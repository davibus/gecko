"""Remote OK public JSON feed provider."""

from __future__ import annotations

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_json_value


class RemoteOkProvider(JobSource):
    name = "remoteok"
    endpoint = "https://remoteok.com/api"

    def __init__(self):
        self._cache: list[RawListing] | None = None

    def configured(self) -> bool:
        return True

    @staticmethod
    def _salary(item: dict) -> str:
        low, high = item.get("salary_min"), item.get("salary_max")
        return " - ".join(f"${value:,.0f}" for value in (low, high)
                          if isinstance(value, (int, float)) and value > 0)

    def full_feed(self):
        if self._cache is None:
            payload = get_json_value(self.endpoint, {"Accept": "application/json"})
            if not isinstance(payload, list):
                raise ProviderError("Remote OK returned an unexpected response payload")
            self._cache = []
            for item in payload:
                if not isinstance(item, dict) or not item.get("position"):
                    continue
                tags = item.get("tags") if isinstance(item.get("tags"), list) else []
                self._cache.append(RawListing(
                    source=self.name,
                    source_job_id=str(item.get("id") or item.get("slug") or ""),
                    url=str(item.get("url") or item.get("apply_url") or ""),
                    title=str(item.get("position") or ""),
                    company=str(item.get("company") or ""),
                    location=str(item.get("location") or "Remote"),
                    description=str(item.get("description") or ""),
                    employment_type=str(item.get("employment_type") or ""),
                    salary=self._salary(item),
                    date_posted=str(item.get("date") or item.get("epoch") or ""),
                    remote_type="remote", tags=[str(tag) for tag in tags], metadata=item,
                ))
        yield from self._cache

    def search(self, request: SearchRequest):
        yield from self.full_feed()
