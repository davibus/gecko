"""Indeed search and manual-URL retrieval adapters."""

from __future__ import annotations

import os
import html
import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import FetchedDocument, get_document, get_json
from .web import SearchHit, WebCareerProvider


SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def extract_indeed_job_key(url: str) -> str:
    """Return the stable Indeed ``jk`` query value, ignoring tracking fields."""
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    host = (parts.hostname or "").casefold().rstrip(".")
    if host != "indeed.com" and not host.endswith(".indeed.com"):
        return ""
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.casefold() == "jk" and value.strip():
            return value.strip()
    return ""


def canonical_indeed_url(url: str) -> str:
    """Canonicalize an Indeed URL to its job key whenever one is available."""
    job_key = extract_indeed_job_key(url)
    if job_key:
        return "https://www.indeed.com/viewjob?" + urlencode({"jk": job_key})
    return ""


def _job_nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from _job_nodes(item)
    elif isinstance(value, dict):
        kind = value.get("@type")
        if kind == "JobPosting" or "JobPosting" in (kind if isinstance(kind, list) else []):
            yield value
        for key in ("@graph", "itemListElement"):
            if key in value:
                yield from _job_nodes(value[key])


def _text(value) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("value") or ""
    return str(value or "")


def _location(value) -> str:
    if isinstance(value, list):
        return ", ".join(filter(None, (_location(item) for item in value)))
    if not isinstance(value, dict):
        return _text(value)
    address = value.get("address", value)
    if not isinstance(address, dict):
        return _text(address)
    return ", ".join(filter(None, (
        _text(address.get("addressLocality")),
        _text(address.get("addressRegion")),
        _text(address.get("addressCountry")),
    )))


def _salary(value) -> str:
    if not isinstance(value, dict):
        return _text(value)
    currency = _text(value.get("currency"))
    amount = value.get("value", value)
    if not isinstance(amount, dict):
        return " ".join(filter(None, (currency, _text(amount))))
    minimum = _text(amount.get("minValue"))
    maximum = _text(amount.get("maxValue"))
    exact = _text(amount.get("value"))
    amount_text = (f"{minimum}-{maximum}" if minimum and maximum else
                   minimum or maximum or exact)
    unit = _text(amount.get("unitText"))
    return " ".join(filter(None, (currency, amount_text, f"per {unit}" if unit else "")))


def _structured_listings(document: FetchedDocument) -> list[RawListing]:
    """Extract complete JobPosting records from any public result page."""
    content_type = (document.content_type or "").casefold()
    if content_type not in {"", "text/html", "application/xhtml+xml"}:
        return []
    page = document.body.decode("utf-8", errors="replace")
    listings: list[RawListing] = []
    for block in SCRIPT_RE.findall(page):
        try:
            payload = json.loads(html.unescape(block).strip())
        except json.JSONDecodeError:
            continue
        for item in _job_nodes(payload):
            organization = item.get("hiringOrganization") or {}
            identifier = item.get("identifier") or {}
            listing = RawListing(
                source="web-careers",
                source_job_id=_text(identifier),
                url=urljoin(document.final_url, str(item.get("url") or document.final_url)),
                title=_text(item.get("title")),
                company=_text(organization),
                location=_location(
                    item.get("jobLocation") or item.get("applicantLocationRequirements")
                ),
                description=_text(item.get("description")),
                employment_type=_text(item.get("employmentType")),
                salary=_salary(item.get("baseSalary")),
                date_posted=_text(item.get("datePosted")),
                remote_type="remote" if item.get("jobLocationType") == "TELECOMMUTE" else "",
                metadata=dict(item),
            )
            if listing.title and listing.company and listing.description:
                listings.append(listing)
    return listings


def _identity_text(value: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _evidence_matches(value: str, evidence: str) -> bool:
    expected = _identity_text(value)
    actual = _identity_text(evidence)
    if not expected or not actual:
        return False
    if expected in actual:
        return True
    expected_words = set(expected.split())
    actual_words = set(actual.split())
    overlap = len(expected_words & actual_words) / max(1, len(expected_words))
    return overlap >= .85 or SequenceMatcher(None, expected, actual).ratio() >= .85


def _listing_matches_evidence(listing: RawListing, evidence: str) -> bool:
    return (
        _evidence_matches(listing.title, evidence)
        and _evidence_matches(listing.company, evidence)
        and (not listing.location or _evidence_matches(listing.location, evidence))
    )


def _is_indeed_hit(hit: SearchHit, job_key: str) -> bool:
    return extract_indeed_job_key(hit.url).casefold() == job_key.casefold()


@dataclass(frozen=True)
class IndeedFallbackResult:
    listing: RawListing | None = None
    authoritative_url: str = ""
    destination_type: str = ""
    diagnostics: tuple[str, ...] = field(default_factory=tuple)


class ManualIndeedFallbackRetriever:
    """Recover a blocked Indeed posting through existing web-career discovery."""

    def __init__(self, search: WebCareerProvider | None = None, fetch=get_document):
        self.search = search or WebCareerProvider()
        self.fetch = fetch

    @property
    def search_label(self) -> str:
        return "Brave" if getattr(self.search, "brave_key", "") else "Web Careers"

    def _search(self, query: str, maximum: int = 8) -> tuple[list[SearchHit], list[str]]:
        return self.search.search_hits(query, maximum=maximum)

    def _official_candidates(self, hits: list[SearchHit], job_key: str):
        # Import lazily because URL resolution itself depends on sources.web.
        from url_resolution import classify_url

        for hit in hits:
            if _is_indeed_hit(hit, job_key):
                continue
            if classify_url(hit.url) == "aggregator_intermediary":
                continue
            try:
                document = self.fetch(hit.url)
            except (ProviderError, OSError, ValueError):
                continue
            page_text = document.body.decode("utf-8", errors="replace")
            for listing in _structured_listings(document):
                yield hit, listing, page_text

    def retrieve(self, url: str) -> IndeedFallbackResult:
        job_key = extract_indeed_job_key(url)
        if not job_key:
            return IndeedFallbackResult(diagnostics=(
                f"{self.search_label}=missing Indeed jk", "employer lookup=not attempted",
            ))
        if not self.search.configured():
            return IndeedFallbackResult(diagnostics=(
                f"{self.search_label}=not configured", "employer lookup=not attempted",
            ))

        canonical = canonical_indeed_url(url)
        exact_queries = (f'"{job_key}"', f'"indeed {job_key}"', f'"{canonical}"')
        exact_hits: list[SearchHit] = []
        search_errors: list[str] = []
        seen: set[str] = set()
        for query in exact_queries:
            hits, errors = self._search(query)
            search_errors.extend(errors)
            for hit in hits:
                if hit.url not in seen:
                    seen.add(hit.url)
                    exact_hits.append(hit)

        indeed_hits = [hit for hit in exact_hits if _is_indeed_hit(hit, job_key)]
        indeed_evidence = " ".join(
            f"{hit.title} {hit.description}" for hit in indeed_hits
        )

        def confirmed(listing: RawListing, hit: SearchHit, page_text: str) -> bool:
            identifier_match = _identity_text(listing.source_job_id) == _identity_text(job_key)
            key_exposed = job_key.casefold() in (
                f"{hit.url} {hit.title} {hit.description} {page_text}".casefold()
            )
            identity_match = bool(indeed_evidence) and _listing_matches_evidence(
                listing, indeed_evidence
            )
            return identifier_match or key_exposed or identity_match

        candidate_hits = list(exact_hits)
        for hit, listing, page_text in self._official_candidates(candidate_hits, job_key):
            if confirmed(listing, hit, page_text):
                return self._result(listing, url, job_key)

        # An indexed Indeed result often exposes identity even when its page is blocked.
        # Reuse that evidence to search for the employer-owned copy, then require both
        # strongly normalized title and company matches before accepting it.
        employer_hits: list[SearchHit] = []
        if indeed_evidence:
            for hit in indeed_hits[:2]:
                identity_query = f'"{hit.title}" careers job'
                hits, errors = self._search(identity_query)
                search_errors.extend(errors)
                employer_hits.extend(hits)
        for _hit, listing, _page_text in self._official_candidates(employer_hits, job_key):
            if _listing_matches_evidence(listing, indeed_evidence):
                return self._result(listing, url, job_key)

        search_detail = "no matching result"
        if search_errors and not exact_hits:
            search_detail = search_errors[-1]
        return IndeedFallbackResult(diagnostics=(
            f"{self.search_label}={search_detail}",
            "employer lookup=no confirmed posting",
        ))

    @staticmethod
    def _result(listing: RawListing, original_url: str, job_key: str) -> IndeedFallbackResult:
        from url_resolution import classify_url

        authoritative_url = listing.url
        destination_type = classify_url(authoritative_url)
        if destination_type == "unknown":
            destination_type = "official_employer_domain"
        recovered = RawListing(
            source="Indeed", source_job_id=job_key, url=original_url,
            title=listing.title, company=listing.company, location=listing.location,
            description=listing.description, employment_type=listing.employment_type,
            salary=listing.salary, date_posted=listing.date_posted,
            remote_type=listing.remote_type, category=listing.category,
            tags=list(listing.tags), metadata={
                **listing.metadata,
                "_recovered_from": authoritative_url,
                "_employer_source_job_id": listing.source_job_id,
            },
        )
        return IndeedFallbackResult(
            listing=recovered,
            authoritative_url=authoritative_url,
            destination_type=destination_type,
            diagnostics=("employer lookup=confirmed posting",),
        )


class ManualIndeedProvider:
    """Retrieve a user-supplied Indeed page through a replaceable fetch boundary."""

    name = "indeed"

    def __init__(self, fetch=get_document):
        self.fetch = fetch

    def retrieve(self, url: str) -> RawListing:
        job_key = extract_indeed_job_key(url)
        if not job_key:
            raise ProviderError("Manual intake requires an Indeed URL containing a jk value")
        document: FetchedDocument = self.fetch(url)
        content_type = (document.content_type or "").casefold()
        if content_type not in {"", "text/html", "application/xhtml+xml"}:
            raise ProviderError(f"Indeed returned unsupported content type {content_type}")
        listings = _structured_listings(document)
        if listings:
            listing = listings[0]
            listing.source = self.name
            listing.source_job_id = job_key
            listing.url = url.strip()
            return listing
        raise ProviderError("Indeed page did not contain a complete structured job posting")


class IndeedProvider(JobSource):
    name = "indeed"

    def __init__(self, endpoint: str | None = None, token: str | None = None):
        self.endpoint = endpoint or os.getenv("INDEED_API_ENDPOINT", "")
        self.token = token or os.getenv("INDEED_API_TOKEN", "")

    def configured(self) -> bool:
        return bool(self.endpoint and self.token)

    def search(self, request: SearchRequest):
        if not self.configured():
            raise ProviderError(
                "No authorized Indeed integration is configured; set INDEED_API_ENDPOINT and INDEED_API_TOKEN"
            )
        separator = "&" if "?" in self.endpoint else "?"
        url = self.endpoint + separator + urlencode({
            "q": request.query, "location": request.location,
            "page": request.page, "limit": request.results_per_page,
        })
        payload = get_json(url, {"Authorization": f"Bearer {self.token}"})
        items = payload.get("results") or payload.get("jobs") or []
        for item in items:
            job_id = str(item.get("jobKey") or item.get("jk") or item.get("id") or "")
            yield RawListing(
                source=self.name,
                source_job_id=job_id,
                url=item.get("url") or item.get("jobUrl") or "",
                title=item.get("title") or item.get("jobTitle") or "",
                company=item.get("company") or item.get("companyName") or "",
                location=item.get("location") or item.get("formattedLocation") or "",
                description=item.get("description") or item.get("jobDescription") or "",
                employment_type=item.get("employmentType") or item.get("jobType") or "",
                salary=item.get("salary") or item.get("salaryText") or "",
                date_posted=item.get("datePosted") or item.get("pubDate") or "",
                remote_type=item.get("remoteType") or "",
                metadata=item,
            )
