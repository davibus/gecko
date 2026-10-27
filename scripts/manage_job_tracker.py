"""Record completed Gecko resumes in the canonical Google Sheet only."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import re
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from google_tracker import (  # noqa: E402
    GoogleTracker,
    job_key,
    load_environment,
    verified_resume_file_uri,
    resume_already_created,
    is_expired_indeed,
    INDEED_APPLICATION_HEADER,
)
from rejected_jobs import PermanentlyRejectedError  # noqa: E402
from normalize import canonicalize_url  # noqa: E402
from sources.indeed import extract_indeed_job_key  # noqa: E402
import resume_naming

RESUME_DIR = ROOT / "output/resumes"
LISTING_DIR = ROOT / "input/job-descriptions"
RESUME_FAILURE_PREFIX = "Resume not created:"


@dataclass
class JobRecord:
    company: str
    job_title: str
    pay: str
    job_number: str
    job_link: str
    resume_path: Path
    date_created: date | None
    source: str = ""
    date_found: date | None = None
    scout_id: int | None = None


def project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def markdown_field(text: str, labels: Iterable[str]) -> str:
    for label in labels:
        match = re.search(rf"(?im)^[ \t]*[-*]?[ \t]*\*\*{re.escape(label)}:\*\*[ \t]*([^\r\n]*)", text)
        if match:
            value = match.group(1).strip("`*_ ")
            link = re.fullmatch(r"\[([^]]+)]\((https?://[^)]+)\)", value)
            return link.group(2) if link else value
    return ""


def extract_title(text: str) -> str:
    title = markdown_field(text, ("Job Title", "Title"))
    if title:
        return title
    match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    # Canonical queue archives use the exact tracker title as their heading.
    # A dash can be part of that title, not a company/location separator.
    if match and markdown_field(text, ("Scout ID",)).isdigit():
        return match.group(1)
    return re.split(r"\s+[—–]\s+", match.group(1), maxsplit=1)[0] if match else ""


def filename_job_number(path: Path) -> str:
    return resume_naming.job_number(path)


def record_from_files(resume: Path, listing: Path | None,
                      *, date_override: date | None = None) -> JobRecord:
    if not resume.is_file():
        raise ValueError("Final DOCX must exist before tracker update")
    listing_text = read_text(listing) if listing and listing.is_file() else ""
    job_number = (markdown_field(listing_text, ("Job Key (Indeed jk)", "Indeed job key", "Job Number"))
                  or (re.search(r"[?&]jk=([A-Za-z0-9_-]+)", listing_text) or [None, ""])[1]
                  or filename_job_number(resume))
    company = markdown_field(listing_text, ("Company",))
    title = extract_title(listing_text)
    missing = [name for name, value in (("company", company), ("job title", title),
                                        ("job number", job_number)) if not value]
    if missing:
        raise ValueError("Cannot record completed resume; missing " + ", ".join(missing))
    found = markdown_field(listing_text, ("Date Discovered", "Date Found"))
    try:
        date_found = datetime.fromisoformat(found).date() if found else None
    except ValueError:
        date_found = None
    scout_value = markdown_field(listing_text, ("Scout ID",))
    return JobRecord(
        company, title, markdown_field(listing_text, ("Salary", "Pay", "Compensation")),
        job_number,
        markdown_field(listing_text, ("URL", "Source URL", "Application URL", "Job Link")),
        resume, date_override or date.today(), markdown_field(listing_text, ("Source",)),
        date_found, int(scout_value) if scout_value.isdigit() else None,
    )


def record_completed_resume(
    resume: Path,
    listing: Path | None,
    tracker: GoogleTracker,
    *,
    date_override: date | None = None,
) -> tuple[int, bool, JobRecord]:
    """Upsert one validated Gecko result and mark its matching Scout row."""
    record = record_from_files(resume, listing, date_override=date_override)
    _assert_not_rejected(record, tracker)
    _assert_no_existing_scout_resume(record, tracker)
    try:
        tracker.application()
        has_application_tab = True
    except RuntimeError as error:
        if "was not found exactly once" not in str(error):
            raise
        has_application_tab = False
    if not has_application_tab:
        # The current workbook uses Job Scout as its sole job ledger. Resolve
        # a pre-existing row before changing any cell; never create a guessed
        # row from a resume filename or silently restore the retired tab.
        matches = _matching_scout_rows(record, tracker)
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one existing Job Scout row for {record.job_number!r}; "
                f"found {len(matches)}. No tracker cells were changed"
            )
        row, data = matches[0]
        scout_id = str(data.get("Scout ID") or "").strip()
        if scout_id and not scout_id.isdigit():
            raise RuntimeError(f"Job Scout row {row} has a nonnumeric ID; no cells were changed")
        resume_url = publish_resume(record, tracker)
        mark_batch_resume(int(scout_id) if scout_id else None, row, tracker,
                          resume_url, allow_local=True, require_approved=True)
        return row, False, record
    resume_url = publish_resume(record, tracker)
    application = {
        "Company": record.company, "Job Title": record.job_title, "Pay": record.pay,
        "Job Number": record.job_number,
        "Job Link": record.job_link, "Resume Link": resume_url,
        "Date Created": record.date_created.strftime("%m/%d/%Y") if record.date_created else "",
        "Source": record.source,
        "Date Found": record.date_found.strftime("%m/%d/%Y") if record.date_found else "",
        "Status": "resume-created",
    }
    if record.scout_id is not None:
        tracker.mark_scout_resume(
            record.scout_id, application["Resume Link"], require_approved=True,
            allow_local=True,
        )
    try:
        row, created = tracker.upsert_application(application)
    except RuntimeError as error:
        if "was not found exactly once" not in str(error) or record.scout_id is None:
            raise
        scout = tracker.scout()
        row = next(number for number, data in scout.rows
                   if str(data.get("Scout ID")) == str(record.scout_id))
        created = False
    return row, created, record


def record_queue_success(
    resume: Path,
    listing: Path | None,
    scout_id: int | None,
    scout_row: int,
    tracker: GoogleTracker,
    *,
    completion_marker: str = "X",
    require_approved: bool = True,
) -> JobRecord:
    """Verify a validated resume, then atomically complete its queue fields."""
    record = record_from_files(resume, listing)
    _assert_not_rejected(record, tracker)
    if record.scout_id is not None and record.scout_id != scout_id:
        raise RuntimeError("Archived listing Scout ID does not match the live Job Scout row")
    resume_url = publish_resume(record, tracker, scout_id=scout_id)
    mark_batch_resume(
        scout_id, scout_row, tracker, resume_url,
        allow_local=True, completion_marker=completion_marker,
        require_approved=require_approved,
    )
    return record


def record_queue_success_local(
    resume: Path,
    listing: Path | None,
    scout_id: int | None,
    scout_row: int,
    tracker: GoogleTracker,
    *,
    require_approved: bool = True,
) -> JobRecord:
    """Complete a manual Indeed row from its validated local Gecko DOCX."""
    path = Path(resume).resolve()
    local_root = RESUME_DIR.resolve()
    if path.parent != local_root or path.suffix.casefold() != ".docx":
        raise ValueError(f"Final Indeed resume must be a DOCX directly under {local_root}")
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("Final local DOCX is missing or empty")
    record = record_from_files(path, listing)
    _assert_not_rejected(record, tracker)
    if record.scout_id is not None and record.scout_id != scout_id:
        raise RuntimeError("Archived listing Scout ID does not match the live Job Scout row")
    mark_batch_resume(
        scout_id, scout_row, tracker, publish_resume(record, tracker, scout_id=scout_id), allow_local=True,
        require_approved=require_approved,
    )
    return record


def publish_resume(
    record: JobRecord,
    tracker: GoogleTracker,
    *,
    scout_id: int | None = None,
) -> str:
    """Return the verified private Drive URL for this completed local resume."""
    del tracker, scout_id
    from resume_delivery import publish
    return publish(record.resume_path)


def _assert_not_rejected(record: JobRecord, tracker: GoogleTracker) -> None:
    if tracker.rejected_jobs_index().match(
        source=record.source,
        job_id=record.job_number,
        url=record.job_link,
    ) is not None:
        raise PermanentlyRejectedError(
            "Job is permanently rejected; no resume or tracker fields were written"
        )


def _assert_no_existing_scout_resume(record: JobRecord, tracker: GoogleTracker) -> None:
    """Protect manual tracker upserts when a listing lacks a Scout ID."""
    tab = tracker.scout(value_render_option="FORMULA")
    if "Resume Created" not in tab.headers:
        raise RuntimeError("Job Scout is missing Resume Created; tracker update was stopped")
    for _, data in _matching_scout_rows(record, tracker, tab=tab):
        if resume_already_created(data.get("Resume Created")):
            raise RuntimeError("SKIP RESUME: existing tracker row already has Resume Created = X")


def _matching_scout_rows(record: JobRecord, tracker: GoogleTracker, *, tab=None):
    """Find a live row by stable ID, canonical URL, or Indeed job key."""
    tab = tab or tracker.scout(value_render_option="FORMULA")
    scout_id = str(record.scout_id or "")
    if not scout_id and re.fullmatch(r"scout-\d+", record.job_number, re.IGNORECASE):
        scout_id = record.job_number.split("-")[-1]
    url = canonicalize_url(record.job_link) if record.job_link else ""
    indeed_key = extract_indeed_job_key(record.job_link) or (
        record.job_number if record.source.casefold() == "indeed" else ""
    )
    matches = []
    for row, data in tab.rows:
        existing_url = str(data.get("Job URL") or "")
        if not (
            (scout_id and str(data.get("Scout ID") or "").strip() == scout_id)
            or (url and canonicalize_url(existing_url) == url)
            or (indeed_key and extract_indeed_job_key(existing_url) == indeed_key)
        ):
            continue
        matches.append((row, data))
    return matches


def _without_resume_failure(value: object) -> str:
    lines = str(value or "").splitlines()
    kept = [line for line in lines
            if not line.strip().casefold().startswith(RESUME_FAILURE_PREFIX.casefold())]
    return "\n".join(kept).strip()


def _queue_source_row(scout_id: int | None, row_number: int, tracker: GoogleTracker):
    tab = tracker.scout(value_render_option="FORMULA")
    required = {"Resume Created", "Apply?", "Scout ID", "Cost", "Notes", "Resume Link"}
    if not required <= tab.headers.keys():
        raise RuntimeError("Required Scout headers are missing; no cell was changed")
    if scout_id is None:
        matches = [(row, data) for row, data in tab.rows
                   if row == row_number and not str(data.get("Scout ID") or "").strip()]
    else:
        matches = [(row, data) for row, data in tab.rows
                   if str(data.get("Scout ID") or "") == str(scout_id)]
    if len(matches) != 1:
        raise RuntimeError("Could not verify unique Job Tracker row before writing resume link")
    # row_number is deliberately only a hint. Sorting or earlier processing may
    # move rows; the stable Scout ID decides the live destination.
    return tab, matches[0][0], matches[0][1]


def record_queue_failure(
    scout_id: int | None,
    row_number: int,
    reason: str,
    tracker: GoogleTracker,
) -> None:
    """Leave Resume Created unchanged and write a retryable failure to Notes."""
    tab, row, data = _queue_source_row(scout_id, row_number, tracker)
    if str(data.get("Apply?") or "").strip().casefold() != "yes":
        raise RuntimeError("Apply? is no longer Yes; no cell was changed")
    if is_expired_indeed(data.get(INDEED_APPLICATION_HEADER)):
        raise RuntimeError("Expired Indeed job cannot enter the resume queue")
    detail = " ".join(str(reason or "").split()).strip()
    if detail.casefold().startswith(RESUME_FAILURE_PREFIX.casefold()):
        message = detail
    else:
        message = f"{RESUME_FAILURE_PREFIX} {detail or 'the generation error did not provide details.'}"
    prior = _without_resume_failure(data.get("Notes"))
    notes = f"{prior}\n{message}" if prior else message
    tracker._write(tab, row, {"Notes": notes})


def add_job(args: argparse.Namespace, tracker: GoogleTracker | None = None) -> int:
    tracker = tracker or GoogleTracker()
    row, created, record = record_completed_resume(
        project_path(args.resume),
        project_path(args.job_description) if args.job_description else None,
        tracker,
        date_override=(datetime.strptime(args.date_created, "%m/%d/%Y").date()
                       if args.date_created else None),
    )
    print(f"{'Added' if created else 'Updated'} Google Job Tracker row {row}: {record.company} — {record.job_title}")
    return 0


def mark_batch_resume(
    scout_id: int | None, row_number: int, tracker: GoogleTracker, resume_url: str,
    *, allow_local: bool = False, require_approved: bool = True,
    completion_marker: str = "X",
) -> None:
    """Write Resume Created and Resume Link together after stable-ID verification."""
    tab, row, data = _queue_source_row(scout_id, row_number, tracker)
    if resume_already_created(data.get("Resume Created")):
        raise RuntimeError("SKIP RESUME: existing tracker row already has Resume Created = X")
    if is_expired_indeed(data.get(INDEED_APPLICATION_HEADER)):
        raise RuntimeError("Expired Indeed job cannot receive a resume link")
    from google_tracker import marked
    if marked(data.get("Applied")):
        raise RuntimeError("Already applied job cannot receive a new resume link")
    if tracker.rejected_jobs_index().match(
        source=data.get("Source"),
        job_id=data.get("Job Number"),
        url=data.get("Job URL") or data.get("Job Link"),
    ) is not None:
        raise PermanentlyRejectedError("Job is permanently rejected; no queue fields were changed")
    if require_approved and str(data.get("Apply?") or "").strip().casefold() != "yes":
        raise RuntimeError("Apply? is no longer Yes; no cell was changed")
    if str(data.get("Cost") or "").strip().casefold() == "x":
        raise RuntimeError("Cost is X; no cell was changed")
    from google_tracker import resume_approval_value
    effective = tracker.scout()
    matches = [value for number, value in effective.rows if number == row]
    if require_approved and (len(matches) != 1 or resume_approval_value(
            matches[0].get("Location"), matches[0].get("Work Arrangement"),
            matches[0].get("Cost")) != "Yes"):
        raise RuntimeError("Utah/remote location and no required application fee are required")
    notes = _without_resume_failure(data.get("Notes"))
    tracker.mark_scout_resume(
        scout_id, resume_url, notes=notes, row_number=row, allow_local=allow_local,
        require_approved=require_approved, completion_marker=completion_marker,
    )


def validate(tracker: GoogleTracker | None = None) -> int:
    tracker = tracker or GoogleTracker()
    scout = tracker.scout()
    scout_ids = [str(data.get("Scout ID")) for _, data in scout.rows if str(data.get("Scout ID") or "").strip()]
    if len(scout_ids) != len(set(scout_ids)):
        raise RuntimeError("Google Job Scout contains duplicate Scout ID values")
    try:
        tab = tracker.application()
    except RuntimeError as error:
        if "not found" not in str(error).casefold():
            raise
        print(f"Google Job Scout valid: {len(scout.rows)} rows; no Job Tracker tab; {tracker.url()}")
        return 0
    numbers = [job_key(data) for _, data in tab.rows if job_key(data)]
    if len(numbers) != len(set(numbers)):
        raise RuntimeError("Google Job Tracker contains duplicate Job Number values")
    index_field = "Index" if "Index" in tab.headers else "Resume #"
    indexes = [int(data[index_field]) for _, data in tab.rows
               if str(data.get(index_field, "")).strip().isdigit()]
    if len(indexes) != len(set(indexes)):
        raise RuntimeError("Google Job Tracker contains duplicate index numbers")
    print(f"Google Job Tracker valid: {len(tab.rows)} rows; {tracker.url()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Verify the configured existing Google worksheets")
    add = sub.add_parser("add", help="Record one QA-passed Gecko resume")
    add.add_argument("--resume", required=True)
    add.add_argument("--job-description", required=True)
    add.add_argument("--date-created")
    sub.add_parser("validate", help="Read and validate Google tracker uniqueness")
    args = parser.parse_args()
    try:
        load_environment(ROOT)
        tracker = GoogleTracker()
        if args.command == "add":
            return add_job(args, tracker)
        if args.command == "init":
            tracker.scout()
            try:
                tracker.application()
            except RuntimeError as error:
                if "not found" not in str(error).casefold():
                    raise
            print(f"Google tracker ready: {tracker.url()}")
            return 0
        return validate(tracker)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Google tracker error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
