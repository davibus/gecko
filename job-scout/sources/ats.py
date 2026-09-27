"""Configurable public job-board providers for supported ATS platforms."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, urlencode

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_json


def _text(value) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("label") or value.get("value") or ""
    return str(value or "")


def _salary(low, high, currency="", period="") -> str:
    amount = " - ".join(str(value) for value in (low, high) if value not in (None, ""))
    return " ".join(filter(None, (str(currency or "").upper(), amount,
                                  f"per {period}" if period else "")))


class ConfiguredAtsProvider(JobSource):
    companies: list[dict]

    def __init__(self, companies: list[dict] | None = None):
        self.companies = [item for item in (companies or []) if isinstance(item, dict)]
        self._cache: list[RawListing] | None = None
        self.board_errors: list[dict[str, str]] = []

    def configured(self) -> bool:
        return bool(self.companies)

    def full_feed(self):
        if not self.configured():
            raise ProviderError(f"{self.name} has no configured employers")
        if self._cache is None:
            self._cache = []
            workers = min(4, len(self.companies))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=self.name) as executor:
                futures = {executor.submit(self.fetch_company, company): company
                           for company in self.companies}
                for future in as_completed(futures):
                    company = futures[future]
                    try:
                        self._cache.extend(future.result())
                    except (ProviderError, ValueError, TypeError) as error:
                        self.board_errors.append({
                            "company": str(company.get("name") or company.get("token") or
                                           company.get("site") or company.get("slug") or "unknown"),
                            "error": str(error),
                        })
            if not self._cache and self.board_errors:
                raise ProviderError(
                    f"Every configured {self.name} employer failed: " +
                    "; ".join(f"{item['company']}: {item['error']}" for item in self.board_errors)
                )
        yield from self._cache

    def search(self, request: SearchRequest):
        yield from self.full_feed()

    def fetch_company(self, company: dict) -> list[RawListing]:
        raise NotImplementedError


class GreenhouseProvider(ConfiguredAtsProvider):
    name = "greenhouse"

    def fetch_company(self, company: dict) -> list[RawListing]:
        token = str(company.get("token") or "").strip()
        if not token:
            raise ValueError("missing board token")
        payload = get_json(
            f"https://boards-api.greenhouse.io/v1/boards/{quote(token)}/jobs?content=true"
        )
        items = payload.get("jobs", []) if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ProviderError("Greenhouse returned an unexpected jobs payload")
        result = []
        for item in items:
            location = _text(item.get("location"))
            result.append(RawListing(
                source=self.name, source_job_id=str(item.get("id") or ""),
                url=str(item.get("absolute_url") or ""), title=str(item.get("title") or ""),
                company=str(company.get("name") or token), location=location,
                description=str(item.get("content") or ""),
                employment_type=_text(item.get("employment_type")),
                date_posted=str(item.get("updated_at") or ""),
                remote_type="remote" if "remote" in location.casefold() else "",
                metadata={**item, "ats_company": token},
            ))
        return result


class LeverProvider(ConfiguredAtsProvider):
    name = "lever"

    def fetch_company(self, company: dict) -> list[RawListing]:
        site = str(company.get("site") or company.get("token") or "").strip()
        if not site:
            raise ValueError("missing site")
        region = "api.eu.lever.co" if company.get("region") == "eu" else "api.lever.co"
        payload = get_json(f"https://{region}/v0/postings/{quote(site)}?mode=json&limit=200")
        if not isinstance(payload, list):
            raise ProviderError("Lever returned an unexpected postings payload")
        result = []
        for item in payload:
            categories = item.get("categories") or {}
            location = _text(categories.get("location"))
            lists = item.get("lists") or []
            description = " ".join(filter(None, (
                str(item.get("descriptionPlain") or item.get("description") or ""),
                " ".join(_text(entry.get("content")) for entry in lists if isinstance(entry, dict)),
                str(item.get("additionalPlain") or item.get("additional") or ""),
            )))
            result.append(RawListing(
                source=self.name, source_job_id=str(item.get("id") or ""),
                url=str(item.get("hostedUrl") or item.get("applyUrl") or ""),
                title=str(item.get("text") or ""), company=str(company.get("name") or site),
                location=location, description=description,
                employment_type=_text(categories.get("commitment")),
                remote_type=str(item.get("workplaceType") or ""),
                category=_text(categories.get("team") or categories.get("department")),
                metadata={**item, "ats_company": site},
            ))
        return result


class AshbyProvider(ConfiguredAtsProvider):
    name = "ashby"

    def fetch_company(self, company: dict) -> list[RawListing]:
        board = str(company.get("board") or company.get("slug") or "").strip()
        if not board:
            raise ValueError("missing board slug")
        url = (f"https://api.ashbyhq.com/posting-api/job-board/{quote(board)}?" +
               urlencode({"includeCompensation": "true"}))
        payload = get_json(url)
        items = payload.get("jobs", []) if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ProviderError("Ashby returned an unexpected jobs payload")
        result = []
        for item in items:
            location = _text(item.get("location"))
            compensation = item.get("compensation") or {}
            result.append(RawListing(
                source=self.name,
                source_job_id=str(item.get("id") or item.get("jobPostingId") or ""),
                url=str(item.get("jobUrl") or item.get("applyUrl") or ""),
                title=str(item.get("title") or ""), company=str(company.get("name") or board),
                location=location,
                description=str(item.get("descriptionHtml") or item.get("descriptionPlain") or ""),
                employment_type=_text(item.get("employmentType")),
                salary=_text(compensation.get("compensationTierSummary") or
                             item.get("compensationTierSummary")),
                date_posted=str(item.get("publishedAt") or ""),
                remote_type="remote" if item.get("isRemote") else "",
                category=_text(item.get("department") or item.get("team")),
                metadata={**item, "ats_company": board},
            ))
        return result


class WorkableProvider(ConfiguredAtsProvider):
    name = "workable"

    def fetch_company(self, company: dict) -> list[RawListing]:
        account = str(company.get("account") or company.get("subdomain") or "").strip()
        if not account:
            raise ValueError("missing account subdomain")
        payload = get_json(f"https://www.workable.com/api/accounts/{quote(account)}?details=true")
        items = payload.get("jobs", []) if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ProviderError("Workable returned an unexpected jobs payload")
        result = []
        for item in items:
            location = item.get("location") or {}
            location_text = _text(location.get("location_str") if isinstance(location, dict) else location)
            salary = item.get("salary") or {}
            result.append(RawListing(
                source=self.name,
                source_job_id=str(item.get("shortcode") or item.get("id") or ""),
                url=str(item.get("url") or item.get("shortlink") or item.get("application_url") or ""),
                title=str(item.get("title") or ""), company=str(company.get("name") or account),
                location=location_text, description=str(item.get("description") or ""),
                employment_type=_text(item.get("employment_type")),
                salary=_salary(salary.get("salary_from"), salary.get("salary_to"),
                               salary.get("salary_currency")) if isinstance(salary, dict) else "",
                date_posted=str(item.get("created_at") or ""),
                remote_type=_text(location.get("workplace_type")) if isinstance(location, dict) else "",
                category=_text(item.get("department")),
                metadata={**item, "ats_company": account},
            ))
        return result
