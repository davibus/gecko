"""USAJOBS official Search API provider."""

from __future__ import annotations

import os
from urllib.parse import urlencode

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_json


DISPLAY_FIELDS = ("Name", "Description", "DisplayName", "Label", "Value", "Code")


def _display_text(value, fields: tuple[str, ...] = DISPLAY_FIELDS) -> str:
    """Extract human-readable text from a USAJOBS scalar or coded object."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for field in fields:
            text = _display_text(value.get(field), ())
            if text:
                return text
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _display_list(value, fields: tuple[str, ...] = DISPLAY_FIELDS) -> str:
    """Join string/object USAJOBS list fields while ignoring null entries."""
    values = value if isinstance(value, (list, tuple)) else [value]
    return ", ".join(filter(None, (_display_text(entry, fields) for entry in values)))


def _mapping_entries(value) -> list[dict]:
    """Return only mapping entries from an object or mixed USAJOBS list field."""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return [entry for entry in value if isinstance(entry, dict)]
    return []


def _money(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"${float(str(value).replace(',', '').replace('$', '')):,.0f}"
    except (TypeError, ValueError):
        return str(value).strip()


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
            item = item if isinstance(item, dict) else {}
            user_area = item.get("UserArea") if isinstance(item.get("UserArea"), dict) else {}
            details = user_area.get("Details") if isinstance(user_area.get("Details"), dict) else {}
            locations = _mapping_entries(item.get("PositionLocation"))
            location_text = item.get("PositionLocationDisplay") or ", ".join(
                filter(None, (_display_text(value, ("LocationName", "CityName", "Name", "Code"))
                              for value in locations))
            )
            remuneration = _mapping_entries(item.get("PositionRemuneration"))
            first_pay = remuneration[0] if remuneration else {}
            low, high = first_pay.get("MinimumRange"), first_pay.get("MaximumRange")
            salary = " - ".join(filter(None, (_money(value) for value in (low, high))))
            description_parts = [_display_list(details.get(key)) for key in (
                "JobSummary", "MajorDuties", "Education", "Requirements", "Evaluations",
            )]
            description_parts.append(_display_list(
                item.get("QualificationSummary") or details.get("QualificationSummary")
            ))
            description = " ".join(filter(None, description_parts))
            employment_type = _display_list(item.get("PositionSchedule"))
            if not employment_type:
                employment_type = _display_list(item.get("PositionOfferingType"))
            yield RawListing(
                source=self.name,
                source_job_id=str(item.get("PositionID") or wrapper.get("MatchedObjectId") or ""),
                url=str(item.get("PositionURI") or ""),
                title=str(item.get("PositionTitle") or ""),
                company=str(item.get("OrganizationName") or item.get("DepartmentName") or ""),
                location=str(location_text or ""), description=description,
                employment_type=employment_type,
                salary=salary,
                date_posted=str(item.get("PublicationStartDate") or ""),
                remote_type="remote" if details.get("RemoteIndicator") else "",
                metadata=item,
            )
