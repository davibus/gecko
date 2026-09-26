"""Read-only Job Scout review queue without compatibility scoring."""

from __future__ import annotations

import json
from datetime import datetime

from models import JobListing
from url_resolution import best_job_url as resolved_best_job_url, url_status_label


CLOSED_STATUSES = {"applied", "rejected", "ignored"}


def _date_value(value: str) -> int:
    if not value:
        return 0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().toordinal()
    except ValueError:
        return 0


def _sort_key(job: JobListing):
    return (-_date_value(job.date_posted), job.company.lower(), job.title.lower(), job.id or 0)


def build_review_queue(
    jobs: list[JobListing], *, limit: int = 20, include_closed: bool = False,
) -> dict[str, list[JobListing]]:
    """Return active discoveries newest first, without evaluating candidate compatibility."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    eligible = [job for job in jobs if include_closed or job.status not in CLOSED_STATUSES]
    return {"jobs": sorted(eligible, key=_sort_key)[:limit]}


def best_job_url(job: JobListing) -> str:
    return resolved_best_job_url(job)


def _employment_type(job: JobListing) -> str:
    return job.employment_type.lower().replace("_", "-") if job.employment_type else ""


def job_record(job: JobListing) -> dict:
    return {
        "job_id": job.id, "company": job.company, "job_title": job.title,
        "location": job.location, "work_arrangement": job.work_arrangement,
        "employment_type": _employment_type(job), "salary": job.salary,
        "source": job.source, "date_posted": job.date_posted, "status": job.status,
        "best_job_url": best_job_url(job), "url_status": url_status_label(job),
        "authoritative_url": job.authoritative_url,
        "authoritative_url_confidence": job.authoritative_url_confidence,
        "enrichment_source": job.enriched_source_url,
    }


def queue_to_dict(queue: dict[str, list[JobListing]]) -> dict[str, list[dict]]:
    return {name: [job_record(job) for job in jobs] for name, jobs in queue.items()}


def queue_to_json(queue: dict[str, list[JobListing]]) -> str:
    return json.dumps(queue_to_dict(queue), indent=2)


def _format_job(job: JobListing) -> list[str]:
    salary = job.salary or "Not provided"
    posted = job.date_posted or "Not provided"
    employment = _employment_type(job) or "Not provided"
    lines = [
        f"[{job.id}] {job.company} - {job.title}",
        f"  Location: {job.location or 'Not provided'} | Arrangement: {job.work_arrangement} | Employment: {employment}",
        f"  Salary: {salary} | Source: {job.source} | Posted: {posted}",
        f"  URL Status: {url_status_label(job)}",
        f"  Best URL: {best_job_url(job) or 'Not provided'}",
    ]
    if job.authoritative_url:
        lines.append(f"  Authoritative URL confidence: {job.authoritative_url_confidence}%")
    if job.enriched_source_url:
        lines.append(f"  Enrichment source: {job.enriched_source_url}")
    lines.append(f"  Select explicitly: python job-scout/scout.py select {job.id}")
    return lines


def format_review_queue(queue: dict[str, list[JobListing]]) -> str:
    jobs = queue["jobs"]
    output = [f"NEWEST ACTIVE JOBS ({len(jobs)})"]
    if not jobs:
        output.append("  None.")
    for job in jobs:
        output.extend(_format_job(job))
        output.append("")
    output.append("Review is read-only. Run `python job-scout/scout.py select <ID>` to begin a Gecko handoff.")
    return "\n".join(output).rstrip()
