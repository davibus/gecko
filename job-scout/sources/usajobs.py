"""USAJOBS official Search API provider."""

from __future__ import annotations

import os
from urllib.parse import urlencode

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_json


class UsaJobsProvider(JobSource):
    name = "usajobs"
    endpoint = "https://data.usajobs.gov/api/search"
    broad_queries = ("marketing", "communications")

    def __init__(self, api_key: str | None = None, email: str | None = None):
        self.api_key = api_key or os.getenv("USAJOBS_API_KEY", "")
        self.email = email or os.getenv("USAJOBS_EMAIL", "")

    def configured(self) -> bool:
        return bool(self.api_key and self.email)

    def search(self, request: SearchRequest):
        if not self.configured():
            raise ProviderError("USAJOBS is not configured; set USAJOBS_API_KEY and USAJOBS_EMAIL")
        params = {
            "Keyword": request.query,
            "Page": request.page,
            "ResultsPerPage": min(request.results_per_page, 100),
            "DatePosted": 30,
            "WhoMayApply": "Public",
            "Fields": "Full",
        }
        location = request.location.casefold()
        if location and location != "remote":
            params["LocationName"] = request.location
        elif location == "remote":
            params["RemoteIndicator"] = "True"
        payload = get_json(self.endpoint + "?" + urlencode(params), {
            "Host": "data.usajobs.gov",
            "User-Agent": self.email,
            "Authorization-Key": self.api_key,
        })
        result = payload.get("SearchResult", {}) if isinstance(payload, dict) else {}
        items = result.get("SearchResultItems", [])
        if not isinstance(items, list):
            raise ProviderError("USAJOBS returned an unexpected search payload")
        for wrapper in items:
            item = wrapper.get("MatchedObjectDescriptor", {}) if isinstance(wrapper, dict) else {}
            details = item.get("UserArea", {}).get("Details", {})
            locations = item.get("PositionLocation", [])
            location_text = item.get("PositionLocationDisplay") or ", ".join(
                str(value.get("LocationName") or "") for value in locations if isinstance(value, dict)
            )
            remuneration = item.get("PositionRemuneration") or [{}]
            first_pay = remuneration[0] if isinstance(remuneration, list) and remuneration else {}
            low, high = first_pay.get("MinimumRange"), first_pay.get("MaximumRange")
            salary = " - ".join(f"${float(value):,.0f}" for value in (low, high) if value not in (None, ""))
            description = " ".join(str(details.get(key) or "") for key in (
                "JobSummary", "MajorDuties", "Education", "Requirements", "Evaluations",
            ))
            yield RawListing(
                source=self.name,
                source_job_id=str(item.get("PositionID") or wrapper.get("MatchedObjectId") or ""),
                url=str(item.get("PositionURI") or ""),
                title=str(item.get("PositionTitle") or ""),
                company=str(item.get("OrganizationName") or item.get("DepartmentName") or ""),
                location=str(location_text or ""), description=description,
                employment_type=", ".join(item.get("PositionSchedule", []) or []),
                salary=salary,
                date_posted=str(item.get("PublicationStartDate") or ""),
                remote_type="remote" if details.get("RemoteIndicator") else "",
                metadata=item,
            )
