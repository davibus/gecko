"""Synchronize Job Scout history into an isolated worksheet in Gecko's tracker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from models import JobListing
from normalize import canonicalize_url
from url_resolution import best_job_url, url_status_label


SHEET_NAME = "Job Scout"
APPLICATION_SHEET = "Job Tracker"
LEGACY_HEADERS = [
    "Scout ID", "Company", "Job Title", "Match Score", "Evidence Confidence",
    "Match Status", "Location", "Work Arrangement", "Employment Type", "Salary",
    "Source", "Date Posted", "Date Found", "Last Seen", "Top Strengths",
    "Top Weaknesses", "Job URL", "Enrichment URL", "Gecko Status",
    "Resume Created", "Applied", "Contacted",
]
SOURCE_B_HEADERS = [
    "Scout ID", "Source", "Company", "Job Title", "Match Score", "Evidence Confidence",
    "Match Status", "Location", "Work Arrangement", "Employment Type", "Salary",
    "Date Posted", "Date Found", "Last Seen", "Top Strengths", "Top Weaknesses",
    "Job URL", "Enrichment URL", "Gecko Status", "Resume Created", "Applied", "Contacted",
]
RESUME_LINK_HEADERS = SOURCE_B_HEADERS[:20] + ["Resume Link"] + SOURCE_B_HEADERS[20:]
PREVIOUS_HEADERS = [header for header in RESUME_LINK_HEADERS if header not in {"Top Strengths", "Top Weaknesses"}]
URL_STATUSLESS_HEADERS = [
    header for header in PREVIOUS_HEADERS
    if header not in {"Applied", "Resume Link", "Contacted"}
] + ["Applied", "Resume Link", "Contacted"]
HEADERS = (
    URL_STATUSLESS_HEADERS[:14]
    + ["URL Status", "Authoritative URL"]
    + URL_STATUSLESS_HEADERS[14:]
)
STATUS_LABELS = {
    "new": "New", "reviewing": "Reviewing", "selected": "Selected",
    "resume-created": "Resume Created", "applied": "Applied", "contacted": "Contacted",
    "interview": "Interview", "rejected": "Rejected", "ignored": "Ignored", "offer": "Offer",
}
STATUS_RANK = {
    "New": 0, "Reviewing": 1, "Selected": 2, "Resume Created": 3,
    "Applied": 4, "Contacted": 5, "Interview": 6, "Rejected": 7,
    "Ignored": 7, "Offer": 8,
}
COLUMN_WIDTHS = [
    10, 12, 28, 44, 13, 19, 24, 28, 18, 18, 20, 14, 14, 14,
    32, 48, 42, 42, 18, 16, 12, 48, 12,
]


@dataclass
class SyncSummary:
    rows: int
    confirmed: int
    provisional: int
    near_matches: int
    tracker_preserved: bool


def _parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _identity(value: str) -> str:
    return canonicalize_url(str(value or "")).lower()


def match_status(job: JobListing) -> str:
    if job.match_score >= 80 and job.evidence_confidence >= 65 and not job.provisional:
        return "Confirmed Strong Match"
    if job.match_score >= 80:
        return "Provisional 80+"
    if job.match_score >= 70:
        return "Near Match"
    return "Below Threshold"


def _merge_lifecycle(existing: dict, job: JobListing) -> str:
    database_status = STATUS_LABELS.get(job.status, job.status.replace("-", " ").title())
    candidates = [database_status, str(existing.get("Gecko Status") or "New")]
    if existing.get("Resume Created"):
        candidates.append("Resume Created")
    if existing.get("Applied"):
        candidates.append("Applied")
    if existing.get("Contacted"):
        candidates.append("Contacted")
    return max(candidates, key=lambda value: STATUS_RANK.get(value, 0))


def _join(values: list[str]) -> str:
    return "\n".join(f"• {value}" for value in values[:3])


def _job_row(job: JobListing, existing: dict | None = None) -> dict:
    existing = existing or {}
    lifecycle = _merge_lifecycle(existing, job)
    resume_created = existing.get("Resume Created") or ("X" if STATUS_RANK.get(lifecycle, 0) >= 3 else None)
    applied = existing.get("Applied")
    contacted = existing.get("Contacted")
    if not applied and job.status in {"applied", "contacted", "interview", "offer"}:
        applied = "X"
    if not contacted and job.status in {"contacted", "interview", "offer"}:
        contacted = "X"
    return {
        "Scout ID": job.id,
        "Company": job.company,
        "Job Title": job.title,
        "Match Score": job.match_score,
        "Evidence Confidence": job.evidence_confidence / 100,
        "Match Status": match_status(job),
        "Location": job.location,
        "Work Arrangement": job.work_arrangement,
        "Employment Type": job.employment_type.lower().replace("_", "-") if job.employment_type else None,
        "Salary": job.salary or None,
        "Source": job.source,
        "Date Posted": _parse_date(job.date_posted),
        "Date Found": _parse_date(job.date_discovered),
        "Last Seen": _parse_date(job.last_seen or job.date_discovered),
        "URL Status": url_status_label(job),
        "Authoritative URL": job.authoritative_url or None,
        "Job URL": best_job_url(job),
        "Enrichment URL": job.enriched_source_url or None,
        "Gecko Status": lifecycle,
        "Resume Created": resume_created,
        "Resume Link": existing.get("Resume Link"),
        "Applied": applied,
        "Contacted": contacted,
    }


def _existing_rows(ws) -> list[dict]:
    if ws.max_row < 2:
        return []
    headers = [ws.cell(1, column).value for column in range(1, len(HEADERS) + 1)]
    if headers != HEADERS:
        raise ValueError("Existing Job Scout worksheet columns do not match the required schema")
    return [
        {header: ws.cell(row, column).value for column, header in enumerate(HEADERS, 1)}
        for row in range(2, ws.max_row + 1)
        if any(ws.cell(row, column).value not in (None, "") for column in range(1, len(HEADERS) + 1))
    ]


def _migrate_schema(ws) -> None:
    """Migrate supported Job Scout layouts without losing row values."""
    if ws.max_row < 1:
        return
    current = [ws.cell(1, column).value for column in range(1, ws.max_column + 1)]
    while current and current[-1] is None:
        current.pop()
    if current == HEADERS:
        return
    if current == LEGACY_HEADERS:
        source_headers = LEGACY_HEADERS
    elif current == SOURCE_B_HEADERS:
        source_headers = SOURCE_B_HEADERS
    elif current == RESUME_LINK_HEADERS:
        source_headers = RESUME_LINK_HEADERS
    elif current == PREVIOUS_HEADERS:
        source_headers = PREVIOUS_HEADERS
    elif current == URL_STATUSLESS_HEADERS:
        source_headers = URL_STATUSLESS_HEADERS
    else:
        return
    records = [
        {header: ws.cell(row, column).value for column, header in enumerate(source_headers, 1)}
        for row in range(2, ws.max_row + 1)
        if any(ws.cell(row, column).value not in (None, "") for column in range(1, len(source_headers) + 1))
    ]
    ws.delete_rows(1, ws.max_row)
    ws.append(HEADERS)
    for record in records:
        ws.append([record.get(header) for header in HEADERS])


def _sort_key(record: dict):
    confidence = record.get("Evidence Confidence") or 0
    if confidence > 1:
        confidence /= 100
    posted = _parse_date(record.get("Date Posted"))
    return (
        -(record.get("Match Score") or 0),
        -confidence,
        -(posted.toordinal() if posted else 0),
        str(record.get("Company") or "").lower(),
    )


def _style_sheet(ws) -> None:
    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center", horizontal="center", wrap_text=False)
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"
    end_column = get_column_letter(len(HEADERS))
    ws.auto_filter.ref = f"A1:{end_column}{max(ws.max_row, 1)}"
    ws.sheet_properties.tabColor = "5B9BD5"
    for index, width in enumerate(COLUMN_WIDTHS, 1):
        ws.column_dimensions[ws.cell(1, index).column_letter].width = width
    for row in range(2, ws.max_row + 1):
        ws.cell(row, HEADERS.index("Match Score") + 1).number_format = "0"
        ws.cell(row, HEADERS.index("Evidence Confidence") + 1).number_format = "0%"
        for header in ("Date Posted", "Date Found", "Last Seen"):
            column = HEADERS.index(header) + 1
            ws.cell(row, column).number_format = "mm/dd/yyyy"
        for column in range(1, len(HEADERS) + 1):
            ws.cell(row, column).alignment = Alignment(vertical="top", wrap_text=False)
        for header in ("Authoritative URL", "Job URL", "Enrichment URL", "Resume Link"):
            column = HEADERS.index(header) + 1
            cell = ws.cell(row, column)
            if cell.value:
                cell.hyperlink = str(cell.value)
                cell.style = "Hyperlink"
    ws.conditional_formatting._cf_rules.clear()
    end = max(ws.max_row, 2)
    match_column = get_column_letter(HEADERS.index("Match Status") + 1)
    status_column = get_column_letter(HEADERS.index("Gecko Status") + 1)
    applied_column = get_column_letter(HEADERS.index("Applied") + 1)
    ws.conditional_formatting.add(
        f"A2:{end_column}{end}",
        FormulaRule(formula=[f'${match_column}2="Confirmed Strong Match"'], fill=PatternFill("solid", fgColor="E2F0D9")),
    )
    ws.conditional_formatting.add(
        f"A2:{end_column}{end}",
        FormulaRule(formula=[f'${match_column}2="Near Match"'], fill=PatternFill("solid", fgColor="FFF2CC")),
    )
    ws.conditional_formatting.add(
        f"A2:{end_column}{end}",
        FormulaRule(
            formula=[f'OR(${status_column}2="Ignored",${status_column}2="Rejected",${status_column}2="Applied",${applied_column}2<>"")'],
            fill=PatternFill("solid", fgColor="E7E6E6"), stopIfTrue=True,
        ),
    )


def _save_atomic(workbook, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix="job-scout-sync-", suffix=".xlsx", dir=path.parent, delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        workbook.save(temp_path)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def sync_job_scout(jobs: list[JobListing], tracker_path: str | Path) -> SyncSummary:
    """Upsert every known Scout job while preserving all other workbook content."""
    tracker_path = Path(tracker_path)
    if tracker_path.exists():
        workbook = load_workbook(tracker_path)
    else:
        workbook = Workbook()
        workbook.active.title = APPLICATION_SHEET
    tracker_preserved = APPLICATION_SHEET in workbook.sheetnames
    if not tracker_preserved:
        raise ValueError(f"Workbook must contain the existing {APPLICATION_SHEET!r} worksheet")
    ws = workbook[SHEET_NAME] if SHEET_NAME in workbook.sheetnames else workbook.create_sheet(SHEET_NAME)
    if ws.max_row == 1 and ws.cell(1, 1).value is None:
        for column, header in enumerate(HEADERS, 1):
            ws.cell(1, column, header)

    _migrate_schema(ws)

    rows = _existing_rows(ws)
    by_id = {str(row["Scout ID"]): row for row in rows if row.get("Scout ID") not in (None, "")}
    by_identity = {}
    for row in rows:
        for column in ("Job URL", "Enrichment URL"):
            identity = _identity(row.get(column))
            if identity:
                by_identity[identity] = row

    for job in jobs:
        existing = by_id.get(str(job.id))
        if existing is None:
            for url in (job.canonical_url, job.url, job.enriched_source_url):
                existing = by_identity.get(_identity(url))
                if existing is not None:
                    break
        updated = _job_row(job, existing)
        if existing is None:
            rows.append(updated)
            existing = rows[-1]
        else:
            existing.update(updated)
    rows.sort(key=_sort_key)
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    for record in rows:
        ws.append([record.get(header) for header in HEADERS])
    _style_sheet(ws)
    _save_atomic(workbook, tracker_path)

    return SyncSummary(
        rows=len(rows),
        confirmed=sum(row.get("Match Status") == "Confirmed Strong Match" for row in rows),
        provisional=sum(row.get("Match Status") == "Provisional 80+" for row in rows),
        near_matches=sum(row.get("Match Status") == "Near Match" for row in rows),
        tracker_preserved=tracker_preserved,
    )
