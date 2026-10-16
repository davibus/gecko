"""Compliant Brave discovery for job boards without generally available APIs."""

from __future__ import annotations

import html
import json
import os
import re
from urllib.parse import urlencode, urljoin, urlsplit

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_document, get_json
from .firecrawl import FirecrawlClient
from .web import SCRIPT_RE, _job_nodes, _text


def _location(value) -> str:
    if isinstance(value, list):
        return ", ".join(filter(None, (_location(item) for item in value)))
    if not isinstance(value, dict):
        return _text(value)
    address = value.get("address", value)
    if not isinstance(address, dict):
        return _text(address)
    return ", ".join(filter(None, (
        _text(address.get("addressLocality")), _text(address.get("addressRegion")),
        _text(address.get("addressCountry")),
    )))


class SearchDiscoveryProvider(JobSource):
    """Find public detail URLs through Brave, then require structured job data."""

    def __init__(self, name: str, site_query: str, api_key: str | None = None):
        self.name = name
        self.site_query = site_query
        match = re.search(r"(?:^|\s)site:([^/\s]+)", site_query, re.I)
        self.site_domain = match.group(1).casefold().rstrip(".") if match else ""
        self.api_key = api_key or os.getenv("BRAVE_SEARCH_API_KEY", "")
        self.errors: list[dict[str, str]] = []
        self.exclusions = []
        self.firecrawl = FirecrawlClient()
        self._documents = {}
        self.discovery_mode = "search-discovery fallback"
        self.broad_queries = (
            "digital marketing", "paid search", "performance marketing", "marketing analytics",
        )

    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, request: SearchRequest):
        if not self.configured():
            raise ProviderError(f"{self.name} search discovery requires BRAVE_SEARCH_API_KEY")
        query = f"{self.site_query} {request.query} {request.location}"
        url = "https://api.search.brave.com/res/v1/web/search?" + urlencode({
            "q": query, "count": min(request.results_per_page, 20),
            "offset": min(max(request.page - 1, 0), 9), "country": "US",
            "search_lang": "en", **({'freshness': {1:'pd',7:'pw',30:'pm'}[request.days]}
                                      if request.days in {1,7,30} else {}),
        })
        payload = get_json(url, {"X-Subscription-Token": self.api_key})
        results = payload.get("web", {}).get("results", [])
        if not isinstance(results, list):
            raise ProviderError(f"Brave returned an unexpected {self.name} discovery payload")
        self.has_more = bool(payload.get('query', {}).get('more_results_available')) and request.page < 10
        self.search_results_returned = getattr(self, 'search_results_returned', 0) + len(results)
        for result in results:
            target = str(result.get("url") or "")
            if not target:
                continue
            host = (urlsplit(target).hostname or "").casefold().rstrip(".")
            if self.site_domain and host != self.site_domain and not host.endswith("." + self.site_domain):
                self.errors.append({"url": target, "error": "off-domain discovery result skipped"})
                continue
            try:
                document = self.document(target)
            except ProviderError as error:
                destination = self.exclusions if re.search(r"HTTP(?: Error)? (404|410)\b", str(error)) else self.errors
                destination.append({"url": target, "error": str(error)})
                continue
            yield from self.extract(document, target)

    def document(self, target):
        if target not in self._documents:
            try:
                self._documents[target] = (
                    self.firecrawl.document(target) if self.firecrawl.configured()
                    else get_document(target))
            except ProviderError as exc:
                self._documents[target] = exc
        result = self._documents[target]
        if isinstance(result, ProviderError):
            raise result
        return result

    def extract(self, document, target):
        page = document.body.decode("utf-8", errors="replace")
        yielded = False
        for block in SCRIPT_RE.findall(page):
            try:
                data = json.loads(html.unescape(block).strip())
            except json.JSONDecodeError:
                continue
            for item in _job_nodes(data):
                organization = item.get("hiringOrganization") or {}
                identifier = item.get("identifier") or {}
                source_id = _text(identifier) or _text(item.get("url")) or target
                location = _location(
                    item.get("jobLocation") or item.get("applicantLocationRequirements")
                )
                listing = RawListing(
                    source=self.name, source_job_id=source_id,
                    url=urljoin(document.final_url, item.get("url") or document.final_url),
                    title=_text(item.get("title")), company=_text(organization),
                    location=location, description=_text(item.get("description")),
                    employment_type=_text(item.get("employmentType")),
                    salary=_text(item.get("baseSalary")),
                    date_posted=_text(item.get("datePosted")),
                    remote_type="remote" if item.get("jobLocationType") == "TELECOMMUTE" else "",
                    metadata={**item, "_discovered_via": "brave",
                              "_retrieved_via": "firecrawl" if self.firecrawl.configured() else "direct"},
                )
                if self.name.casefold() == "indeed":
                    from .indeed import application_method_from_page
                    method = application_method_from_page(page)
                    if method:
                        listing.metadata["_indeed_application_method"] = method
                if listing.title and listing.company and listing.description:
                    yielded = True
                    yield listing
        if not yielded:
            self.errors.append({"url": target, "error": "no structured public JobPosting data"})
