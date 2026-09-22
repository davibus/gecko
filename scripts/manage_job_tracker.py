"""Create, update, backfill, and validate Gecko's persistent job tracker.

Examples:
    python scripts/manage_job_tracker.py init
    python scripts/manage_job_tracker.py add \
        --resume output/resumes/Dave-Call+Acme+abc123.docx \
        --match-report output/match-reports/Dave-Call+Acme+abc123.md \
        --job-description input/job-descriptions/Acme+abc123.md
    python scripts/manage_job_tracker.py import-history
    python scripts/manage_job_tracker.py validate
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from urllib.parse import urlsplit
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet


ROOT = Path(__file__).resolve().parents[1]
JOB_SCOUT_ROOT = ROOT / "job-scout"
if str(JOB_SCOUT_ROOT) not in sys.path:
    sys.path.insert(0, str(JOB_SCOUT_ROOT))

from google_sheets_sync import load_environment_files, sync_workbook_to_google, tracker_backend
from excel_preservation import append_preserving_format

DEFAULT_TRACKER = ROOT / "output" / "job-tracker.xlsx"
RESUME_DIR = ROOT / "output" / "resumes"
REPORT_DIR = ROOT / "output" / "match-reports"
JOB_DESCRIPTION_DIR = ROOT / "input" / "job-descriptions"
SHEET_NAME = "Job Tracker"

HEADERS = [
    "Resume #",
    "Company",
    "Job Title",
    "Pay",
    "Job Number",
    "Match Score",
    "Job Link",
    "Resume Link",
    "Date Created",
    "Applied",
    "Contacted",
    "Source",
    "Date Found",
    "Status",
]

LEGACY_HEADERS = HEADERS[:11]

COLUMN_WIDTHS = {
    "A": 11,
    "B": 28,
    "C": 42,
    "D": 31,
    "E": 22,
    "F": 14,
    "G": 38,
    "H": 48,
    "I": 15,
    "J": 12,
    "K": 12,
    "L": 18,
    "M": 15,
    "N": 18,
}


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
    status: str = "resume-created"
    scout_id: int | None = None


def project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def clean_markdown(value: str) -> str:
    value = value.strip().rstrip("  ")
    link = re.fullmatch(r"\[([^]]+)]\((https?://[^)]+)\)", value)
    if link:
        return link.group(2)
    return value.strip("`*_ ")


def markdown_field(text: str, labels: Iterable[str]) -> str:
    for label in labels:
        pattern = rf"(?im)^[ \t]*[-*]?[ \t]*\*\*{re.escape(label)}:\*\*[ \t]*([^\r\n]*)[ \t]*\r?$"
        match = re.search(pattern, text)
        if match:
            return clean_markdown(match.group(1))
    return ""


def extract_job_number(text: str) -> str:
    value = markdown_field(text, ("Job Key (Indeed jk)", "Indeed job key", "Job Number"))
    if value:
        return value
    match = re.search(r"[?&]jk=([A-Za-z0-9_-]+)", text)
    return match.group(1) if match else ""


def extract_score(text: str) -> str:
    match = re.search(
        r"(?i)(?:overall\s+)?match\s+score[^\d]{0,30}(\d{1,3})\s*/\s*100",
        text,
    )
    if not match:
        return ""
    score = int(match.group(1))
    return f"{score}/100" if 0 <= score <= 100 else ""


def extract_title(text: str) -> str:
    value = markdown_field(text, ("Job Title", "Title"))
    if value:
        return value
    heading = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    if not heading:
        return ""
    return re.split(r"\s+[—–]\s+", heading.group(1).strip(), maxsplit=1)[0].strip()


def filename_job_number(path: Path) -> str:
    stem = path.stem
    if stem.startswith("Dave-Call+"):
        stem = stem[len("Dave-Call+") :]
    return stem.rsplit("+", 1)[-1]


def find_by_job_number(directory: Path, suffix: str, job_number: str) -> Path | None:
    exact = sorted(directory.glob(f"*+{job_number}{suffix}"))
    if exact:
        return exact[0]
    for path in sorted(directory.glob(f"*{suffix}")):
        if job_number in read_text(path):
            return path
    return None


def reliable_historical_date(paths: Iterable[Path]) -> date | None:
    """Use filesystem dates only when all supplied artifacts agree on the day."""
    existing = [path for path in paths if path and path.exists()]
    if len(existing) < 2:
        return None
    days = {datetime.fromtimestamp(path.stat().st_mtime).date() for path in existing}
    return days.pop() if len(days) == 1 else None


def record_from_files(
    resume: Path,
    report: Path,
    job_description: Path | None,
    *,
    historical: bool,
    date_override: date | None = None,
) -> JobRecord:
    if not resume.is_file():
        raise ValueError(f"Resume does not exist: {resume}")
    if not report.is_file():
        raise ValueError(f"Match report does not exist: {report}")

    report_text = read_text(report)
    listing_text = read_text(job_description) if job_description and job_description.is_file() else ""
    combined = listing_text + "\n" + report_text
    job_number = extract_job_number(combined) or filename_job_number(resume)
    company = markdown_field(listing_text, ("Company",)) or markdown_field(report_text, ("Company",))
    title = (
        markdown_field(listing_text, ("Job Title", "Title"))
        or markdown_field(report_text, ("Job Title", "Title"))
        or extract_title(listing_text)
        or extract_title(report_text)
    )
    pay = markdown_field(
        listing_text,
        ("Salary", "Pay", "Compensation", "Compensation in supplied listing"),
    )
    job_link = markdown_field(
        listing_text,
        ("URL", "Source URL", "Application URL", "Job Link"),
    ) or markdown_field(report_text, ("Application URL", "URL", "Source URL", "Job Link"))
    score = extract_score(report_text)
    source = markdown_field(listing_text, ("Source",))
    scout_id_value = markdown_field(listing_text, ("Scout ID",))
    scout_id = int(scout_id_value) if scout_id_value.isdigit() else None
    if not source and "indeed.com/" in job_link.lower():
        source = "Indeed"
    found_value = markdown_field(listing_text, ("Date Discovered", "Date Found"))
    try:
        date_found = datetime.fromisoformat(found_value).date() if found_value else None
    except ValueError:
        date_found = None

    missing = [
        name
        for name, value in (
            ("company", company),
            ("job title", title),
            ("job number", job_number),
            ("match score", score),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Cannot add {resume.name}; missing required evidence: {', '.join(missing)}")

    if date_override:
        created = date_override
    elif historical:
        created = reliable_historical_date(path for path in (resume, report, job_description) if path)
    else:
        created = date.today()

    return JobRecord(
        company, title, pay, job_number, score, job_link, resume, created,
        source=source, date_found=date_found, status="resume-created", scout_id=scout_id,
    )


def style_worksheet(ws: Worksheet) -> None:
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(vertical="center", wrap_text=False)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:N{max(ws.max_row, 1)}"
    ws.row_dimensions[1].height = 22
    for column, width in COLUMN_WIDTHS.items():
        ws.column_dimensions[column].width = width
    for row in range(2, ws.max_row + 1):
        for column in range(1, len(HEADERS) + 1):
            ws.cell(row, column).alignment = Alignment(vertical="top", wrap_text=False)


def create_workbook() -> Workbook:
    workbook = Workbook()
    ws = workbook.active
    ws.title = SHEET_NAME
    ws.append(HEADERS)
    style_worksheet(ws)
    return workbook


def load_tracker(path: Path) -> Workbook:
    if not path.exists():
        return create_workbook()
    workbook = load_workbook(path)
    if SHEET_NAME not in workbook.sheetnames:
        raise ValueError(f"Tracker must contain a worksheet named {SHEET_NAME!r}")
    ws = workbook[SHEET_NAME]
    populated_headers = [ws.cell(1, column).value for column in range(1, ws.max_column + 1)]
    if populated_headers == LEGACY_HEADERS:
        for column, value in enumerate(HEADERS[len(LEGACY_HEADERS):], len(LEGACY_HEADERS) + 1):
            target = ws.cell(1, column, value)
            source = ws.cell(1, len(LEGACY_HEADERS))
            if source.has_style:
                from copy import copy
                target._style = copy(source._style)
    elif populated_headers != HEADERS:
        raise ValueError("Tracker columns do not match Gecko's required schema")
    return workbook


def source_from_url(value: str) -> str:
    host = urlsplit(value).netloc.lower().removeprefix("www.")
    known = {
        "indeed.com": "Indeed", "linkedin.com": "LinkedIn", "adzuna.com": "Adzuna",
        "ziprecruiter.com": "ZipRecruiter", "monster.com": "Monster",
    }
    for domain, source in known.items():
        if host == domain or host.endswith("." + domain):
            return source
    return host


def backfill_extended_fields(ws: Worksheet) -> bool:
    """Populate evidence-backed fields added after the original tracker schema."""
    changed = False
    for row in range(2, ws.max_row + 1):
        if not ws.cell(row, 12).value and ws.cell(row, 7).value:
            ws.cell(row, 12, source_from_url(str(ws.cell(row, 7).value)))
            changed = True
        if not ws.cell(row, 14).value and ws.cell(row, 8).value:
            ws.cell(row, 14, "resume-created")
            changed = True
    return changed


def save_atomic(workbook: Workbook, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix="job-tracker-", suffix=".xlsx", dir=path.parent, delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        workbook.save(temp_path)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def existing_job_numbers(ws: Worksheet) -> set[str]:
    return {
        str(ws.cell(row, 5).value).strip()
        for row in range(2, ws.max_row + 1)
        if ws.cell(row, 5).value not in (None, "")
    }


def next_resume_number(ws: Worksheet) -> int:
    numbers = []
    for row in range(2, ws.max_row + 1):
        value = ws.cell(row, 1).value
        if isinstance(value, int):
            numbers.append(value)
        elif isinstance(value, str) and value.isdigit():
            numbers.append(int(value))
    return max(numbers, default=0) + 1


def relative_resume_link(resume: Path, tracker: Path) -> str:
    try:
        return Path(os.path.relpath(resume.resolve(), tracker.parent.resolve())).as_posix()
    except ValueError:
        return str(resume.resolve())


def append_record(ws: Worksheet, tracker: Path, record: JobRecord) -> bool:
    if record.job_number in existing_job_numbers(ws):
        return False
    resume_link = relative_resume_link(record.resume_path, tracker)
    values = [
        next_resume_number(ws), record.company, record.job_title, record.pay or None,
        record.job_number, record.match_score, record.job_link or None, resume_link,
        record.date_created, None, None,
        record.source or None, record.date_found, record.status,
    ]
    row = append_preserving_format(ws, set(HEADERS))
    for column, value in enumerate(values, 1):
        ws.cell(row, column, value)
    if record.job_link:
        ws.cell(row, 7).hyperlink = record.job_link
    ws.cell(row, 8).hyperlink = resume_link
    return True


def upsert_record(ws: Worksheet, tracker: Path, record: JobRecord) -> tuple[bool, bool]:
    """Add or refresh one application row while preserving manual fields."""
    target_row = next(
        (
            row for row in range(2, ws.max_row + 1)
            if str(ws.cell(row, 5).value or "").strip() == record.job_number
        ),
        None,
    )
    if target_row is None:
        return append_record(ws, tracker, record), True

    resume_link = relative_resume_link(record.resume_path, tracker)
    before = [ws.cell(target_row, column).value for column in range(1, len(HEADERS) + 1)]
    updated = [
        before[0], record.company, record.job_title, record.pay or None,
        record.job_number, record.match_score, record.job_link or None, resume_link,
        record.date_created, before[9], before[10], record.source or None,
        record.date_found, record.status,
    ]
    changed = before != updated
    for column, value in enumerate(updated, 1):
        if ws.cell(target_row, column).value != value:
            ws.cell(target_row, column).value = value
    if record.job_link:
        link_cell = ws.cell(target_row, 7)
        current = link_cell.hyperlink.target if link_cell.hyperlink else None
        if current != record.job_link:
            link_cell.hyperlink = record.job_link
            changed = True
    else:
        if ws.cell(target_row, 7).hyperlink is not None:
            ws.cell(target_row, 7).hyperlink = None
            changed = True
    resume_cell = ws.cell(target_row, 8)
    current_resume = resume_cell.hyperlink.target if resume_cell.hyperlink else None
    if current_resume != resume_link:
        resume_cell.hyperlink = resume_link
        changed = True
    return False, changed


def mark_scout_resume_created(workbook: Workbook, record: JobRecord) -> bool:
    """Advance an existing Scout row without changing its manual application fields."""
    if record.scout_id is None or "Job Scout" not in workbook.sheetnames:
        return False
    ws = workbook["Job Scout"]
    headers = {ws.cell(1, column).value: column for column in range(1, ws.max_column + 1)}
    required = {"Scout ID", "Gecko Status", "Resume Created"}
    if not required <= headers.keys():
        return False
    for row in range(2, ws.max_row + 1):
        if str(ws.cell(row, headers["Scout ID"]).value) == str(record.scout_id):
            changed = False
            status_cell = ws.cell(row, headers["Gecko Status"])
            if status_cell.value != "Resume Created":
                status_cell.value = "Resume Created"
                changed = True
            created_cell = ws.cell(row, headers["Resume Created"])
            if created_cell.value != "X":
                created_cell.value = "X"
                changed = True
            if "Resume Link" in headers:
                link = record.resume_path.resolve().as_uri()
                link_cell = ws.cell(row, headers["Resume Link"])
                current = link_cell.hyperlink.target if link_cell.hyperlink else None
                if link_cell.value != link:
                    link_cell.value = link
                    changed = True
                if current != link:
                    link_cell.hyperlink = link
                    changed = True
            return changed
    return False


def init_tracker(tracker: Path) -> int:
    existed = tracker.exists()
    workbook = load_tracker(tracker)
    changed = backfill_extended_fields(workbook[SHEET_NAME])
    if not existed:
        save_atomic(workbook, tracker)
    elif changed:
        save_atomic(workbook, tracker)
    print(f"Tracker ready: {tracker}")
    return 0


def add_job(args: argparse.Namespace, tracker: Path) -> int:
    resume = project_path(args.resume)
    report = project_path(args.match_report)
    listing = project_path(args.job_description) if args.job_description else None
    date_override = datetime.strptime(args.date_created, "%m/%d/%Y").date() if args.date_created else None
    record = record_from_files(resume, report, listing, historical=False, date_override=date_override)
    workbook = load_tracker(tracker)
    ws = workbook[SHEET_NAME]
    backfilled = backfill_extended_fields(ws)
    added, tracker_updated = upsert_record(ws, tracker, record)
    scout_updated = mark_scout_resume_created(workbook, record)
    if tracker_updated or scout_updated or backfilled:
        save_atomic(workbook, tracker)
    if tracker_backend() == "google-sheets":
        google = sync_workbook_to_google(tracker)
        print(
            f"Google Sheets synchronized: {google.application_rows} Job Tracker rows, "
            f"{google.scout_rows} Job Scout rows"
        )
    if added:
        print(f"Added Resume #{ws.max_row - 1}: {record.company} — {record.job_title}")
    elif tracker_updated:
        print(f"Updated Job Number {record.job_number}: {record.company} — {record.job_title}")
    else:
        print(f"No change: Job Number {record.job_number} is already tracked")
    return 0


def historical_records() -> list[JobRecord]:
    records = []
    for resume in sorted(RESUME_DIR.glob("*.docx")):
        job_number = filename_job_number(resume)
        report = find_by_job_number(REPORT_DIR, ".md", job_number)
        if not report:
            print(f"Skipped {resume.name}: no corresponding match report", file=sys.stderr)
            continue
        listing = find_by_job_number(JOB_DESCRIPTION_DIR, ".md", job_number)
        try:
            records.append(record_from_files(resume, report, listing, historical=True))
        except ValueError as error:
            print(f"Skipped {resume.name}: {error}", file=sys.stderr)
    return sorted(
        records,
        key=lambda record: (
            record.date_created is None,
            record.date_created or date.max,
            record.resume_path.stat().st_mtime if record.date_created else 0,
            record.job_number,
        ),
    )


def import_history(tracker: Path) -> int:
    workbook = load_tracker(tracker)
    ws = workbook[SHEET_NAME]
    backfilled = backfill_extended_fields(ws)
    added = 0
    for record in historical_records():
        if append_record(ws, tracker, record):
            added += 1
    if added or backfilled:
        save_atomic(workbook, tracker)
    print(f"Historical import complete: {added} added, {ws.max_row - 1} total")
    return 0


def validate_tracker(tracker: Path) -> int:
    if not tracker.is_file():
        raise ValueError(f"Tracker does not exist: {tracker}")
    workbook = load_tracker(tracker)
    ws = workbook[SHEET_NAME]
    errors = []
    raw_numbers = [ws.cell(row, 1).value for row in range(2, ws.max_row + 1)]
    try:
        numbers = [int(value) for value in raw_numbers]
    except (TypeError, ValueError):
        numbers = []
    if sorted(numbers) != list(range(1, len(raw_numbers) + 1)):
        errors.append("Resume # values do not form a unique sequence starting at 1")
    jobs = [ws.cell(row, 5).value for row in range(2, ws.max_row + 1)]
    if len(jobs) != len(set(jobs)):
        errors.append("duplicate Job Number values found")
    for row in range(2, ws.max_row + 1):
        if not ws.cell(row, 7).hyperlink and ws.cell(row, 7).value:
            errors.append(f"row {row} Job Link is not a hyperlink")
        if not ws.cell(row, 8).hyperlink:
            errors.append(f"row {row} Resume Link is not a hyperlink")
        score = re.fullmatch(r"(\d{1,3})/100", str(ws.cell(row, 6).value or ""))
        if not score or not 0 <= int(score.group(1)) <= 100:
            errors.append(f"row {row} Match Score is invalid")
        if ws.cell(row, 14).value not in (None, "resume-created", "applied", "contacted", "interview", "rejected", "offer", "ignored"):
            errors.append(f"row {row} Status is invalid")
    if errors:
        raise ValueError("Tracker validation failed: " + "; ".join(errors))
    print(f"Tracker valid: {ws.max_row - 1} job rows in {tracker}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracker", default=str(DEFAULT_TRACKER), help="Path to the tracker workbook")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Create or restyle the tracker without adding a row")
    add = subparsers.add_parser("add", help="Add one completed Gecko job")
    add.add_argument("--resume", required=True, help="Final DOCX path")
    add.add_argument("--match-report", required=True, help="Final match report path")
    add.add_argument("--job-description", help="Archived listing path")
    add.add_argument("--date-created", help="Override successful generation date (MM/DD/YYYY)")
    subparsers.add_parser("import-history", help="Backfill completed jobs found in the project")
    subparsers.add_parser("validate", help="Check tracker structure and row invariants")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    tracker = project_path(args.tracker)
    try:
        load_environment_files(ROOT)
        if args.command == "init":
            return init_tracker(tracker)
        if args.command == "add":
            return add_job(args, tracker)
        if args.command == "import-history":
            return import_history(tracker)
        if args.command == "validate":
            return validate_tracker(tracker)
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
