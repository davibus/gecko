"""Cross-board duplicate detection using identity and content evidence."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from models import JobListing


def _words(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", value.lower()) if len(word) > 2}


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, " ".join(sorted(_words(left))), " ".join(sorted(_words(right)))).ratio()


def _identity(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").casefold()))


def description_similarity(left: str, right: str) -> float:
    a, b = _words(left), _words(right)
    return len(a & b) / len(a | b) if a and b else 0.0


def _provider_ids(job: JobListing) -> set[tuple[str, str]]:
    identities = set()
    if job.source and job.source_job_id:
        identities.add((_identity(job.source), _identity(job.source_job_id)))
    identities.update(
        (_identity(link.get("source", "")), _identity(link.get("source_job_id", "")))
        for link in job.source_links
        if link.get("source") and link.get("source_job_id")
    )
    return identities


def exact_duplicate(candidate: JobListing, existing: list[JobListing]) -> JobListing | None:
    """Use stable identities in descending order before fuzzy comparison."""
    provider_ids = _provider_ids(candidate)
    if provider_ids:
        match = next((job for job in existing if provider_ids & _provider_ids(job)), None)
        if match:
            return match
    if candidate.canonical_url:
        match = next((job for job in existing
                      if job.canonical_url and job.canonical_url == candidate.canonical_url), None)
        if match:
            return match
    identity = tuple(_identity(value) for value in (
        candidate.company, candidate.title, candidate.location
    ))
    if all(identity):
        match = next((job for job in existing if identity == tuple(_identity(value) for value in (
            job.company, job.title, job.location
        ))), None)
        if match:
            return match
    return None


def duplicate_confidence(left: JobListing, right: JobListing) -> float:
    if left.canonical_url and left.canonical_url == right.canonical_url:
        return 1.0
    exact_identity = (
        _identity(left.company), _identity(left.title), _identity(left.location)
    )
    if all(exact_identity) and exact_identity == (
        _identity(right.company), _identity(right.title), _identity(right.location)
    ):
        return .98 if left.date_posted and left.date_posted == right.date_posted else .88
    company = _similarity(left.company, right.company)
    title = _similarity(left.title, right.title)
    location = _similarity(left.location, right.location) if left.location and right.location else 0.65
    description = description_similarity(left.description, right.description)
    # Company and title are required identity anchors; description resolves reposts.
    if company < 0.72 or title < 0.72:
        return 0.0
    return company * 0.25 + title * 0.35 + location * 0.10 + description * 0.30


def find_duplicate(candidate: JobListing, existing: list[JobListing], threshold: float = 0.76) -> JobListing | None:
    exact = exact_duplicate(candidate, existing)
    if exact:
        return exact
    matches = ((duplicate_confidence(candidate, item), item) for item in existing)
    score, match = max(matches, default=(0.0, None), key=lambda pair: pair[0])
    return match if score >= threshold else None
