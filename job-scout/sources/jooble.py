"""Jooble's official Jobs API adapter."""

from __future__ import annotations

import hashlib
import os

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import post_json


class JoobleProvider(JobSource):
    name = "jooble"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("JOOBLE_API_KEY", "")

    def configured(self) -> bool:
        return bool(self.api_key.strip())

    def search(self, request: SearchRequest):
        if not self.configured():
            raise ProviderError("Jooble is not configured; set JOOBLE_API_KEY")
        # Jooble authenticates with a path token. Never include this URL in output or errors.
        url = f"https://jooble.org/api/{self.api_key}"
        payload = {
            "keywords": request.query,
            "location": request.location,
            "page": str(request.page),
            "ResultOnPage": str(request.results_per_page),
        }
        response = post_json(url, payload, error_label="Jooble API")
        jobs = response.get("jobs", [])
        if not isinstance(jobs, list):
            raise ProviderError("Jooble API returned an unexpected jobs payload")
        for item in jobs:
            if not isinstance(item, dict):
                continue
            link = str(item.get("link") or "").strip()
            source_id = str(item.get("id") or "").strip()
            if not source_id and link:
                source_id = hashlib.sha256(link.encode("utf-8")).hexdigest()[:24]
            yield RawListing(
                source="Jooble",
                source_job_id=source_id,
                url=link,
                title=str(item.get("title") or "").strip(),
                company=str(item.get("company") or "").strip(),
                location=str(item.get("location") or "").strip(),
                description=str(item.get("snippet") or item.get("description") or "").strip(),
                employment_type=str(item.get("type") or "").strip(),
                salary=str(item.get("salary") or "").strip(),
                date_posted=str(item.get("updated") or item.get("date") or "").strip(),
                metadata=item,
            )
