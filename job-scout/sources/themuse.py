"""The Muse public Jobs API provider."""

from __future__ import annotations

import os
from urllib.parse import urlencode

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_json


class TheMuseProvider(JobSource):
    name = "themuse"
    endpoint = "https://www.themuse.com/api/public/jobs"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("THE_MUSE_API_KEY", "")
        self._pages = {}

    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, request: SearchRequest):
        if not self.configured():
            raise ProviderError("The Muse is not configured; set THE_MUSE_API_KEY")
        params = {"api_key": self.api_key, "page": request.page - 1, "descending": "true"}
        if request.location:
            params["location"] = request.location
        page_key = (request.location, request.page)
        if page_key not in self._pages:
            self._pages[page_key] = get_json(self.endpoint + "?" + urlencode(params))
        payload = self._pages[page_key]
        items = payload.get("results", []) if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ProviderError("The Muse returned an unexpected jobs payload")
        self.has_more = request.page < int(payload.get('page_count', request.page))
        words = {word.casefold() for word in request.query.split() if len(word) > 2}
        for item in items:
            title = str(item.get("name") or "")
            description = str(item.get("contents") or "")
            if words and not any(word in f"{title} {description}".casefold() for word in words):
                continue
            locations = item.get("locations") or []
            categories = item.get("categories") or []
            levels = item.get("levels") or []
            yield RawListing(
                source=self.name, source_job_id=str(item.get("id") or ""),
                url=str(item.get("refs", {}).get("landing_page") or ""),
                title=title, company=str(item.get("company", {}).get("name") or ""),
                location=", ".join(str(value.get("name") or "") for value in locations),
                description=description,
                employment_type=", ".join(str(value.get("name") or "") for value in levels),
                date_posted=str(item.get("publication_date") or ""),
                category=", ".join(str(value.get("name") or "") for value in categories),
                metadata=item,
            )
