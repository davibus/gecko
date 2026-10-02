"""Archive resumes for Job Scout rows explicitly marked Applied = x.

Preview is the default and performs no filesystem or Google Sheets writes. Pass
--apply only after reviewing the complete plan. The script resolves fields by
their exact headers and updates only the Resume Link cell after each safe move.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))

from google_tracker import Config, GoogleTracker  # noqa: E402


RESUME_DIR = (ROOT / "output" / "resumes").resolve()
APPLIED_DIR = (RESUME_DIR / "applied").resolve()


@dataclass(frozen=True)
class MovePlan:
    row: int
    company: str
    source: Path
    destination: Path
    old_uri: str
    new_uri: str


@dataclass(frozen=True)
class PlanIssue:
    row: int
    company: str
    reason: str


@dataclass(frozen=True)
class ArchivePlan:
    worksheet: str
    applied_column: int
    resume_link_column: int
    moves: tuple[MovePlan, ...]
    already_archived: tuple[int, ...]
    issues: tuple[PlanIssue, ...]


def _column_letter(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _a1(tab: str, cell: str) -> str:
    return "'" + tab.replace("'", "''") + "'!" + cell


def _normal(value: Any) -> str:
    return ("" if value is None else str(value)).strip().casefold()


def _path_from_file_uri(value: str) -> Path:
    parsed = urlsplit(value)
    if parsed.scheme.casefold() != "file" or parsed.netloc not in ("", "localhost"):
        raise ValueError("Resume Link is not a local file URI")
    local = unquote(parsed.path)
    if re.fullmatch(r"/[A-Za-z]:/.*", local):
        local = local[1:]
    if not local:
        raise ValueError("Resume Link has no local path")
    return Path(local).resolve()


def build_plan(
    tab,
    *,
    resume_dir: Path = RESUME_DIR,
    applied_dir: Path = APPLIED_DIR,
) -> ArchivePlan:
    """Build a complete, non-mutating archive plan from a live tracker tab."""
    required = {"Applied", "Resume Link"}
    missing = sorted(required - tab.headers.keys())
    if missing:
        raise RuntimeError(
            f"Google worksheet {tab.title!r} is missing required columns: "
            + ", ".join(missing)
        )
    applied_column = tab.headers["Applied"]
    link_column = tab.headers["Resume Link"]
    if applied_column != 8:
        raise RuntimeError(
            f"Applied is in Column {_column_letter(applied_column)}, not the expected Column H; "
            "no changes were made"
        )

    resume_dir = resume_dir.resolve()
    applied_dir = applied_dir.resolve()
    moves: list[MovePlan] = []
    already_archived: list[int] = []
    issues: list[PlanIssue] = []
    claimed_sources: dict[Path, int] = {}
    claimed_destinations: dict[Path, int] = {}

    for row, data in tab.rows:
        if _normal(data.get("Applied")) != "x":
            continue
        company = str(data.get("Company") or "").strip() or "(unknown company)"
        old_uri = str(data.get("Resume Link") or "").strip()
        if not old_uri:
            issues.append(PlanIssue(row, company, "Resume Link is blank"))
            continue
        try:
            source = _path_from_file_uri(old_uri)
        except ValueError as error:
            issues.append(PlanIssue(row, company, str(error)))
            continue
        if source.suffix.casefold() != ".docx":
            issues.append(PlanIssue(row, company, "Resume Link does not target a DOCX"))
            continue
        if source.parent == applied_dir:
            if source.is_file() and source.stat().st_size > 0:
                already_archived.append(row)
            else:
                issues.append(PlanIssue(row, company, "Archived Resume Link target is missing or empty"))
            continue
        if source.parent != resume_dir:
            issues.append(PlanIssue(row, company, "Resume Link target is outside output/resumes"))
            continue
        if not source.is_file() or source.stat().st_size <= 0:
            issues.append(PlanIssue(row, company, "Resume Link target is missing or empty"))
            continue
        destination = applied_dir / source.name
        if destination.exists():
            issues.append(PlanIssue(row, company, f"destination already exists: {destination}"))
            continue
        if source in claimed_sources:
            issues.append(PlanIssue(
                row, company, f"same resume is also referenced by row {claimed_sources[source]}"
            ))
            continue
        if destination in claimed_destinations:
            issues.append(PlanIssue(
                row, company, f"destination is also claimed by row {claimed_destinations[destination]}"
            ))
            continue
        claimed_sources[source] = row
        claimed_destinations[destination] = row
        moves.append(MovePlan(
            row=row,
            company=company,
            source=source,
            destination=destination,
            old_uri=old_uri,
            new_uri=destination.as_uri(),
        ))

    return ArchivePlan(
        worksheet=tab.title,
        applied_column=applied_column,
        resume_link_column=link_column,
        moves=tuple(moves),
        already_archived=tuple(already_archived),
        issues=tuple(issues),
    )


def _read_cell(tracker: GoogleTracker, worksheet: str, column: int, row: int) -> Any:
    cell = f"{_column_letter(column)}{row}"
    try:
        result = tracker.api.values().get(
            spreadsheetId=tracker.config.spreadsheet_id,
            range=_a1(worksheet, cell),
            valueRenderOption="FORMULA",
        ).execute()
    except Exception as error:
        raise RuntimeError(f"Cannot read Google Sheets {worksheet} {cell}: {error}") from error
    values = result.get("values", [])
    return values[0][0] if values and values[0] else ""


def _write_cell(
    tracker: GoogleTracker,
    worksheet: str,
    column: int,
    row: int,
    value: str,
) -> None:
    cell = f"{_column_letter(column)}{row}"
    try:
        tracker.api.values().update(
            spreadsheetId=tracker.config.spreadsheet_id,
            range=_a1(worksheet, cell),
            valueInputOption="RAW",
            body={"values": [[value]]},
        ).execute()
    except Exception as error:
        raise RuntimeError(f"Cannot update Google Sheets {worksheet} {cell}: {error}") from error


def _read_preflight_values(
    tracker: GoogleTracker,
    plan: ArchivePlan,
) -> dict[int, tuple[Any, Any]]:
    """Read every target's Applied and Resume Link values in one bounded request."""
    if not plan.moves:
        return {}
    first_row = min(item.row for item in plan.moves)
    last_row = max(item.row for item in plan.moves)
    first_column = min(plan.applied_column, plan.resume_link_column)
    last_column = max(plan.applied_column, plan.resume_link_column)
    cell_range = (
        f"{_column_letter(first_column)}{first_row}:"
        f"{_column_letter(last_column)}{last_row}"
    )
    try:
        result = tracker.api.values().get(
            spreadsheetId=tracker.config.spreadsheet_id,
            range=_a1(plan.worksheet, cell_range),
            valueRenderOption="FORMULA",
        ).execute()
    except Exception as error:
        raise RuntimeError(
            f"Cannot preflight Google Sheets {plan.worksheet} {cell_range}: {error}"
        ) from error
    rows = result.get("values", [])

    def value_at(row: int, column: int) -> Any:
        row_offset = row - first_row
        column_offset = column - first_column
        if row_offset < 0 or row_offset >= len(rows):
            return ""
        values = rows[row_offset]
        return values[column_offset] if column_offset < len(values) else ""

    return {
        item.row: (
            value_at(item.row, plan.applied_column),
            value_at(item.row, plan.resume_link_column),
        )
        for item in plan.moves
    }


def _preflight(tracker: GoogleTracker, plan: ArchivePlan) -> None:
    """Recheck every target before creating the directory or moving any file."""
    current_values = _read_preflight_values(tracker, plan)
    for item in plan.moves:
        applied, raw_link = current_values[item.row]
        link = str(raw_link or "").strip()
        if _normal(applied) != "x":
            raise RuntimeError(f"Row {item.row} is no longer Applied = x; no files were moved")
        if link != item.old_uri:
            raise RuntimeError(f"Row {item.row} Resume Link changed; no files were moved")
        if not item.source.is_file() or item.source.stat().st_size <= 0:
            raise RuntimeError(f"Row {item.row} source resume changed; no files were moved")
        if item.destination.exists():
            raise RuntimeError(f"Row {item.row} destination now exists; no files were moved")


def apply_plan(
    tracker: GoogleTracker,
    plan: ArchivePlan,
    *,
    applied_dir: Path = APPLIED_DIR,
) -> list[MovePlan]:
    """Apply a clean plan, verifying every filesystem and Sheet mutation."""
    if plan.issues:
        raise RuntimeError("Archive plan has unresolved issues; no changes were made")
    if not plan.moves:
        return []
    _preflight(tracker, plan)
    applied_dir.mkdir(parents=False, exist_ok=True)
    completed: list[MovePlan] = []

    for item in plan.moves:
        sheet_changed = False
        try:
            os.rename(item.source, item.destination)
            if item.source.exists() or not item.destination.is_file():
                raise RuntimeError("filesystem move could not be verified")
            _write_cell(
                tracker, plan.worksheet, plan.resume_link_column, item.row, item.new_uri
            )
            sheet_changed = True
            stored = str(_read_cell(
                tracker, plan.worksheet, plan.resume_link_column, item.row
            ) or "").strip()
            if stored != item.new_uri:
                raise RuntimeError("Resume Link read-back did not match the moved file")
            completed.append(item)
        except Exception as error:
            rollback_errors: list[str] = []
            link_is_old = False
            try:
                current = str(_read_cell(
                    tracker, plan.worksheet, plan.resume_link_column, item.row
                ) or "").strip()
                if current == item.new_uri or sheet_changed:
                    _write_cell(
                        tracker, plan.worksheet, plan.resume_link_column, item.row, item.old_uri
                    )
                    current = str(_read_cell(
                        tracker, plan.worksheet, plan.resume_link_column, item.row
                    ) or "").strip()
                link_is_old = current == item.old_uri
                if not link_is_old:
                    rollback_errors.append("could not restore the original Resume Link")
            except Exception as rollback_error:
                rollback_errors.append(f"Sheet rollback failed: {rollback_error}")

            if item.destination.exists() and link_is_old:
                try:
                    os.rename(item.destination, item.source)
                except Exception as rollback_error:
                    rollback_errors.append(f"file rollback failed: {rollback_error}")
            detail = f"Row {item.row} failed after {len(completed)} completed move(s): {error}"
            if rollback_errors:
                detail += "; " + "; ".join(rollback_errors)
            raise RuntimeError(detail) from error

    return completed


def ensure_clickable_links(
    tracker: GoogleTracker,
    tab,
    plan: ArchivePlan,
) -> int:
    """Attach native link metadata without changing visible Resume Link values."""
    rows_by_number = {row: data for row, data in tab.rows}
    targets = {item.row: item.new_uri for item in plan.moves}
    for row in plan.already_archived:
        targets[row] = str(rows_by_number[row].get("Resume Link") or "").strip()
    if not targets:
        return 0

    column_index = plan.resume_link_column - 1
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": tab.sheet_id,
                    "startRowIndex": row - 1,
                    "endRowIndex": row,
                    "startColumnIndex": column_index,
                    "endColumnIndex": column_index + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"link": {"uri": uri}},
                    },
                },
                "fields": "userEnteredFormat.textFormat.link",
            },
        }
        for row, uri in sorted(targets.items())
    ]
    try:
        tracker.api.batchUpdate(
            spreadsheetId=tracker.config.spreadsheet_id,
            body={"requests": requests},
        ).execute()
    except Exception as error:
        raise RuntimeError(f"Cannot make Resume Link cells clickable: {error}") from error

    first_row = min(targets)
    last_row = max(targets)
    letter = _column_letter(plan.resume_link_column)
    cell_range = f"{letter}{first_row}:{letter}{last_row}"
    try:
        result = tracker.api.get(
            spreadsheetId=tracker.config.spreadsheet_id,
            ranges=[_a1(plan.worksheet, cell_range)],
            includeGridData=True,
            fields=(
                "sheets(data(startRow,rowData(values("
                "effectiveValue,hyperlink,userEnteredFormat(textFormat(link))"
                "))))"
            ),
        ).execute()
    except Exception as error:
        raise RuntimeError(f"Cannot verify clickable Resume Link cells: {error}") from error
    data = result.get("sheets", [{}])[0].get("data", [{}])[0]
    start_row = int(data.get("startRow", first_row - 1)) + 1
    cells: dict[int, dict[str, Any]] = {}
    for offset, row_data in enumerate(data.get("rowData", [])):
        values = row_data.get("values", [])
        if values:
            cells[start_row + offset] = values[0]

    failed = []
    for row, uri in sorted(targets.items()):
        cell = cells.get(row, {})
        value = str(cell.get("effectiveValue", {}).get("stringValue", ""))
        formatted_link = str(
            cell.get("userEnteredFormat", {})
            .get("textFormat", {})
            .get("link", {})
            .get("uri", "")
        )
        automatic_link = str(cell.get("hyperlink") or "")
        if value != uri or uri not in {formatted_link, automatic_link}:
            failed.append(row)
    if failed:
        raise RuntimeError(
            "Clickable Resume Link read-back failed for row(s): "
            + ", ".join(str(row) for row in failed)
        )
    return len(targets)


def print_plan(plan: ArchivePlan, *, applying: bool) -> None:
    applied_letter = _column_letter(plan.applied_column)
    link_letter = _column_letter(plan.resume_link_column)
    mode = "APPLY" if applying else "PREVIEW (read-only)"
    print(f"Mode: {mode}")
    print(f"Worksheet: {plan.worksheet}")
    print(f"Applied header: Column {applied_letter}")
    print(f"Resume Link header: Column {link_letter}")
    if link_letter != "S":
        print("Note: Column S is not Resume Link and will not be changed.")
    print(f"Archive folder: {APPLIED_DIR}")
    print(f"Planned moves: {len(plan.moves)}")
    print(f"Already archived: {len(plan.already_archived)}")
    print(f"Issues: {len(plan.issues)}")
    for item in plan.moves:
        print(f"MOVE row {item.row} | {item.company}")
        print(f"  FROM {item.source}")
        print(f"  TO   {item.destination}")
        print(f"  SET  {plan.worksheet}!{link_letter}{item.row} = {item.new_uri}")
    for issue in plan.issues:
        print(f"ISSUE row {issue.row} | {issue.company} | {issue.reason}")
    if not applying:
        print("No folder, files, or Google Sheet cells were changed.")
        print("After reviewing, run again with --apply to execute this exact workflow.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Move Applied = x resumes into output/resumes/applied and update only "
            "their Resume Link cells. Preview-only unless --apply is supplied."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the planned file moves and verified Resume Link updates",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tracker = GoogleTracker(Config.from_environment())
    tab = tracker.scout(value_render_option="FORMULA")
    plan = build_plan(tab)
    print_plan(plan, applying=args.apply)
    if not args.apply:
        return 0 if not plan.issues else 2
    completed = apply_plan(tracker, plan)
    clickable = ensure_clickable_links(tracker, tab, plan)
    print(f"Completed and verified: {len(completed)} move(s).")
    print(f"Clickable Resume Links verified: {clickable}.")
    print(f"Google Sheet: {tracker.url()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
