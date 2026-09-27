"""Jobicy public remote-jobs API provider."""

from __future__ import annotations

from urllib.parse import urlencode

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_json


class JobicyProvider(JobSource):
    name = "jobicy"
    endpoint = "https://jobicy.com/api/v2/remote-jobs"

    def __init__(self, limit: int = 200):
        self.limit = min(max(limit, 1), 200)
        self._cache: list[RawListing] | None = None

    def configured(self) -> bool:
        return True

    @staticmethod
    def _salary(item: dict) -> str:
        low, high = item.get("salaryMin"), item.get("salaryMax")
        amount = " - ".join(str(value) for value in (low, high) if value not in (None, ""))
        currency = str(item.get("salaryCurrency") or "").upper()
        period = str(item.get("salaryPeriod") or "")
        return " ".join(filter(None, (currency, amount, f"per {period}" if period else "")))

    def full_feed(self):
        if self._cache is None:
            url = self.endpoint + "?" + urlencode({
                "count": self.limit, "geo": "usa", "industry": "marketing",
            })
            payload = get_json(url)
            items = payload.get("jobs", []) if isinstance(payload, dict) else None
            if not isinstance(items, list):
                raise ProviderError("Jobicy returned an unexpected jobs payload")
            self._cache = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                types = item.get("jobType") or []
                industries = item.get("jobIndustry") or []
                self._cache.append(RawListing(
                    source=self.name,
                    source_job_id=str(item.get("id") or item.get("jobSlug") or ""),
                    url=str(item.get("url") or ""),
                    title=str(item.get("jobTitle") or ""),
                    company=str(item.get("companyName") or ""),
                    location=str(item.get("jobGeo") or "Remote"),
                    description=str(item.get("jobDescription") or item.get("jobExcerpt") or ""),
                    employment_type=", ".join(map(str, types)) if isinstance(types, list) else str(types),
                    salary=self._salary(item),
                    date_posted=str(item.get("pubDate") or ""),
                    remote_type="remote",
                    category=", ".join(map(str, industries)) if isinstance(industries, list) else str(industries),
                    tags=[str(value) for value in industries] if isinstance(industries, list) else [],
                    metadata=item,
                ))
        yield from self._cache

    def search(self, request: SearchRequest):
        words = {word.casefold() for word in request.query.split() if len(word) > 2}
        for job in self.full_feed():
            haystack = f"{job.title} {job.description}".casefold()
            if not words or any(word in haystack for word in words):
                yield job
