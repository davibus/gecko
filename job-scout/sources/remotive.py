"""Remotive official category RSS aggregation with public API fallback."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_bytes, get_json


class RemotiveProvider(JobSource):
    """Aggregate official category feeds once each; use the API only if all fail."""

    name = "remotive"
    feed_base = "https://remotive.com/remote-jobs/feed"
    api_endpoint = "https://remotive.com/api/remote-jobs"
    endpoint = feed_base
    category_feeds = (
        ("Software Development", f"{feed_base}/software-development"),
        ("Customer Service", f"{feed_base}/customer-service"),
        ("Design", f"{feed_base}/design"),
        ("Marketing", f"{feed_base}/marketing"),
        ("Sales", f"{feed_base}/sales"),
        ("Product Management", f"{feed_base}/product"),
        ("Project Management", f"{feed_base}/project-management"),
        ("Artificial Intelligence", f"{feed_base}/artificial-intelligence"),
        ("Data and Analytics", f"{feed_base}/data"),
        ("Devops", f"{feed_base}/devops"),
        ("Finance", f"{feed_base}/finance"),
        ("Human Resources", f"{feed_base}/human-resources"),
        ("Quality Assurance", f"{feed_base}/qa"),
        ("Writing", f"{feed_base}/writing"),
        ("Legal", f"{feed_base}/legal"),
        ("Medical", f"{feed_base}/medical"),
        ("Teaching", f"{feed_base}/education"),
        ("Account Management", f"{feed_base}/account-management"),
        ("Business Development", f"{feed_base}/business-development"),
        ("Communications", f"{feed_base}/communications"),
        ("Compliance", f"{feed_base}/compliance"),
        ("Engineering", f"{feed_base}/engineering"),
        ("Information Technology", f"{feed_base}/information-technology"),
        ("Knowledge Management", f"{feed_base}/knowledge-management"),
        ("Operations", f"{feed_base}/operations"),
        ("Research", f"{feed_base}/research"),
        ("Strategy", f"{feed_base}/strategy"),
        ("Supply Chain", f"{feed_base}/supply-chain"),
        ("Travel and Hospitality", f"{feed_base}/travel-hospitality"),
        # Remotive does not publish an E-Commerce category; Marketing is the
        # closest official feed. All Others adds broad adjacent coverage.
        ("All Others", f"{feed_base}/all-others"),
    )

    def __init__(self):
        self._feed_cache: dict[str, list[RawListing]] = {}
        self._feed_errors: dict[str, ProviderError] = {}
        self._feed_results: list[dict] = []
        self._rss_pool: list[RawListing] | None = None
        self._rss_raw_count = 0
        self._rss_duplicate_count = 0
        self._api_jobs: list[dict] | None = None
        self.active_source = ""

    @property
    def rss_count(self) -> int:
        """Unique category-feed jobs after within-Remotive deduplication."""
        return len(self._rss_pool or [])

    @property
    def rss_raw_count(self) -> int:
        return self._rss_raw_count

    @property
    def rss_duplicate_count(self) -> int:
        return self._rss_duplicate_count

    @property
    def successful_feed_count(self) -> int:
        return sum(bool(result["success"]) for result in self._feed_results)

    @property
    def failed_feed_count(self) -> int:
        return sum(not result["success"] for result in self._feed_results)

    @property
    def feed_results(self) -> list[dict]:
        return [dict(result) for result in self._feed_results]

    @property
    def api_count(self) -> int:
        return len(self._api_jobs or [])

    @property
    def raw_count(self) -> int:
        return self.rss_raw_count if self.active_source == "category-rss" else self.api_count

    @property
    def rss_error(self) -> str:
        failures = [
            f'{result["category"]}: {result["error"]}'
            for result in self._feed_results if not result["success"]
        ]
        return "; ".join(failures)

    def configured(self) -> bool:
        return True

    @staticmethod
    def _text(item: ET.Element, *names: str) -> str:
        wanted = {name.casefold() for name in names}
        for child in item:
            if child.tag.rsplit("}", 1)[-1].casefold() in wanted:
                return "".join(child.itertext()).strip()
        return ""

    @classmethod
    def _source_id(cls, item: ET.Element, url: str) -> str:
        explicit = cls._text(item, "jobId", "job-id", "id")
        if explicit:
            return explicit
        guid = cls._text(item, "guid")
        numeric = re.search(r"-(\d+)(?:/)?$", guid or url)
        if numeric:
            return numeric.group(1)
        identity = guid or url or "|".join((
            cls._text(item, "title"), cls._text(item, "company", "creator"),
            cls._text(item, "pubDate", "publication-date"),
        ))
        return "rss-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _canonical_url(url: str) -> str:
        parts = urlsplit((url or "").strip())
        query = [
            (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
        ]
        return urlunsplit((
            parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"),
            urlencode(query), "",
        ))

    @staticmethod
    def _publication_date(value: str) -> str:
        if not value:
            return ""
        try:
            return parsedate_to_datetime(value).isoformat()
        except (TypeError, ValueError, OverflowError):
            return value

    @classmethod
    def _rss_listing(cls, item: ET.Element, feed_category: str) -> RawListing:
        url = cls._text(item, "link") or cls._text(item, "guid")
        item_categories = [
            "".join(child.itertext()).strip()
            for child in item
            if child.tag.rsplit("}", 1)[-1].casefold() in {"category", "tag"}
            and "".join(child.itertext()).strip()
        ]
        categories = list(dict.fromkeys([feed_category, *item_categories]))
        return RawListing(
            source="remotive",
            source_job_id=cls._source_id(item, url),
            url=url,
            title=cls._text(item, "title"),
            company=cls._text(item, "company", "company-name", "creator"),
            location=cls._text(
                item, "location", "candidate-location-restriction",
                "candidate_required_location",
            ) or "Remote",
            description=cls._text(item, "description", "encoded"),
            employment_type=cls._text(item, "type", "job-type", "job_type"),
            salary=cls._text(item, "salary", "compensation"),
            date_posted=cls._publication_date(
                cls._text(item, "pubDate", "publication-date", "publication_date")
            ),
            remote_type="remote",
            category=item_categories[0] if item_categories else feed_category,
            tags=categories,
            metadata={"feed": "rss", "feed_categories": [feed_category]},
        )

    def _load_category_feed(self, category: str, url: str) -> list[RawListing]:
        if url in self._feed_errors:
            raise self._feed_errors[url]
        if url not in self._feed_cache:
            try:
                body = get_bytes(
                    url,
                    headers={"Accept": "application/rss+xml, application/xml, text/xml"},
                )
                root = ET.fromstring(body)
                items = [
                    element for element in root.iter()
                    if element.tag.rsplit("}", 1)[-1].casefold() in {"item", "job"}
                ]
                self._feed_cache[url] = [self._rss_listing(item, category) for item in items]
            except ET.ParseError as error:
                wrapped = ProviderError(f"Remotive RSS returned invalid XML: {error}")
                self._feed_errors[url] = wrapped
                raise wrapped from error
            except ProviderError as error:
                self._feed_errors[url] = error
                raise
        return self._feed_cache[url]

    @staticmethod
    def _merge_category_provenance(existing: RawListing, duplicate: RawListing) -> None:
        existing.tags = list(dict.fromkeys([*existing.tags, *duplicate.tags]))
        feed_categories = list(dict.fromkeys([
            *(existing.metadata.get("feed_categories") or []),
            *(duplicate.metadata.get("feed_categories") or []),
        ]))
        existing.metadata["feed_categories"] = feed_categories

    def category_pool(self) -> list[RawListing]:
        """Fetch every configured category once and return a deduplicated pool."""
        if self._rss_pool is not None:
            return list(self._rss_pool)
        self._feed_results = []
        raw_jobs: list[RawListing] = []
        for category, url in self.category_feeds:
            try:
                jobs = self._load_category_feed(category, url)
                raw_jobs.extend(jobs)
                self._feed_results.append({
                    "category": category, "url": url, "success": True,
                    "jobs": len(jobs), "error": "",
                })
            except ProviderError as error:
                self._feed_results.append({
                    "category": category, "url": url, "success": False,
                    "jobs": 0, "error": str(error),
                })

        by_id: dict[str, RawListing] = {}
        by_url: dict[str, RawListing] = {}
        unique: list[RawListing] = []
        for job in raw_jobs:
            duplicate = by_id.get(job.source_job_id) if job.source_job_id else None
            canonical_url = self._canonical_url(job.url)
            if duplicate is None and canonical_url:
                duplicate = by_url.get(canonical_url)
            if duplicate is not None:
                self._merge_category_provenance(duplicate, job)
                continue
            unique.append(job)
            if job.source_job_id:
                by_id[job.source_job_id] = job
            if canonical_url:
                by_url[canonical_url] = job
        self._rss_raw_count = len(raw_jobs)
        self._rss_duplicate_count = len(raw_jobs) - len(unique)
        self._rss_pool = unique
        return list(unique)

    def _load_api_jobs(self) -> list[dict]:
        if self._api_jobs is None:
            response = get_json(self.api_endpoint)
            if not isinstance(response, dict):
                raise ProviderError("Remotive API returned an unexpected response payload")
            jobs = response.get("jobs", [])
            if not isinstance(jobs, list):
                raise ProviderError("Remotive API returned an unexpected jobs payload")
            self._api_jobs = [item for item in jobs if isinstance(item, dict)]
        return self._api_jobs

    @staticmethod
    def _api_listing(item: dict) -> RawListing:
        tags = item.get("tags") or []
        if not isinstance(tags, list):
            tags = [tags]
        category = str(item.get("category") or "").strip()
        return RawListing(
            source="remotive", source_job_id=str(item.get("id") or "").strip(),
            url=str(item.get("url") or "").strip(), title=str(item.get("title") or "").strip(),
            company=str(item.get("company_name") or "").strip(),
            location=str(item.get("candidate_required_location") or "Remote").strip(),
            description=str(item.get("description") or "").strip(),
            employment_type=str(item.get("job_type") or "").strip(),
            salary=str(item.get("salary") or "").strip(),
            date_posted=str(item.get("publication_date") or "").strip(), remote_type="remote",
            category=category,
            tags=list(dict.fromkeys([category, *[str(tag).strip() for tag in tags if str(tag).strip()]]))
            if category else [str(tag).strip() for tag in tags if str(tag).strip()],
            metadata={**item, "feed_categories": [category] if category else []},
        )

    def api_feed(self):
        for item in self._load_api_jobs():
            yield self._api_listing(item)

    def full_feed(self):
        """Use aggregated category RSS unless every category request failed."""
        jobs = self.category_pool()
        if self.successful_feed_count:
            self.active_source = "category-rss"
        else:
            jobs = list(self.api_feed())
            self.active_source = "api-fallback"
        yield from jobs

    @staticmethod
    def _matches(item: dict, query: str) -> bool:
        terms = query.casefold().split()
        searchable = " ".join((
            str(item.get("title") or ""), str(item.get("description") or ""),
            str(item.get("category") or ""),
            " ".join(str(tag) for tag in (item.get("tags") or [])),
        )).casefold()
        return all(term in searchable for term in terms)

    def search(self, request: SearchRequest):
        """Retain the legacy query-based API adapter for diagnostics/compatibility."""
        matches = [item for item in self._load_api_jobs() if self._matches(item, request.query)]
        start = max(request.page - 1, 0) * request.results_per_page
        stop = start + request.results_per_page
        for item in matches[start:stop]:
            yield self._api_listing(item)
