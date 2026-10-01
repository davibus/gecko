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
from google_tracker import GoogleTracker, job_key, load_environment  # noqa: E402
from resume_storage import GoogleDriveResumeStore  # noqa: E402

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
    return re.split(r"\s+[—–]\s+", match.group(1), maxsplit=1)[0] if match else ""


def filename_job_number(path: Path) -> str:
    return path.stem.rsplit("+", 1)[-1]


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
            record.scout_id, application["Resume Link"], require_approved=False
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
) -> JobRecord:
    """Publish a validated resume, then atomically complete Columns G and S."""
    record = record_from_files(resume, listing)
    if record.scout_id is not None and record.scout_id != scout_id:
        raise RuntimeError("Archived listing Scout ID does not match the live Job Scout row")
    resume_url = publish_resume(record, tracker, scout_id=scout_id)
    mark_batch_resume(scout_id, scout_row, tracker, resume_url)
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
    if record.scout_id is not None and record.scout_id != scout_id:
        raise RuntimeError("Archived listing Scout ID does not match the live Job Scout row")
    mark_batch_resume(
        scout_id, scout_row, tracker, path.as_uri(), allow_local=True,
        require_approved=require_approved,
    )
    return record


def publish_resume(
    record: JobRecord,
    tracker: GoogleTracker,
    *,
    scout_id: int | None = None,
    store: GoogleDriveResumeStore | None = None,
) -> str:
    """Return the existing or newly uploaded persistent URL for this exact job."""
    drive = store or GoogleDriveResumeStore(tracker.config.credentials_file)
    upload = drive.publish(
        record.resume_path, record.job_number,
        scout_id=scout_id if scout_id is not None else record.scout_id,
    )
    if not upload.url.startswith("https://"):
        raise RuntimeError("Resume created but no accessible resume URL was returned")
    return upload.url


def _without_resume_failure(value: object) -> str:
    lines = str(value or "").splitlines()
    kept = [line for line in lines
            if not line.strip().casefold().startswith(RESUME_FAILURE_PREFIX.casefold())]
    return "\n".join(kept).strip()


def _queue_source_row(scout_id: int | None, row_number: int, tracker: GoogleTracker):
    tab = tracker.scout(value_render_option="FORMULA")
    required = {"Resume Created", "Apply?", "Scout ID", "Notes"}
    if not required <= tab.headers.keys():
        raise RuntimeError("Required Scout headers are missing; no cell was changed")
    if (tab.headers["Apply?"] != 6 or tab.headers["Resume Created"] != 7
            or tab.headers["Notes"] != 9):
        raise RuntimeError(
            "Apply? must be Column F, Resume Created Column G, and Notes Column I; "
            "no cell was changed"
        )
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
    """Leave Column G unchanged and write a specific retryable failure to Column I."""
    tab, row, data = _queue_source_row(scout_id, row_number, tracker)
    if str(data.get("Apply?") or "").strip().casefold() != "yes":
        raise RuntimeError("Apply? is no longer Yes; no cell was changed")
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
) -> None:
    """Write Column G and fixed Column S together after stable-ID verification."""
    tab, row, data = _queue_source_row(scout_id, row_number, tracker)
    if require_approved and str(data.get("Apply?") or "").strip().casefold() != "yes":
        raise RuntimeError("Apply? is no longer Yes; no cell was changed")
    notes = _without_resume_failure(data.get("Notes"))
    tracker.mark_scout_resume(
        scout_id, resume_url, notes=notes, row_number=row, allow_local=allow_local,
        require_approved=require_approved,
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
