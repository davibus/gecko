"""Cross-board duplicate detection using identity and content evidence."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from models import JobListing


def _words(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", value.lower()) if len(word) > 2}


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, " ".join(sorted(_words(left))), " ".join(sorted(_words(right)))).ratio()


def description_similarity(left: str, right: str) -> float:
    a, b = _words(left), _words(right)
    return len(a & b) / len(a | b) if a and b else 0.0


def duplicate_confidence(left: JobListing, right: JobListing) -> float:
    if left.canonical_url and left.canonical_url == right.canonical_url:
        return 1.0
    company = _similarity(left.company, right.company)
    title = _similarity(left.title, right.title)
    location = _similarity(left.location, right.location) if left.location and right.location else 0.65
    description = description_similarity(left.description, right.description)
    # Company and title are required identity anchors; description resolves reposts.
    if company < 0.72 or title < 0.72:
        return 0.0
    return company * 0.25 + title * 0.35 + location * 0.10 + description * 0.30


def find_duplicate(candidate: JobListing, existing: list[JobListing], threshold: float = 0.76) -> JobListing | None:
    matches = ((duplicate_confidence(candidate, item), item) for item in existing)
    score, match = max(matches, default=(0.0, None), key=lambda pair: pair[0])
    return match if score >= threshold else None
