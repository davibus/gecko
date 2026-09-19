"""Structured/public-text enrichment for provisional Adzuna matches."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from models import JobListing
from normalize import canonicalize_url, clean_text
from scoring import score_job
from sources.base import ProviderError
from sources.http import FetchedDocument, get_document
from sources.web import SCRIPT_RE, _job_nodes, _text
from storage import JobStore


MINIMUM_GAIN = 200
MAX_PAGES = 6


@dataclass
class EnrichmentCandidate:
    description: str
    source_url: str
    structured: bool
    official: bool
    title_similarity: float


@dataclass
class EnrichmentResult:
    status: str
    description: str = ""
    source_url: str = ""
    error: str = ""


class _SemanticTextParser(HTMLParser):
    """Extract text only from semantic main/article/itemprop containers."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[bool] = []
        self.capture_count = 0
        self.parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        itemprop = values.get("itemprop", "").lower()
        starts_capture = tag in {"main", "article"} or itemprop in {"description", "jobdescription"}
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(starts_capture)
            self.capture_count += int(starts_capture)
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])

    def handle_endtag(self, _tag):
        if self.stack:
            self.capture_count -= int(self.stack.pop())

    def handle_data(self, data):
        if self.capture_count and data.strip():
            self.parts.append(data.strip())

    @property
    def text(self) -> str:
        return clean_text(" ".join(self.parts))


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _official(url: str) -> bool:
    host = _host(url)
    return bool(host and "adzuna." not in host)


def _title_similarity(expected: str, actual: str) -> float:
    expected_words = set(re.findall(r"[a-z0-9]+", expected.lower()))
    actual_words = set(re.findall(r"[a-z0-9]+", actual.lower()))
    return len(expected_words & actual_words) / max(1, len(expected_words))


def _page_candidates(page: str, page_url: str, job: JobListing) -> tuple[list[EnrichmentCandidate], list[str]]:
    candidates: list[EnrichmentCandidate] = []
    follow_urls: list[str] = []
    for block in SCRIPT_RE.findall(page):
        try:
            data = json.loads(html.unescape(block).strip())
        except json.JSONDecodeError:
            continue
        for node in _job_nodes(data):
            description = clean_text(node.get("description", ""))
            node_url = urljoin(page_url, _text(node.get("url")) or page_url)
            title = _text(node.get("title"))
            if node_url and node_url != page_url:
                follow_urls.append(node_url)
            if description:
                candidates.append(EnrichmentCandidate(
                    description=description,
                    source_url=node_url or page_url,
                    structured=True,
                    official=_official(node_url or page_url),
                    title_similarity=_title_similarity(job.title, title or job.title),
                ))

    parser = _SemanticTextParser()
    try:
        parser.feed(page)
    except (ValueError, AssertionError):
        pass
    if parser.text:
        candidates.append(EnrichmentCandidate(
            description=parser.text,
            source_url=page_url,
            structured=False,
            official=_official(page_url),
            title_similarity=_title_similarity(job.title, parser.text[:500]),
        ))
    follow_urls.extend(urljoin(page_url, link) for link in parser.links
                       if re.search(r"\b(apply|career|job|position)\b", link, re.I))
    canonical = re.findall(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', page, re.I,
    )
    follow_urls.extend(urljoin(page_url, value) for value in canonical)
    board_ids = re.findall(r'(?:GREENHOUSE_BOARD_ID|boards\.greenhouse\.io/)(?:["\':=\\u002F]+)([a-z0-9_-]+)', page, re.I)
    follow_urls.extend(
        f"https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs?content=true"
        for board_id in board_ids
    )
    return candidates, list(dict.fromkeys(follow_urls))


def _greenhouse_candidates(payload: dict, job: JobListing) -> list[EnrichmentCandidate]:
    candidates = []
    for item in payload.get("jobs", []):
        title = _text(item.get("title"))
        similarity = _title_similarity(job.title, title)
        description = clean_text(item.get("content", ""))
        source_url = _text(item.get("absolute_url"))
        if description and source_url and similarity >= .25:
            candidates.append(EnrichmentCandidate(
                description=description,
                source_url=source_url,
                structured=True,
                official=True,
                title_similarity=similarity,
            ))
    return candidates


def enrich_listing(job: JobListing, fetch=get_document) -> EnrichmentResult:
    """Retrieve a fuller description through redirects and structured public markup."""
    if job.source.lower() != "adzuna" or job.match_score < 80 or not job.provisional:
        return EnrichmentResult("failed", error="Job is not an eligible provisional Adzuna 80+ match.")

    queue = list(dict.fromkeys(filter(None, [job.url, job.canonical_url] + [
        link.get("url", "") for link in job.source_links
    ] + [value.rstrip(".,);]") for value in re.findall(r"https?://[^\s<>\"']+", job.description)])))
    visited: set[str] = set()
    candidates: list[EnrichmentCandidate] = []
    errors: list[str] = []
    while queue and len(visited) < MAX_PAGES:
        url = queue.pop(0)
        if url in visited or urlsplit(url).scheme not in {"http", "https"}:
            continue
        visited.add(url)
        try:
            document: FetchedDocument = fetch(url)
        except (ProviderError, OSError, ValueError) as error:
            errors.append(str(error))
            continue
        content_type = document.content_type.lower()
        if content_type in {"application/json", "application/ld+json"}:
            try:
                candidates.extend(_greenhouse_candidates(json.loads(document.body), job))
            except (json.JSONDecodeError, UnicodeDecodeError):
                errors.append("Structured career endpoint returned invalid JSON.")
            continue
        if content_type not in {"text/html", "application/xhtml+xml", ""}:
            errors.append(f"Unsupported content type: {content_type}")
            continue
        page = document.body.decode("utf-8", errors="replace")
        page_candidates, follow_urls = _page_candidates(page, document.final_url, job)
        candidates.extend(page_candidates)
        for follow_url in follow_urls:
            if follow_url not in visited and follow_url not in queue:
                queue.append(follow_url)

    minimum_length = len(job.description) + max(MINIMUM_GAIN, len(job.description) // 5)
    viable = [candidate for candidate in candidates
              if len(candidate.description) >= minimum_length and candidate.title_similarity >= .25]
    if not viable:
        detail = errors[-1] if errors else "No fuller structured or semantic job description was found."
        return EnrichmentResult("failed", error=detail)
    viable.sort(key=lambda value: (
        value.official, value.structured, value.title_similarity, len(value.description)
    ), reverse=True)
    best = viable[0]
    return EnrichmentResult("succeeded", best.description, canonicalize_url(best.source_url))


def enrich_and_rescore(
    job: JobListing,
    store: JobStore,
    preferences: dict,
    resume_text: str,
    fetch=get_document,
) -> JobListing:
    """Preserve original evidence, enrich, rescore, and persist the final classification."""
    if job.enrichment_status == "not_attempted":
        job.original_description = job.description
        job.original_match_score = job.match_score
        job.original_evidence_confidence = job.evidence_confidence
        job.original_url = job.url

    outcome = enrich_listing(job, fetch=fetch)
    job.enriched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    job.enrichment_status = outcome.status
    job.enrichment_error = outcome.error
    if outcome.status == "succeeded":
        job.enriched_description = outcome.description
        job.enriched_source_url = outcome.source_url
        enriched_job = replace(job, description=outcome.description)
        result = score_job(enriched_job, preferences, resume_text)
        job.enriched_match_score = result.total
        job.enriched_evidence_confidence = result.confidence
        job.match_score = result.total
        job.evidence_confidence = result.confidence
        job.evidence_levels = result.evidence_levels
        job.match_strengths = result.strengths
        job.match_weaknesses = result.weaknesses
        job.provisional = result.total >= preferences["minimum_score"] and result.confidence < 65
        if job.provisional and not any("80+ provisional" in item for item in job.match_weaknesses):
            job.match_weaknesses.append("80+ provisional — full description recommended.")
        store.update_scoring(job, retained=job.match_score >= preferences["minimum_score"])
    else:
        job.provisional = True
        job.enriched_description = ""
        job.enriched_source_url = ""
        job.enriched_match_score = 0
        job.enriched_evidence_confidence = 0
    store.save_enrichment(job)
    return job
