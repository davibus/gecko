"""Shared permanent-rejection identity rules for every Gecko scout workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit

from normalize import canonicalize_url
from sources.indeed import canonical_indeed_url, extract_indeed_job_key


REJECTED_TAB = "Rejected Jobs"
REJECTED_HEADERS = (
    "Source",
    "Job ID",
    "Original Job URL",
    "Normalized Job URL",
    "Company",
    "Job Title",
    "Date Rejected",
    "Reason or Status",
)
REJECT_STATUSES = frozenset({"reject", "delete / reject", "delete/reject"})


class PermanentlyRejectedError(RuntimeError):
    """Raised at a final write boundary when a job entered rejection history."""


def normalize_source(value: object, url: object = "") -> str:
    source = " ".join(str(value or "").split()).casefold()
    if source:
        return source
    try:
        host = (urlsplit(str(url or "").strip()).hostname or "").casefold()
    except ValueError:
        host = ""
    return "indeed" if host == "indeed.com" or host.endswith(".indeed.com") else ""


def normalize_job_id(source: object, job_id: object, url: object = "") -> str:
    source_key = normalize_source(source, url)
    if source_key == "indeed":
        indeed_key = extract_indeed_job_key(str(url or ""))
        if indeed_key:
            return indeed_key.casefold()
    return " ".join(str(job_id or "").split()).casefold()


def normalize_job_url(url: object) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    return canonical_indeed_url(value) or canonicalize_url(value)


@dataclass(frozen=True)
class RejectedJob:
    source: str = ""
    job_id: str = ""
    original_url: str = ""
    normalized_url: str = ""
    company: str = ""
    title: str = ""
    date_rejected: str = ""
    reason: str = ""

    @classmethod
    def from_mapping(cls, values: dict[str, object]) -> "RejectedJob":
        original_url = str(values.get("Original Job URL") or "").strip()
        normalized_url = (
            str(values.get("Normalized Job URL") or "").strip()
            or normalize_job_url(original_url)
        )
        source = normalize_source(values.get("Source"), original_url or normalized_url)
        return cls(
            source=source,
            job_id=normalize_job_id(source, values.get("Job ID"), original_url),
            original_url=original_url,
            normalized_url=normalized_url,
            company=str(values.get("Company") or "").strip(),
            title=str(values.get("Job Title") or "").strip(),
            date_rejected=str(values.get("Date Rejected") or "").strip(),
            reason=str(values.get("Reason or Status") or "").strip(),
        )

    def as_mapping(self) -> dict[str, str]:
        return {
            "Source": self.source,
            "Job ID": self.job_id,
            "Original Job URL": self.original_url,
            "Normalized Job URL": self.normalized_url,
            "Company": self.company,
            "Job Title": self.title,
            "Date Rejected": self.date_rejected,
            "Reason or Status": self.reason,
        }


class RejectedJobsIndex:
    """Source-qualified stable IDs first, then canonical URLs; never title/company."""

    def __init__(self, records: Iterable[RejectedJob] = ()):
        self.records = tuple(records)
        self.provider_ids = {
            (record.source, record.job_id)
            for record in self.records if record.source and record.job_id
        }
        self.urls = {
            normalize_job_url(record.normalized_url or record.original_url)
            for record in self.records if record.normalized_url or record.original_url
        }
        self.urls.discard("")

    def match(
        self,
        *,
        source: object = "",
        job_id: object = "",
        url: object = "",
        urls: Iterable[object] = (),
    ) -> RejectedJob | None:
        all_urls = [url, *urls]
        source_key = normalize_source(source, next((value for value in all_urls if value), ""))
        candidate_id = normalize_job_id(source_key, job_id, next((value for value in all_urls if value), ""))
        if source_key and candidate_id:
            if (source_key, candidate_id) in self.provider_ids:
                return next(
                    record for record in self.records
                    if (record.source, record.job_id) == (source_key, candidate_id)
                )
        for candidate_url in all_urls:
            normalized = normalize_job_url(candidate_url)
            if normalized and normalized in self.urls:
                match = next((
                    record for record in self.records
                    if normalize_job_url(record.normalized_url or record.original_url) == normalized
                    and (not candidate_id or not record.job_id)
                ), None)
                if match is not None:
                    return match
        return None

    def matches_job(self, job) -> RejectedJob | None:
        return self.match(
            source=getattr(job, "source", ""),
            job_id=getattr(job, "source_job_id", ""),
            url=getattr(job, "url", ""),
            urls=(
                getattr(job, "canonical_url", ""),
                getattr(job, "authoritative_url", ""),
                *(link.get("url", "") for link in getattr(job, "source_links", ()) or ()),
            ),
        )


def rejection_record(
    *,
    source: object,
    job_id: object,
    url: object,
    company: object,
    title: object,
    date_rejected: object,
    reason: object,
) -> RejectedJob:
    original_url = str(url or "").strip()
    source_key = normalize_source(source, original_url)
    return RejectedJob(
        source=source_key,
        job_id=normalize_job_id(source_key, job_id, original_url),
        original_url=original_url,
        normalized_url=normalize_job_url(original_url),
        company=str(company or "").strip(),
        title=str(title or "").strip(),
        date_rejected=str(date_rejected or "").strip(),
        reason=str(reason or "").strip(),
    )
