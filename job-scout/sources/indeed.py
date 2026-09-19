"""Adapter for an authorized Indeed integration; it never scrapes Indeed pages."""

from __future__ import annotations

import os
from urllib.parse import urlencode

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_json


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
