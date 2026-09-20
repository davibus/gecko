"""Normalize provider-specific records into the common JobListing model."""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from models import JobListing, RawListing


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
TRACKING_PARAMS = {"from", "ref", "referrer", "source", "utm_campaign", "utm_content", "utm_medium", "utm_source"}


def clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = TAG_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if key.lower() not in TRACKING_PARAMS and not key.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def infer_work_arrangement(raw: RawListing) -> str:
    value = f"{raw.remote_type} {raw.location} {raw.title} {raw.description[:1500]}".lower()
    if "hybrid" in value:
        return "hybrid"
    if any(term in value for term in ("remote", "telecommute", "work from home")):
        return "remote"
    return "on-site" if raw.location else "unknown"


def normalize(raw: RawListing, discovered: str | None = None) -> JobListing:
    employment_type = clean_text(raw.employment_type).lower().replace("_", "-")
    discovered_date = discovered or JobListing.today()
    return JobListing(
        company=clean_text(raw.company) or "Unknown company",
        title=clean_text(raw.title),
        location=clean_text(raw.location),
        work_arrangement=infer_work_arrangement(raw),
        employment_type=employment_type,
        salary=clean_text(raw.salary),
        source=clean_text(raw.source),
        source_job_id=clean_text(raw.source_job_id),
        url=raw.url.strip(),
        date_posted=clean_text(raw.date_posted)[:10],
        date_discovered=discovered_date,
        description=clean_text(raw.description),
        canonical_url=canonicalize_url(raw.url),
        category=clean_text(raw.category),
        tags=[clean_text(tag) for tag in raw.tags if clean_text(tag)],
        last_seen=discovered_date,
        source_links=[{"source": clean_text(raw.source), "source_job_id": clean_text(raw.source_job_id), "url": raw.url.strip()}],
    )
