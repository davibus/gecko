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
    """Uses Brave Search (or legacy Google CSE), then reads schema.org JobPosting data."""

    name = "web-careers"

    def __init__(self):
        self.google_key = os.getenv("GOOGLE_CSE_API_KEY", "")
        self.google_cx = os.getenv("GOOGLE_CSE_ID", "")
        self.brave_key = os.getenv("BRAVE_SEARCH_API_KEY", "")

    def configured(self) -> bool:
        return bool(self.brave_key or (self.google_key and self.google_cx))

    def _result_urls(self, request: SearchRequest) -> list[str]:
        query = f'{request.query} jobs (site:jobs.lever.co OR site:boards.greenhouse.io OR inurl:careers)'
        if request.location:
            query += f" {request.location}"
        if self.brave_key:
            url = "https://api.search.brave.com/res/v1/web/search?" + urlencode({
                "q": query, "count": min(request.results_per_page, 20),
                "offset": min(max(request.page - 1, 0), 9), "country": "US", "search_lang": "en",
            })
            payload = get_json(url, {"X-Subscription-Token": self.brave_key})
            return [item.get("url", "") for item in payload.get("web", {}).get("results", [])]
        if self.google_key and self.google_cx:
            url = "https://customsearch.googleapis.com/customsearch/v1?" + urlencode({
                "key": self.google_key, "cx": self.google_cx, "q": query,
                "num": min(request.results_per_page, 10), "start": (request.page - 1) * 10 + 1,
            })
            return [item.get("link", "") for item in get_json(url).get("items", [])]
        raise ProviderError(
            "Web discovery is not configured; set BRAVE_SEARCH_API_KEY or legacy GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID"
        )

    def search(self, request: SearchRequest):
        for url in self._result_urls(request):
            if not url:
                continue
            try:
                page = get_bytes(url).decode("utf-8", errors="replace")
            except ProviderError:
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
                    yield RawListing(
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
                        metadata=item,
                    )
