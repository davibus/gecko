"""Safe, provenance-aware full-description retrieval shared by Scout and Gecko."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Callable, Iterable
from urllib.parse import urlsplit

from enrichment import EnrichmentCandidate, _greenhouse_candidates, _page_candidates
from models import JobListing
from normalize import canonicalize_url, clean_text
from sources.base import ProviderError
from sources.http import FetchedDocument, get_document
from url_resolution import (
    apply_resolution,
    classify_url,
    resolve_authoritative_url,
)


MINIMUM_FULL_DESCRIPTION = 600
MAX_FOLLOW_PAGES = 4


@dataclass(frozen=True)
class RetrievalAttempt:
    method: str
    url: str = ""
    outcome: str = ""
    detail: str = ""

    def summary(self) -> str:
        target = f" ({self.url})" if self.url else ""
        detail = f": {self.detail}" if self.detail else ""
        return f"{self.method}{target} - {self.outcome}{detail}"


@dataclass
class DescriptionRetrievalResult:
    status: str
    description: str = ""
    source_url: str = ""
    attempts: list[RetrievalAttempt] = field(default_factory=list)
    authoritative_url: str = ""
    error: str = ""


def description_is_sufficient(value: str) -> bool:
    """Reject provider snippets while accepting substantive saved job text."""
    text = clean_text(value or "")
    return len(text) >= MINIMUM_FULL_DESCRIPTION and not text.endswith(("...", "…"))


def _unique_urls(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = str(value or "").strip()
        if not value or urlsplit(value).scheme not in {"http", "https"}:
            continue
        normalized = canonicalize_url(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _best_candidate(candidates: list[EnrichmentCandidate]) -> EnrichmentCandidate | None:
    viable = [
        candidate for candidate in candidates
        if description_is_sufficient(candidate.description)
        and candidate.title_similarity >= .60
    ]
    if not viable:
        return None
    return max(
        viable,
        key=lambda candidate: (
            candidate.official,
            candidate.structured,
            candidate.title_similarity,
            len(clean_text(candidate.description)),
        ),
    )


def _fetch_candidates(
    job: JobListing,
    url: str,
    method: str,
    fetch: Callable[[str], FetchedDocument],
) -> tuple[EnrichmentCandidate | None, list[RetrievalAttempt]]:
    queue = [url]
    visited: set[str] = set()
    attempts: list[RetrievalAttempt] = []
    candidates: list[EnrichmentCandidate] = []
    while queue and len(visited) < MAX_FOLLOW_PAGES:
        current = queue.pop(0)
        normalized = canonicalize_url(current)
        if not normalized or normalized in visited:
            continue
        visited.add(normalized)
        try:
            document = fetch(normalized)
        except (ProviderError, OSError, ValueError) as error:
            attempts.append(RetrievalAttempt(method, normalized, "failed", str(error)))
            continue
        content_type = document.content_type.lower()
        found: list[EnrichmentCandidate] = []
        follow_urls: list[str] = []
        if content_type in {"application/json", "application/ld+json"}:
            try:
                payload = json.loads(document.body.decode("utf-8", errors="replace"))
                if isinstance(payload, dict):
                    found.extend(_greenhouse_candidates(payload, job))
            except (json.JSONDecodeError, UnicodeDecodeError):
                attempts.append(RetrievalAttempt(method, normalized, "failed", "invalid structured JSON"))
                continue
        elif content_type in {"text/html", "application/xhtml+xml", ""}:
            page = document.body.decode("utf-8", errors="replace")
            found, follow_urls = _page_candidates(page, document.final_url, job)
        else:
            attempts.append(RetrievalAttempt(
                method, normalized, "failed", f"unsupported content type {content_type or 'unknown'}"
            ))
            continue
        candidates.extend(found)
        longest = max((len(clean_text(item.description)) for item in found), default=0)
        attempts.append(RetrievalAttempt(
            method,
            canonicalize_url(document.final_url) or normalized,
            "candidate found" if longest else "no usable description",
            f"longest candidate {longest} characters" if longest else "no structured or semantic job text",
        ))
        for follow_url in _unique_urls(follow_urls):
            if classify_url(follow_url) == "aggregator_intermediary":
                continue
            if follow_url not in visited and follow_url not in queue:
                queue.append(follow_url)
    return _best_candidate(candidates), attempts


def retrieve_full_description(
    job: JobListing,
    *,
    authoritative_urls: Iterable[str] = (),
    redirect_urls: Iterable[str] = (),
    ats_urls: Iterable[str] = (),
    aggregator_urls: Iterable[str] = (),
    fetch: Callable[[str], FetchedDocument] = get_document,
    search_urls=None,
    prefer_fuller: bool = False,
) -> DescriptionRetrievalResult:
    """Follow Gecko's safe fallback order without evading blocked sources."""
    attempts: list[RetrievalAttempt] = []
    stored = [
        ("stored enriched description", job.enriched_description, job.enriched_source_url),
        ("stored description", job.description, job.original_url or job.url),
    ]
    sufficient = [entry for entry in stored if description_is_sufficient(entry[1])]
    for method, description, source_url in stored:
        length = len(clean_text(description or ""))
        attempts.append(RetrievalAttempt(
            method,
            source_url or "",
            "accepted" if description_is_sufficient(description) else "insufficient",
            f"{length} characters; minimum {MINIMUM_FULL_DESCRIPTION}",
        ))
    best_description = ""
    best_url = ""
    if sufficient:
        _, best_description, best_url = max(sufficient, key=lambda entry: len(clean_text(entry[1])))
        if not prefer_fuller:
            return DescriptionRetrievalResult(
                "succeeded", clean_text(best_description), best_url, attempts,
                authoritative_url=job.authoritative_url,
            )

    groups = [
        ("authoritative employer or ATS URL", _unique_urls([
            job.authoritative_url, *authoritative_urls,
        ])),
        ("resolved redirect destination", _unique_urls([
            job.url_redirect_url, *redirect_urls,
        ])),
        ("known ATS or structured source", _unique_urls([
            job.enriched_source_url,
            *(link.get("url", "") for link in job.source_links
              if classify_url(link.get("url", "")) == "official_ats"),
            *(url for url in ats_urls if classify_url(url) == "official_ats"),
        ])),
    ]
    tried: set[str] = set()
    for method, urls in groups:
        for url in urls:
            if url in tried:
                continue
            tried.add(url)
            candidate, detail = _fetch_candidates(job, url, method, fetch)
            attempts.extend(detail)
            if candidate and len(clean_text(candidate.description)) > len(clean_text(best_description)):
                best_description = candidate.description
                best_url = candidate.source_url
                if not prefer_fuller:
                    return DescriptionRetrievalResult(
                        "succeeded", clean_text(best_description), canonicalize_url(best_url), attempts,
                        authoritative_url=job.authoritative_url or canonicalize_url(best_url),
                    )

    try:
        resolution = resolve_authoritative_url(
            job,
            fetch=fetch,
            search_urls=search_urls,
            include_discovery=False,
        ) if search_urls is not None else resolve_authoritative_url(
            job,
            fetch=fetch,
            include_discovery=False,
        )
        attempts.append(RetrievalAttempt(
            "authoritative search or re-resolution",
            resolution.authoritative_url or resolution.redirect_url,
            resolution.status,
            resolution.error or f"confidence {resolution.confidence}",
        ))
        if resolution.status == "verified" and resolution.authoritative_url:
            apply_resolution(job, resolution)
            url = canonicalize_url(resolution.authoritative_url)
            if url not in tried:
                tried.add(url)
                candidate, detail = _fetch_candidates(
                    job, url, "authoritative search result", fetch
                )
                attempts.extend(detail)
                if candidate and len(clean_text(candidate.description)) > len(clean_text(best_description)):
                    best_description = candidate.description
                    best_url = candidate.source_url
    except (ProviderError, OSError, ValueError) as error:
        attempts.append(RetrievalAttempt(
            "authoritative search or re-resolution", outcome="failed", detail=str(error)
        ))

    originals = _unique_urls([
        *aggregator_urls,
        job.original_url,
        job.url,
        job.canonical_url,
        *(link.get("url", "") for link in job.source_links
          if classify_url(link.get("url", "")) == "aggregator_intermediary"),
    ])
    for url in originals:
        if url in tried:
            continue
        tried.add(url)
        candidate, detail = _fetch_candidates(job, url, "original aggregator URL", fetch)
        attempts.extend(detail)
        if candidate and len(clean_text(candidate.description)) > len(clean_text(best_description)):
            best_description = candidate.description
            best_url = candidate.source_url

    if description_is_sufficient(best_description):
        return DescriptionRetrievalResult(
            "succeeded",
            clean_text(best_description),
            canonicalize_url(best_url) if best_url else "",
            attempts,
            authoritative_url=job.authoritative_url,
        )
    reason = (
        f"No source produced a complete description of at least "
        f"{MINIMUM_FULL_DESCRIPTION} characters."
    )
    return DescriptionRetrievalResult(
        "failed", attempts=attempts, authoritative_url=job.authoritative_url,
        error=reason,
    )
