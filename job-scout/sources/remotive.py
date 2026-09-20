"""Remotive's official, keyless public Jobs API adapter."""

from __future__ import annotations

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_json


class RemotiveProvider(JobSource):
    """Read Remotive's public feed once and filter it for Scout requests.

    Remotive asks API users to make only a few requests per day. A provider
    instance therefore caches the complete active-job feed for the duration of
    a Scout run, even when the run contains several role/location requests.
    """

    name = "remotive"
    endpoint = "https://remotive.com/api/remote-jobs"

    def __init__(self):
        self._jobs: list[dict] | None = None

    @property
    def raw_count(self) -> int:
        """Number of records in the cached API feed, after payload validation."""
        return len(self._jobs or [])

    def configured(self) -> bool:
        # The official public endpoint does not require authentication.
        return True

    def _load_jobs(self) -> list[dict]:
        if self._jobs is None:
            response = get_json(self.endpoint)
            if not isinstance(response, dict):
                raise ProviderError("Remotive API returned an unexpected response payload")
            jobs = response.get("jobs", [])
            if not isinstance(jobs, list):
                raise ProviderError("Remotive API returned an unexpected jobs payload")
            self._jobs = [item for item in jobs if isinstance(item, dict)]
        return self._jobs

    @staticmethod
    def _to_raw_listing(item: dict) -> RawListing:
        tags = item.get("tags") or []
        if not isinstance(tags, list):
            tags = [tags]
        # The public feed is remote-only. candidate_required_location is a
        # geographic eligibility restriction, not an office location.
        return RawListing(
            source="remotive",
            source_job_id=str(item.get("id") or "").strip(),
            url=str(item.get("url") or "").strip(),
            title=str(item.get("title") or "").strip(),
            company=str(item.get("company_name") or "").strip(),
            location=str(item.get("candidate_required_location") or "Remote").strip(),
            description=str(item.get("description") or "").strip(),
            employment_type=str(item.get("job_type") or "").strip(),
            salary=str(item.get("salary") or "").strip(),
            # Never substitute retrieval time: this is Remotive's actual
            # publication timestamp (the public feed itself is delayed).
            date_posted=str(item.get("publication_date") or "").strip(),
            remote_type="remote",
            category=str(item.get("category") or "").strip(),
            tags=[str(tag).strip() for tag in tags if str(tag).strip()],
            metadata=item,
        )

    def full_feed(self):
        """Yield every current feed job once, without title-query filtering."""
        for item in self._load_jobs():
            yield self._to_raw_listing(item)

    @staticmethod
    def _matches(item: dict, query: str) -> bool:
        terms = query.casefold().split()
        if not terms:
            return True
        searchable = " ".join((
            str(item.get("title") or ""),
            str(item.get("description") or ""),
            str(item.get("category") or ""),
            " ".join(str(tag) for tag in (item.get("tags") or [])),
        )).casefold()
        return all(term in searchable for term in terms)

    def search(self, request: SearchRequest):
        matches = [item for item in self._load_jobs() if self._matches(item, request.query)]
        start = max(request.page - 1, 0) * request.results_per_page
        stop = start + request.results_per_page
        for item in matches[start:stop]:
            yield self._to_raw_listing(item)
