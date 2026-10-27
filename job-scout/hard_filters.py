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


def _starting_annual_base(value: str) -> float | None:
    """Read a posted USD annual lower bound; never annualize contract rates."""
    text = str(value or '').casefold().strip()
    if re.search(r'\b(?:estimated?|predicted|up to|at most|maximum|cad|aud|eur|gbp|hourly|hour|monthly|month|weekly|week|daily|day)\b|[/]\s*hr\b|[€£]|[ca]\$', text):
        return None
    if re.search(r'\b(?:ote|on.target|total compensation|total cash)\b', text) and not re.search(r'\bbase (?:salary|pay)\b', text):
        return None
    text = re.split(r'\b(?:bonus|commission|equity|ote|on.target|total compensation)\b', text)[0]
    matches = list(re.finditer(r'(?<![\w.])(\d+(?:,\d{3})*(?:\.\d+)?)\s*(k)?\b', text))
    values = [(float(m[1].replace(',', '')), bool(m[2])) for m in matches]
    shorthand = any(k for _, k in values)
    amounts = [n * 1000 if k or (shorthand and n < 1000) else n for n, k in values]
    annual = [n for n in amounts if n >= 10_000]
    return min(annual) if annual else None


def salary_exclusion_reason(job, preferences: dict) -> str:
    threshold = float(preferences.get('deterministic_filters', {}).get('maximum_starting_annual_base_salary', 0) or 0)
    if not threshold:
        return ''
    # An explicitly labeled base salary wins over provider OTE/total pay.
    description = max((str(job.description or ''), str(getattr(job, 'enriched_description', '') or '')), key=len)
    base = re.search(
        r'\b(?:annual\s+)?base\s+(?:salary|pay)(?:\s+range)?[^$\d\n.;]{0,100}'
        r'((?:USD\s*)?\$?\d[\d,.]*\s*[kK]?(?:\s*(?:-|–|—|to)\s*\$?\d[\d,.]*\s*[kK]?)?[^\n.;]{0,30})',
        description, re.I,
    )
    starting = _starting_annual_base(base[0] if base else job.salary)
    if starting is None:
        # ATS boards often put pay in a labeled description section rather than
        # a separate salary field. Reuse the shared parser, excluding non-base
        # qualifiers and annualization of hourly/monthly contract rates.
        from salary_format import _candidates
        candidates = []
        for candidate in _candidates(description, 'Job Description'):
            suffix = description.split(candidate.evidence, 1)[-1][:35]
            explicit_base_suffix = bool(re.match(r'\s*(?:USD\s*)?base\b', suffix, re.I))
            if (candidate.currency == 'USD' and candidate.period == 'year'
                    and (not candidate.qualifier or explicit_base_suffix
                         or candidate.qualifier == 'Posted lower bound only.')):
                candidates.append(candidate)
        if candidates:
            best = max(c.score for c in candidates)
            starting = float(min(c.low for c in candidates if c.score == best))
        else:
            offered = re.findall(
                r'range being offered for this role is\s*(\$[\d,]+\s*[kK]?(?:\s*[-–—]\s*\$?[\d,]+\s*[kK]?)?)',
                description, re.I)
            values = [value for text in offered if (value := _starting_annual_base(text)) is not None]
            if values: starting = min(values)
    if starting is not None and starting > threshold:
        return f'starting annual base salary above ${threshold:,.0f}'
    return ''


def deterministic_filter(job, preferences: dict) -> tuple[bool, str]:
    """Apply only explicit, high-confidence hard filters."""
    if preferences.get('_impromptu'):
        from impromptu_filters import matches
        if not matches(job, preferences['_impromptu'], preferences.get('_impromptu_known', {})):
            return False, 'outside impromptu selections'
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
    if arrangement == 'remote':
        us_or_worldwide = re.search(r'\b(?:united states|usa|us|canada|can|worldwide|anywhere|global)\b', location)
        foreign_only = re.search(
            r'\b(?:united kingdom|uk|denmark|new zealand|australia|european union|emea|philippines|germany|india|pakistan)\b|^(?:au|nz)\b',
            location + ' ' + _text(job.title),
        )
        if foreign_only and not us_or_worldwide:
            return False, 'remote role restricted outside United States'
    preferred = [_text(item) for item in preferences.get("preferred_locations", []) if _text(item)]
    require_preferred = bool(filters.get("require_preferred_location_for_non_remote", True))
    if require_preferred and arrangement != "remote" and location and preferred:
        if not any(place in location for place in preferred):
            return False, "non-remote role outside preferred locations"

    minimum = int(filters.get("minimum_annual_salary", 0) or 0)
    salaries = _annual_salary_values(job.salary)
    if minimum and salaries and max(salaries) < minimum:
        return False, "compensation below configured minimum"
    salary_reason = salary_exclusion_reason(job, preferences)
    if salary_reason:
        return False, salary_reason

    excluded_categories = {_text(item) for item in filters.get("excluded_categories", [])}
    if _text(job.category) in excluded_categories:
        return False, "excluded category"
    return True, "passed deterministic filters"
