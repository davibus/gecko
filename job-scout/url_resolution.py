"""Resolve provider discovery links to verified employer or ATS job postings."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

from models import JobListing
from normalize import canonicalize_url, clean_text
from sources.base import ProviderError, SearchRequest
from sources.http import FetchedDocument, get_document
from sources.web import SCRIPT_RE, WebCareerProvider, _job_nodes, _text


CONFIG_PATH = Path(__file__).resolve().parent / "preferences" / "url_resolution.json"
EXPIRED_RE = re.compile(
    r"\b(job|position|posting)\s+(?:is\s+)?(?:no longer available|closed|expired|filled)\b",
    re.I,
)
LEGAL_SUFFIX_RE = re.compile(
    r"\b(?:incorporated|inc|llc|ltd|limited|corp|corporation|company|co|plc)\b", re.I,
)


@dataclass(frozen=True)
class ResolutionConfig:
    aggregator_hosts: tuple[str, ...]
    ats_hosts: tuple[str, ...]
    minimum_confidence: int = 82
    ambiguity_margin: int = 8
    maximum_search_results: int = 8


@dataclass
class URLCandidate:
    url: str
    destination_type: str
    title: str = ""
    company: str = ""
    location: str = ""
    identifier: str = ""
    date_posted: str = ""
    structured: bool = False
    expired: bool = False
    confidence: int = 0


@dataclass(frozen=True)
class URLResolutionResult:
    status: str
    authoritative_url: str = ""
    confidence: int = 0
    destination_type: str = "unknown"
    redirect_url: str = ""
    error: str = ""


@lru_cache(maxsize=4)
def load_resolution_config(path: str | Path = CONFIG_PATH) -> ResolutionConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ResolutionConfig(
        aggregator_hosts=tuple(value.lower().lstrip(".") for value in payload["aggregator_hosts"]),
        ats_hosts=tuple(value.lower().lstrip(".") for value in payload["ats_hosts"]),
        minimum_confidence=int(payload.get("minimum_confidence", 82)),
        ambiguity_margin=int(payload.get("ambiguity_margin", 8)),
        maximum_search_results=int(payload.get("maximum_search_results", 8)),
    )


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _host_matches(host: str, patterns: tuple[str, ...]) -> bool:
    return any(host == pattern or host.endswith("." + pattern) for pattern in patterns)


def classify_url(url: str, config: ResolutionConfig | None = None) -> str:
    """Classify host trust without claiming that an individual job is verified."""
    config = config or load_resolution_config()
    host = _host(url)
    if not host:
        return "dead_unavailable"
    if _host_matches(host, config.aggregator_hosts):
        return "aggregator_intermediary"
    if _host_matches(host, config.ats_hosts):
        return "official_ats"
    return "unknown"


def _words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _normalized_company(value: str) -> str:
    return " ".join(LEGAL_SUFFIX_RE.sub(" ", clean_text(value)).casefold().split())


def _similarity(expected: str, actual: str, *, company: bool = False) -> float:
    if company:
        expected, actual = _normalized_company(expected), _normalized_company(actual)
    else:
        expected, actual = clean_text(expected).casefold(), clean_text(actual).casefold()
    if not expected or not actual:
        return 0.0
    left, right = _words(expected), _words(actual)
    jaccard = len(left & right) / len(left | right) if left and right else 0.0
    sequence = SequenceMatcher(None, expected, actual).ratio()
    containment = 1.0 if expected in actual or actual in expected else 0.0
    return max(jaccard, sequence, containment)


def _location_text(value) -> str:
    if isinstance(value, list):
        return ", ".join(_location_text(item) for item in value)
    if not isinstance(value, dict):
        return _text(value)
    address = value.get("address", value)
    if isinstance(address, dict):
        return ", ".join(filter(None, (
            _text(address.get("addressLocality")), _text(address.get("addressRegion")),
            _text(address.get("addressCountry")),
        )))
    return _text(address)


def _is_expired(value: str, page_text: str) -> bool:
    if EXPIRED_RE.search(page_text):
        return True
    if not value:
        return False
    try:
        return datetime.fromisoformat(value[:10]).date() < date.today()
    except ValueError:
        return False


def _structured_candidates(page: str, page_url: str, config: ResolutionConfig) -> list[URLCandidate]:
    candidates: list[URLCandidate] = []
    for block in SCRIPT_RE.findall(page):
        try:
            payload = json.loads(html.unescape(block).strip())
        except json.JSONDecodeError:
            continue
        for node in _job_nodes(payload):
            organization = node.get("hiringOrganization") or {}
            identifier = node.get("identifier") or {}
            node_url = canonicalize_url(urljoin(page_url, _text(node.get("url")) or page_url))
            destination_type = classify_url(node_url, config)
            if destination_type == "unknown":
                destination_type = "official_employer_domain"
            candidates.append(URLCandidate(
                url=node_url,
                destination_type=destination_type,
                title=_text(node.get("title")),
                company=_text(organization),
                location=_location_text(node.get("jobLocation") or node.get("applicantLocationRequirements")),
                identifier=_text(identifier),
                date_posted=_text(node.get("datePosted")),
                structured=True,
                expired=_is_expired(_text(node.get("validThrough")), clean_text(page)),
            ))
    return candidates


def _page_candidates(document: FetchedDocument, job: JobListing, config: ResolutionConfig) -> list[URLCandidate]:
    final_url = canonicalize_url(document.final_url)
    destination_type = classify_url(final_url, config)
    if document.content_type.lower() not in {"text/html", "application/xhtml+xml", ""}:
        return []
    page = document.body.decode("utf-8", errors="replace")
    candidates = _structured_candidates(page, final_url, config)
    if candidates:
        return candidates
    page_text = clean_text(page)
    title_match = _similarity(job.title, page_text[:2000])
    company_match = _similarity(job.company, page_text[:3000], company=True)
    if destination_type == "unknown" and title_match >= .8 and company_match >= .8:
        destination_type = "direct_employer_listing"
    canonical_matches = re.findall(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', page, re.I,
    )
    url = canonicalize_url(urljoin(final_url, canonical_matches[0])) if canonical_matches else final_url
    return [URLCandidate(
        url=url,
        destination_type=destination_type,
        title=job.title if title_match >= .8 else page_text[:500],
        company=job.company if company_match >= .8 else "",
        location=job.location if _similarity(job.location, page_text) >= .6 else "",
        structured=False,
        expired=_is_expired("", page_text),
    )]


def _candidate_links(document: FetchedDocument, config: ResolutionConfig) -> list[str]:
    """Extract likely application links without accepting the current intermediary."""
    if document.content_type.lower() not in {"text/html", "application/xhtml+xml", ""}:
        return []
    page = document.body.decode("utf-8", errors="replace")
    links = re.findall(r'<a[^>]+href=["\']([^"\']+)', page, re.I)
    links += re.findall(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', page, re.I)
    candidates = []
    for value in links:
        url = canonicalize_url(urljoin(document.final_url, html.unescape(value)))
        kind = classify_url(url, config)
        if urlsplit(url).scheme not in {"http", "https"} or kind == "aggregator_intermediary":
            continue
        if kind == "official_ats" or re.search(r"\b(apply|career|job|position|opening)\b", value, re.I):
            candidates.append(url)
    return list(dict.fromkeys(candidates))


def _candidate_confidence(candidate: URLCandidate, job: JobListing) -> int:
    if candidate.expired or candidate.destination_type in {
        "aggregator_intermediary", "unknown", "dead_unavailable",
    }:
        return 0
    title = _similarity(job.title, candidate.title)
    company = _similarity(job.company, candidate.company, company=True)
    if title < .72 or company < .72:
        return 0
    destination = {
        "official_employer_domain": .28,
        "official_ats": .20,
        "direct_employer_listing": .18,
    }.get(candidate.destination_type, 0)
    location = _similarity(job.location, candidate.location) if job.location and candidate.location else .5
    job_id = 1.0 if candidate.identifier and candidate.identifier.casefold() in job.description.casefold() else 0.0
    recency = 1.0 if candidate.date_posted and candidate.date_posted[:10] == job.date_posted[:10] else .5
    confidence = destination + title * .32 + company * .28 + location * .06 + job_id * .04 + recency * .02
    if candidate.structured:
        confidence += .03
    return min(100, round(confidence * 100))


def _discovery_url(job: JobListing) -> str:
    jooble = [
        link.get("url", "") for link in job.source_links
        if link.get("source", "").casefold() == "jooble" and link.get("url")
    ]
    if jooble:
        away = next((url for url in jooble if "/away/" in url), None)
        return away or jooble[-1]
    return job.url or job.canonical_url


def _default_search_urls(job: JobListing, maximum: int) -> list[str]:
    provider = WebCareerProvider()
    if not provider.configured():
        return []
    query = f'"{job.company}" "{job.title}"'
    request = SearchRequest(query, job.location, results_per_page=maximum)
    result_urls: list[str] = []
    for backend in provider.backends:
        try:
            result_urls.extend(provider._result_urls(backend, request, query))
        except ProviderError:
            continue
    return result_urls[:maximum]


def resolve_authoritative_url(
    job: JobListing,
    *,
    fetch: Callable[[str], FetchedDocument] = get_document,
    search_urls: Callable[[JobListing, int], list[str]] = _default_search_urls,
    config: ResolutionConfig | None = None,
    include_discovery: bool = True,
) -> URLResolutionResult:
    """Resolve one job without changing fit scoring or persisted job fields."""
    config = config or load_resolution_config()
    discovery_url = _discovery_url(job)
    redirect_url = ""
    errors: list[str] = []
    direct_candidates: list[URLCandidate] = []
    linked_urls: list[str] = []
    if include_discovery:
        try:
            document = fetch(discovery_url)
            redirect_url = canonicalize_url(document.final_url)
            direct_candidates = _page_candidates(document, job, config)
            linked_urls = _candidate_links(document, config)
        except (ProviderError, OSError, ValueError) as error:
            errors.append(str(error))

    for candidate in direct_candidates:
        candidate.confidence = _candidate_confidence(candidate, job)
    verified_direct = [candidate for candidate in direct_candidates
                       if candidate.confidence >= config.minimum_confidence]
    if verified_direct:
        best = max(verified_direct, key=lambda item: item.confidence)
        return URLResolutionResult(
            status="verified", authoritative_url=best.url, confidence=best.confidence,
            destination_type=best.destination_type, redirect_url=redirect_url,
        )

    candidates: list[URLCandidate] = []
    try:
        result_urls = search_urls(job, config.maximum_search_results)
    except (ProviderError, OSError, ValueError) as error:
        result_urls = []
        errors.append(str(error))
    existing_urls = [job.enriched_source_url, job.authoritative_url] + [
        link.get("url", "") for link in job.source_links
    ]
    discovery_host = _host(discovery_url)
    existing_urls = [url for url in existing_urls if url and _host(url) != discovery_host]
    result_urls = linked_urls + existing_urls + result_urls
    for url in list(dict.fromkeys(filter(None, result_urls)))[:config.maximum_search_results]:
        if canonicalize_url(url) == canonicalize_url(discovery_url):
            continue
        try:
            candidates.extend(_page_candidates(fetch(url), job, config))
        except (ProviderError, OSError, ValueError) as error:
            errors.append(str(error))
    for candidate in candidates:
        candidate.confidence = _candidate_confidence(candidate, job)
    viable = sorted(
        (candidate for candidate in candidates if candidate.confidence >= config.minimum_confidence),
        key=lambda item: item.confidence,
        reverse=True,
    )
    if viable and (len(viable) == 1 or viable[0].confidence - viable[1].confidence >= config.ambiguity_margin):
        best = viable[0]
        return URLResolutionResult(
            status="verified", authoritative_url=best.url, confidence=best.confidence,
            destination_type=best.destination_type, redirect_url=redirect_url,
        )

    redirect_type = classify_url(redirect_url or discovery_url, config)
    if viable:
        status = "authoritative_url_not_found"
        error = "Several authoritative candidates were too ambiguous to select safely."
    elif not redirect_url and include_discovery:
        status = "dead_unavailable"
        error = "Discovery URL was unavailable and no authoritative match was verified."
    elif not redirect_url:
        status = "authoritative_url_not_found"
        error = "No authoritative employer or ATS posting was verified by search."
    elif redirect_type == "aggregator_intermediary":
        status = "authoritative_url_not_found"
        error = "Redirect remained on an aggregator and no authoritative match was verified."
    else:
        status = "jooble_redirect_only" if _host(discovery_url).endswith("jooble.org") else "unverified"
        error = "Destination could not be verified as the matching employer posting."
    if errors:
        error = f"{error} Last error: {errors[-1]}"
    return URLResolutionResult(
        status=status, destination_type=redirect_type, redirect_url=redirect_url, error=error,
    )


def apply_resolution(job: JobListing, result: URLResolutionResult) -> JobListing:
    job.url_verification_status = result.status
    job.authoritative_url = result.authoritative_url
    job.authoritative_url_confidence = result.confidence
    job.url_destination_type = result.destination_type
    job.url_redirect_url = result.redirect_url
    job.url_resolution_error = result.error
    job.url_resolved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return job


def resolve_and_store(job: JobListing, store, **kwargs) -> JobListing:
    """Resolve and persist URL metadata without touching match-score fields."""
    apply_resolution(job, resolve_authoritative_url(job, **kwargs))
    store.save_url_resolution(job)
    return job


def best_job_url(job: JobListing) -> str:
    """Return the safest application link without losing provider history."""
    if job.url_verification_status == "verified" and job.authoritative_url:
        return job.authoritative_url
    return job.enriched_source_url or job.canonical_url or job.url


def url_status_label(job: JobListing) -> str:
    if job.url_verification_status == "verified":
        labels = {
            "official_employer_domain": "Verified - Official employer",
            "official_ats": "Verified - Official ATS",
            "direct_employer_listing": "Verified - Direct employer listing",
        }
        return labels.get(job.url_destination_type, "Verified")
    return {
        "jooble_redirect_only": "Jooble redirect only",
        "authoritative_url_not_found": "Stale / authoritative posting not found",
        "dead_unavailable": "Stale / unavailable",
        "unverified": "Unverified",
        "not_attempted": "Not checked",
        "": "Not checked",
    }.get(job.url_verification_status, job.url_verification_status.replace("_", " ").title())
