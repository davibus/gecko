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
        return safe_name(job.source_job_id)
    return hashlib.sha256((job.canonical_url or job.title + job.company).encode()).hexdigest()[:16]


def archive_listing(job: JobListing, project_root: Path) -> Path:
    company = safe_name(job.company)
    number = job_number(job)
    destination = project_root / "input" / "job-descriptions" / f"{company}+{number}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    links = "\n".join(f"- {item['source']}: {item['url']}" for item in job.source_links)
    strengths = "\n".join(f"- {value}" for value in job.match_strengths) or "- None recorded"
    weaknesses = "\n".join(f"- {value}" for value in job.match_weaknesses) or "- None recorded"
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
- **Gecko Match Score:** {job.match_score}/100

## Source links

{links}

## Scout strengths

{strengths}

## Scout weaknesses

{weaknesses}

## Full job description

{full_description}
"""
    destination.write_text(content, encoding="utf-8")
    (project_root / "scratch" / f"{company}+{number}").mkdir(parents=True, exist_ok=True)
    return destination
