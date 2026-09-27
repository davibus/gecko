"""Indeed search and manual-URL retrieval adapters."""

from __future__ import annotations

import os
import html
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import FetchedDocument, get_document, get_json


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
        page = document.body.decode("utf-8", errors="replace")
        for block in SCRIPT_RE.findall(page):
            try:
                payload = json.loads(html.unescape(block).strip())
            except json.JSONDecodeError:
                continue
            for item in _job_nodes(payload):
                organization = item.get("hiringOrganization") or {}
                listing = RawListing(
                    source=self.name,
                    source_job_id=job_key,
                    url=url.strip(),
                    title=_text(item.get("title")),
                    company=_text(organization),
                    location=_location(item.get("jobLocation") or item.get("applicantLocationRequirements")),
                    description=_text(item.get("description")),
                    employment_type=_text(item.get("employmentType")),
                    salary=_salary(item.get("baseSalary")),
                    date_posted=_text(item.get("datePosted")),
                    remote_type="remote" if item.get("jobLocationType") == "TELECOMMUTE" else "",
                    metadata=dict(item),
                )
                if listing.title and listing.company and listing.description:
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
