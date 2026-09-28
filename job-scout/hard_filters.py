"""Configurable deterministic gates that run before deduplication and AI."""

from __future__ import annotations

import re

from role_filter import role_filter_reason


def _text(value: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _annual_salary_values(value: str) -> list[int]:
    text = str(value or "").casefold().replace(",", "")
    amounts = []
    for raw, suffix in re.findall(r"\$?\s*(\d+(?:\.\d+)?)\s*(k)?", text):
        number = float(raw) * (1000 if suffix else 1)
        if "hour" in text or "/hr" in text:
            number *= 2080
        if number >= 10_000:
            amounts.append(int(number))
    return amounts


def deterministic_filter(job, preferences: dict) -> tuple[bool, str]:
    """Apply only explicit, high-confidence hard filters."""
    filters = preferences.get("deterministic_filters", {})
    relevant, reason = role_filter_reason(job.title)
    if not relevant:
        return False, reason

    title = _text(job.title)
    excluded_titles = filters.get("excluded_title_terms", preferences.get("excluded_seniority", []))
    if any(_text(term) in title for term in excluded_titles if _text(term)):
        return False, "excluded title/seniority"

    employment = _text(job.employment_type)
    allowed_types = [_text(item) for item in filters.get(
        "allowed_employment_types", preferences.get("preferred_employment_types", [])
    ) if _text(item)]
    if employment and allowed_types and not any(item in employment for item in allowed_types):
        return False, "excluded employment type"

    arrangement = _text(job.work_arrangement)
    allowed_arrangements = {_text(item) for item in filters.get(
        "allowed_work_arrangements", ["remote", "hybrid", "on-site", "unknown"]
    )}
    if arrangement and arrangement not in allowed_arrangements:
        return False, "excluded work arrangement"

    location = _text(job.location)
    preferred = [_text(item) for item in preferences.get("preferred_locations", []) if _text(item)]
    require_preferred = bool(filters.get("require_preferred_location_for_non_remote", True))
    if require_preferred and arrangement != "remote" and location and preferred:
        if not any(place in location for place in preferred):
            return False, "non-remote role outside preferred locations"

    minimum = int(filters.get("minimum_annual_salary", 0) or 0)
    salaries = _annual_salary_values(job.salary)
    if minimum and salaries and max(salaries) < minimum:
        return False, "compensation below configured minimum"

    excluded_categories = {_text(item) for item in filters.get("excluded_categories", [])}
    if _text(job.category) in excluded_categories:
        return False, "excluded category"
    return True, "passed deterministic filters"
