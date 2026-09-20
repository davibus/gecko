"""Shared data contracts for Gecko Job Scout."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


VALID_STATUSES = {
    "new", "reviewing", "selected", "resume-created", "applied", "contacted",
    "interview", "rejected", "offer", "ignored",
}


@dataclass
class RawListing:
    source: str
    source_job_id: str
    url: str
    title: str
    company: str
    location: str = ""
    description: str = ""
    employment_type: str = ""
    salary: str = ""
    date_posted: str = ""
    remote_type: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobListing:
    company: str
    title: str
    location: str
    work_arrangement: str
    employment_type: str
    salary: str
    source: str
    source_job_id: str
    url: str
    date_posted: str
    date_discovered: str
    description: str
    canonical_url: str
    category: str = ""
    tags: list[str] = field(default_factory=list)
    last_seen: str = ""
    match_score: int = 0
    evidence_confidence: int = 0
    provisional: bool = False
    evidence_levels: dict[str, str] = field(default_factory=dict)
    original_description: str = ""
    original_match_score: int = 0
    original_evidence_confidence: int = 0
    original_url: str = ""
    enriched_description: str = ""
    enriched_source_url: str = ""
    enriched_at: str = ""
    enrichment_status: str = "not_attempted"
    enrichment_error: str = ""
    enriched_match_score: int = 0
    enriched_evidence_confidence: int = 0
    url_verification_status: str = "not_attempted"
    authoritative_url: str = ""
    authoritative_url_confidence: int = 0
    url_destination_type: str = "unknown"
    url_redirect_url: str = ""
    url_resolved_at: str = ""
    url_resolution_error: str = ""
    match_strengths: list[str] = field(default_factory=list)
    match_weaknesses: list[str] = field(default_factory=list)
    status: str = "new"
    source_links: list[dict[str, str]] = field(default_factory=list)
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "JobListing":
        fields = cls.__dataclass_fields__
        return cls(**{key: item for key, item in value.items() if key in fields})

    @staticmethod
    def today() -> str:
        return date.today().isoformat()
