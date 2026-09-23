"""Career-page discovery via supported search APIs and JobPosting JSON-LD."""

from __future__ import annotations

import html
import json
import os
import re
from urllib.parse import urlencode, urljoin

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_bytes, get_json


SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def _job_nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from _job_nodes(item)
    elif isinstance(value, dict):
        if value.get("@type") == "JobPosting" or "JobPosting" in (value.get("@type") or []):
            yield value
        for key in ("@graph", "itemListElement"):
            if key in value:
                yield from _job_nodes(value[key])


def _text(value) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("value") or ""
    return str(value or "")


class WebCareerProvider(JobSource):
    """Uses configured web-search APIs, then reads schema.org JobPosting data."""

    name = "web-careers"

    def __init__(self):
        self.google_key = os.getenv("GOOGLE_CSE_API_KEY", "")
        self.google_cx = os.getenv("GOOGLE_CSE_ID", "")
        self.google_cse_enabled = os.getenv("GOOGLE_CSE_ENABLED", "false").strip().casefold() in {
            "1", "true", "yes", "on",
        }
        self.brave_key = os.getenv("BRAVE_SEARCH_API_KEY", "")
        self.search_results_returned = 0
        self.brave_search_results_returned = 0
        self.google_cse_search_results_returned = 0
        self.pages_fetched = 0
        self.valid_job_postings_extracted = 0
        self.errors: list[dict[str, str]] = []
        self.search_queries: list[dict] = []
        self.backend_stats = {
            "brave": {
                "configured": bool(self.brave_key), "used": False,
                "results_fetched": 0, "pages_fetched": 0,
                "valid_job_postings_extracted": 0,
            },
            "google-cse": {
                "configured": bool(self.google_key and self.google_cx),
                "enabled": self.google_cse_enabled,
                "active": bool(
                    self.google_cse_enabled and self.google_key and self.google_cx
                ),
                "used": False,
                "results_fetched": 0, "pages_fetched": 0,
                "valid_job_postings_extracted": 0,
            },
        }

    @property
    def backend(self) -> str:
        if self.brave_key:
            return "brave"
        if self.backend_stats["google-cse"]["active"]:
            return "google-cse"
        return ""

    def configured(self) -> bool:
        return bool(self.brave_key or self.backend_stats["google-cse"]["active"])

    @property
    def backends(self) -> list[str]:
        return [
            name for name, stats in self.backend_stats.items()
            if stats.get("active", stats["configured"])
        ]

    def diagnostics(
        self,
        *,
        jobs_added: int = 0,
        backend_qualifying: dict[str, int] | None = None,
        backend_added: dict[str, int] | None = None,
    ) -> dict:
        """Return run counters without including credentials or credential-bearing URLs."""
        backend_qualifying = backend_qualifying or {}
        backend_added = backend_added or {}
        google_errors = [
            error for error in self.errors
            if error.get("stage") == "google-cse-api"
            or "google-cse" in error.get("backends", [])
        ]
        google_cse = {
            **self.backend_stats["google-cse"],
            "skipped": not self.backend_stats["google-cse"]["active"],
            "skip_reason": (
                "disabled" if not self.google_cse_enabled
                else "missing_credentials"
                if not self.backend_stats["google-cse"]["configured"] else ""
            ),
            "qualifying": backend_qualifying.get("google-cse", 0),
            "added": backend_added.get("google-cse", 0),
            "errors": google_errors,
        }
        return {
            "configured": self.configured(),
            "backend": self.backend,
            "backends": self.backends,
            "brave_used": self.backend == "brave",
            "google_cse_configured": self.backend_stats["google-cse"]["configured"],
            "google_cse_enabled": self.google_cse_enabled,
            "google_cse_used": self.backend_stats["google-cse"]["used"],
            "search_results_returned": self.search_results_returned,
            "brave_search_results_returned": self.brave_search_results_returned,
            "google_cse_search_results_returned": self.google_cse_search_results_returned,
            "pages_fetched": self.pages_fetched,
            "valid_job_postings_extracted": self.valid_job_postings_extracted,
            "jobs_added": jobs_added,
            "google_cse": google_cse,
            "search_queries": list(self.search_queries),
            "errors": list(self.errors),
        }

    def _safe_error(self, error: ProviderError) -> str:
        message = str(error)
        for secret in (self.brave_key, self.google_key, self.google_cx):
            if secret:
                message = message.replace(secret, "[REDACTED]")
        return message

    def _query(self, request: SearchRequest) -> str:
        query = f'{request.query} jobs (site:jobs.lever.co OR site:boards.greenhouse.io OR inurl:careers)'
        if request.location:
            query += f" {request.location}"
        return query

    def _result_urls(self, backend: str, request: SearchRequest, query: str) -> list[str]:
        if backend == "brave":
            url = "https://api.search.brave.com/res/v1/web/search?" + urlencode({
                "q": query, "count": min(request.results_per_page, 20),
                "offset": min(max(request.page - 1, 0), 9), "country": "US", "search_lang": "en",
            })
            payload = get_json(url, {"X-Subscription-Token": self.brave_key})
            return [item.get("url", "") for item in payload.get("web", {}).get("results", [])]
        if backend == "google-cse":
            url = "https://customsearch.googleapis.com/customsearch/v1?" + urlencode({
                "key": self.google_key, "cx": self.google_cx, "q": query,
                "num": min(request.results_per_page, 10), "start": (request.page - 1) * 10 + 1,
            })
            return [item.get("link", "") for item in get_json(url).get("items", [])]
        raise ProviderError(f"Unsupported web-search backend: {backend}")

    def search(self, request: SearchRequest):
        query = self._query(request)
        self.search_queries.append({
            "query": query, "role": request.query, "location": request.location,
            "backends": self.backends,
        })
        url_backends: dict[str, set[str]] = {}
        for backend in self.backends:
            self.backend_stats[backend]["used"] = True
            try:
                result_urls = self._result_urls(backend, request, query)
            except ProviderError as error:
                self.errors.append({
                    "stage": f"{backend}-api",
                    "query": request.query,
                    "location": request.location,
                    "error": self._safe_error(error),
                })
                continue
            count = len(result_urls)
            self.search_results_returned += count
            self.backend_stats[backend]["results_fetched"] += count
            if backend == "brave":
                self.brave_search_results_returned += count
            else:
                self.google_cse_search_results_returned += count
            for url in result_urls:
                if url:
                    url_backends.setdefault(url, set()).add(backend)

        for url, discovery_backends in url_backends.items():
            if not url:
                continue
            try:
                page = get_bytes(url).decode("utf-8", errors="replace")
                self.pages_fetched += 1
                for backend in discovery_backends:
                    self.backend_stats[backend]["pages_fetched"] += 1
            except ProviderError as error:
                self.errors.append({
                    "stage": "page-fetch",
                    "url": url,
                    "backends": sorted(discovery_backends),
                    "error": self._safe_error(error),
                })
                continue
            for block in SCRIPT_RE.findall(page):
                try:
                    data = json.loads(html.unescape(block).strip())
                except json.JSONDecodeError:
                    continue
                for item in _job_nodes(data):
                    org = item.get("hiringOrganization") or {}
                    location = item.get("jobLocation") or item.get("applicantLocationRequirements") or ""
                    if isinstance(location, list):
                        location = ", ".join(_text(part) for part in location)
                    elif isinstance(location, dict):
                        address = location.get("address", location)
                        if isinstance(address, dict):
                            location = ", ".join(filter(None, [
                                _text(address.get("addressLocality")), _text(address.get("addressRegion")),
                                _text(address.get("addressCountry")),
                            ]))
                    identifier = item.get("identifier") or {}
                    job_id = _text(identifier) or _text(item.get("url")) or url
                    metadata = dict(item)
                    metadata["_web_search_backends"] = sorted(discovery_backends)
                    listing = RawListing(
                        source=self.name,
                        source_job_id=job_id,
                        url=urljoin(url, item.get("url") or url),
                        title=_text(item.get("title")),
                        company=_text(org),
                        location=_text(location),
                        description=_text(item.get("description")),
                        employment_type=_text(item.get("employmentType")),
                        salary=_text(item.get("baseSalary")),
                        date_posted=_text(item.get("datePosted")),
                        remote_type="remote" if item.get("jobLocationType") == "TELECOMMUTE" else "",
                        metadata=metadata,
                    )
                    if listing.title and listing.description:
                        self.valid_job_postings_extracted += 1
                        for backend in discovery_backends:
                            self.backend_stats[backend]["valid_job_postings_extracted"] += 1
                    yield listing
