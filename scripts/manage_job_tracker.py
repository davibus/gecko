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

RESUME_DIR = ROOT / "output/resumes"
REPORT_DIR = ROOT / "output/match-reports"
LISTING_DIR = ROOT / "input/job-descriptions"


@dataclass
class JobRecord:
    company: str
    job_title: str
    pay: str
    job_number: str
    match_score: str
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


def extract_score(text: str) -> str:
    match = re.search(r"(?i)(?:overall\s+)?match\s+score[^\d]{0,30}(\d{1,3})\s*/\s*100", text)
    if not match:
        return ""
    score = int(match.group(1))
    return f"{score}/100" if 0 <= score <= 100 else ""


def extract_title(text: str) -> str:
    title = markdown_field(text, ("Job Title", "Title"))
    if title:
        return title
    match = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    return re.split(r"\s+[—–]\s+", match.group(1), maxsplit=1)[0] if match else ""


def filename_job_number(path: Path) -> str:
    return path.stem.rsplit("+", 1)[-1]


def record_from_files(resume: Path, report: Path, listing: Path | None,
                      *, date_override: date | None = None) -> JobRecord:
    if not resume.is_file() or not report.is_file():
        raise ValueError("Final DOCX and match report must both exist before tracker update")
    listing_text = read_text(listing) if listing and listing.is_file() else ""
    report_text = read_text(report)
    combined = listing_text + "\n" + report_text
    job_number = (markdown_field(combined, ("Job Key (Indeed jk)", "Indeed job key", "Job Number"))
                  or (re.search(r"[?&]jk=([A-Za-z0-9_-]+)", combined) or [None, ""])[1]
                  or filename_job_number(resume))
    company = markdown_field(listing_text, ("Company",)) or markdown_field(report_text, ("Company",))
    title = extract_title(listing_text) or extract_title(report_text)
    score = extract_score(report_text)
    missing = [name for name, value in (("company", company), ("job title", title),
                                        ("job number", job_number), ("match score", score)) if not value]
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
        job_number, score,
        markdown_field(listing_text, ("URL", "Source URL", "Application URL", "Job Link")),
        resume, date_override or date.today(), markdown_field(listing_text, ("Source",)),
        date_found, int(scout_value) if scout_value.isdigit() else None,
    )


def add_job(args: argparse.Namespace, tracker: GoogleTracker | None = None) -> int:
    tracker = tracker or GoogleTracker()
    record = record_from_files(project_path(args.resume), project_path(args.match_report),
                               project_path(args.job_description) if args.job_description else None,
                               date_override=(datetime.strptime(args.date_created, "%m/%d/%Y").date()
                                              if args.date_created else None))
    application = {
        "Company": record.company, "Job Title": record.job_title, "Pay": record.pay,
        "Job Number": record.job_number, "Match Score": record.match_score,
        "Job Link": record.job_link, "Resume Link": record.resume_path.resolve().as_uri(),
        "Date Created": record.date_created.strftime("%m/%d/%Y") if record.date_created else "",
        "Source": record.source,
        "Date Found": record.date_found.strftime("%m/%d/%Y") if record.date_found else "",
        "Status": "resume-created",
    }
    row, created = tracker.upsert_application(application)
    if record.scout_id is not None:
        tracker.mark_scout_resume(record.scout_id, application["Resume Link"])
    print(f"{'Added' if created else 'Updated'} Google Job Tracker row {row}: {record.company} — {record.job_title}")
    return 0


def mark_batch_resume(scout_id: int, row_number: int, tracker: GoogleTracker) -> None:
    """Mark the selected Scout row using header positions, preserving later statuses."""
    tab = tracker.scout()
    if not {"Resume Created", "Gecko Status", "Apply?", "Scout ID"} <= tab.headers.keys():
        raise RuntimeError("Required Scout headers are missing; no cell was changed")
    matches = [(row, data) for row, data in tab.rows if str(data.get("Scout ID")) == str(scout_id)]
    if len(matches) != 1 or matches[0][0] != row_number:
        raise RuntimeError("Scout row identity changed; no cell was changed")
    row, data = matches[0]
    if str(data.get("Apply?") or "").strip().casefold() != "yes":
        raise RuntimeError("Apply? is no longer Yes; no cell was changed")
    if str(data.get("Resume Created") or "").strip():
        raise RuntimeError("Resume Created is no longer blank; no cell was changed")
    values = {"Resume Created": "X"}
    if str(data.get("Gecko Status") or "").strip().casefold() not in {
            "applied", "contacted", "interview", "offer"}:
        values["Gecko Status"] = "Resume Created"
    tracker._write(tab, row, values)


def validate(tracker: GoogleTracker | None = None) -> int:
    tracker = tracker or GoogleTracker()
    tab = tracker.application()
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
    add.add_argument("--match-report", required=True)
    add.add_argument("--job-description")
    add.add_argument("--date-created")
    sub.add_parser("validate", help="Read and validate Google tracker uniqueness")
    args = parser.parse_args()
    try:
        load_environment(ROOT)
        tracker = GoogleTracker()
        if args.command == "add":
            return add_job(args, tracker)
        if args.command == "init":
            tracker.application()
            tracker.scout()
            print(f"Google tracker ready: {tracker.url()}")
            return 0
        return validate(tracker)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Google tracker error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
