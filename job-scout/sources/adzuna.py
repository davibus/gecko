"""Adzuna's supported Jobs API adapter."""

from __future__ import annotations

import os
from urllib.parse import urlencode

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_json


class AdzunaProvider(JobSource):
    name = "adzuna"

    def __init__(self, app_id: str | None = None, app_key: str | None = None, country: str = "us"):
        self.app_id = app_id or os.getenv("ADZUNA_APP_ID", "")
        self.app_key = app_key or os.getenv("ADZUNA_APP_KEY", "")
        self.country = country

    def configured(self) -> bool:
        return bool(self.app_id and self.app_key)

    def search(self, request: SearchRequest):
        if not self.configured():
            raise ProviderError("Adzuna is not configured; set ADZUNA_APP_ID and ADZUNA_APP_KEY")
        params = urlencode({
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": request.results_per_page,
            "what": (request.query + ' remote' if request.location.casefold() == 'remote'
                     else request.query),
            "where": '' if request.location.casefold() == 'remote' else request.location,
            "sort_by": "date",
            "content-type": "application/json",
        })
        if request.days is not None:
            params += '&' + urlencode({'max_days_old': request.days})
        url = f"https://api.adzuna.com/v1/api/jobs/{self.country}/search/{request.page}?{params}"
        payload = get_json(url)
        items = payload.get('results', [])
        self.has_more = bool(items) and (request.page * request.results_per_page <
            int(payload.get('count', request.page * request.results_per_page)))
        for item in items:
            salary_min, salary_max = item.get("salary_min"), item.get("salary_max")
            salary = ""
            if salary_min or salary_max:
                salary = " - ".join(f"${number:,.0f}" for number in (salary_min, salary_max) if number)
                if str(item.get('salary_is_predicted', '')).strip().lower() in {'1', 'true'}:
                    salary = 'Estimated ' + salary
            yield RawListing(
                source=self.name,
                source_job_id=str(item.get("id", "")),
                url=item.get("redirect_url", ""),
                title=item.get("title", ""),
                company=(item.get("company") or {}).get("display_name", ""),
                location=(item.get("location") or {}).get("display_name", ""),
                description=item.get("description", ""),
                employment_type=item.get("contract_time", "") or item.get("contract_type", ""),
                salary=salary,
                date_posted=item.get("created", ""),
                metadata=item,
            )
