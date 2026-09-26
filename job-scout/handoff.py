"""Archive a selected listing in the format Gecko's existing workflow consumes."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from models import JobListing
from url_resolution import best_job_url, url_status_label


INVALID_FILENAME = re.compile(r'[\\/:*?"<>|]')


def safe_name(value: str) -> str:
    return re.sub(r"-+", "-", INVALID_FILENAME.sub("", value).strip().replace(" ", "-")) or "Unknown-Company"


def job_number(job: JobListing) -> str:
    if job.source_job_id:
        if job.source_job_id.startswith(("https://", "http://")):
            from urllib.parse import urlsplit
            path_id = urlsplit(job.source_job_id).path.rstrip("/").rsplit("/", 1)[-1]
            if path_id:
                return safe_name(path_id)
        return safe_name(job.source_job_id)
    return hashlib.sha256((job.canonical_url or job.title + job.company).encode()).hexdigest()[:16]


def archive_listing(job: JobListing, project_root: Path) -> Path:
    company = safe_name(job.company)
    number = job_number(job)
    destination = project_root / "input" / "job-descriptions" / f"{company}+{number}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    links = "\n".join(f"- {item['source']}: {item['url']}" for item in job.source_links)
    best_url = best_job_url(job)
    full_description = job.enriched_description or job.description
    content = f"""# {job.title} — {job.company}

- **Scout ID:** {job.id or ''}
- **Job Number:** `{number}`
- **Company:** {job.company}
- **Job Title:** {job.title}
- **Location:** {job.location}
- **Work Arrangement:** {job.work_arrangement}
- **Job Type:** {job.employment_type}
- **Salary:** {job.salary}
- **Source:** {job.source}
- **URL:** {best_url}
- **URL Status:** {url_status_label(job)}
- **Authoritative URL:** {job.authoritative_url}
- **Date Posted:** {job.date_posted}
- **Date Discovered:** {job.date_discovered}

## Source links

{links}

## Full job description

{full_description}
"""
    destination.write_text(content, encoding="utf-8")
    (project_root / "scratch" / f"{company}+{number}").mkdir(parents=True, exist_ok=True)
    return destination
