"""Synchronize Gecko's two tracker worksheets with the Google Sheets API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable
from urllib.parse import quote, unquote, urlparse

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from normalize import canonicalize_url
from tracker_sync import (
    APPLICATION_SHEET,
    COLUMN_WIDTHS as SCOUT_COLUMN_WIDTHS,
    HEADERS as SCOUT_HEADERS,
    LEGACY_HEADERS as LEGACY_SCOUT_HEADERS,
    PREVIOUS_HEADERS as PREVIOUS_SCOUT_HEADERS,
    RESUME_LINK_HEADERS as RESUME_LINK_SCOUT_HEADERS,
    SOURCE_B_HEADERS as SOURCE_B_SCOUT_HEADERS,
    URL_STATUSLESS_HEADERS as URL_STATUSLESS_SCOUT_HEADERS,
    SHEET_NAME as SCOUT_SHEET,
    STATUS_RANK,
    _sort_key as scout_sort_key,
    _style_sheet as style_scout_xlsx,
)


APPLICATION_HEADERS = [
    "Resume #", "Company", "Job Title", "Pay", "Job Number", "Match Score",
    "Job Link", "Resume Link", "Date Created", "Applied", "Contacted", "Source",
    "Date Found", "Status",
]
APPLICATION_COLUMN_WIDTHS = [11, 28, 42, 31, 22, 14, 38, 48, 15, 12, 12, 18, 15, 18]
MANUAL_COLUMNS = ("Applied", "Contacted")
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
VALID_BACKENDS = {"xlsx", "google-sheets"}


@dataclass(frozen=True)
class GoogleSheetsConfig:
    spreadsheet_id: str
    credentials_file: Path

    @classmethod
    def from_environment(cls) -> "GoogleSheetsConfig":
        spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
        credentials_value = os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "").strip()
        missing = []
        if not spreadsheet_id:
            missing.append("GOOGLE_SHEETS_SPREADSHEET_ID")
        if not credentials_value:
            missing.append("GOOGLE_SHEETS_CREDENTIALS_FILE")
        if missing:
            raise ValueError("Missing Google Sheets configuration: " + ", ".join(missing))
        credentials_file = Path(os.path.expandvars(credentials_value)).expanduser()
        if not credentials_file.is_file():
            raise ValueError(f"Google Sheets credentials file does not exist: {credentials_file}")
        return cls(spreadsheet_id=spreadsheet_id, credentials_file=credentials_file)


@dataclass(frozen=True)
class GoogleSyncSummary:
    application_rows: int
    scout_rows: int
    spreadsheet_id: str


def load_environment_files(project_root: Path) -> None:
    """Load ignored local environment files without replacing process variables."""
    for path in (project_root / ".env.local", project_root / ".env.google-sheets.local"):
        if not path.is_file():
            continue
        for number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                raise ValueError(f"Invalid environment entry at {path.name}:{number}")
            name, value = line.split("=", 1)
            name = name.strip()
            if not name or not name.replace("_", "").isalnum() or name[0].isdigit():
                raise ValueError(f"Invalid environment variable name at {path.name}:{number}")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(name, value)


def tracker_backend() -> str:
    backend = os.getenv("TRACKER_BACKEND", "xlsx").strip().lower() or "xlsx"
    if backend not in VALID_BACKENDS:
        raise ValueError(f"TRACKER_BACKEND must be one of: {', '.join(sorted(VALID_BACKENDS))}")
    return backend


def build_sheets_service(config: GoogleSheetsConfig):
    """Create the official Google Sheets API client with narrow spreadsheet scope."""
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError(
            "Google Sheets dependencies are missing; install job-scout/requirements.txt"
        ) from error
    credentials = Credentials.from_service_account_file(
        str(config.credentials_file), scopes=[SHEETS_SCOPE]
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _sheet_range(title: str, columns: str) -> str:
    return f"'{title.replace(chr(39), chr(39) * 2)}'!A1:{columns}"


def _normalize_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%m/%d/%Y")
    if isinstance(value, date):
        return value.strftime("%m/%d/%Y")
    return value


def _records_from_values(values: list[list[Any]], headers: list[str], title: str) -> list[dict]:
    if not values:
        return []
    actual = list(values[0])
    while actual and actual[-1] in (None, ""):
        actual.pop()
    if len(set(actual)) != len(actual):
        raise ValueError(f"Google Sheet {title!r} contains duplicate column names")
    if title == SCOUT_SHEET:
        supported = (
            headers, LEGACY_SCOUT_HEADERS, SOURCE_B_SCOUT_HEADERS,
            RESUME_LINK_SCOUT_HEADERS, PREVIOUS_SCOUT_HEADERS, URL_STATUSLESS_SCOUT_HEADERS,
        )
        if not any(set(candidate).issubset(actual) for candidate in supported):
            raise ValueError(f"Google Sheet {title!r} columns do not match Gecko's required schema")
    elif not set(headers).issubset(actual):
        raise ValueError(f"Google Sheet {title!r} columns do not match Gecko's required schema")
    records = []
    for source_row in values[1:]:
        row = list(source_row) + [""] * (len(actual) - len(source_row))
        record = {header: row[index] for index, header in enumerate(actual)}
        if any(value not in (None, "") for value in record.values()):
            records.append(record)
    return records


def _output_headers(values: list[list[Any]], required: list[str]) -> list[str]:
    """Keep the user's column order and append newly managed columns if needed."""
    if not values:
        return list(required)
    actual = list(values[0])
    while actual and actual[-1] in (None, ""):
        actual.pop()
    return actual + [header for header in required if header not in actual]


def _records_from_xlsx(ws, headers: list[str]) -> list[dict]:
    actual = [ws.cell(1, column).value for column in range(1, ws.max_column + 1)]
    while actual and actual[-1] in (None, ""):
        actual.pop()
    source_headers = headers
    if ws.title == SCOUT_SHEET and actual in (
        LEGACY_SCOUT_HEADERS, SOURCE_B_SCOUT_HEADERS, RESUME_LINK_SCOUT_HEADERS,
        PREVIOUS_SCOUT_HEADERS, URL_STATUSLESS_SCOUT_HEADERS,
    ):
        source_headers = actual
    elif actual != headers:
        raise ValueError(f"XLSX worksheet {ws.title!r} columns do not match Gecko's required schema")
    return [
        {header: ws.cell(row, column).value for column, header in enumerate(source_headers, 1)}
        for row in range(2, ws.max_row + 1)
        if any(ws.cell(row, column).value not in (None, "") for column in range(1, len(headers) + 1))
    ]


def _canonical_identity(value: Any) -> str:
    return canonicalize_url(str(value or "")).lower()


def _copy_manual(target: dict, source: dict) -> None:
    for column in MANUAL_COLUMNS:
        if source.get(column) not in (None, ""):
            target[column] = source[column]


def _copy_custom(target: dict, source: dict, managed_headers: list[str]) -> None:
    """Carry user-owned columns with their row when sorted or upserted."""
    managed = set(managed_headers)
    for column, value in source.items():
        if column not in managed:
            target[column] = value


def _preserve_remote_url_verification(target: dict, source: dict) -> None:
    """Do not erase an existing verified URL with an older local backup."""
    local_status = str(target.get("URL Status") or "")
    remote_status = str(source.get("URL Status") or "")
    if remote_status and local_status in {"", "Not checked"}:
        target["URL Status"] = source.get("URL Status")
        target["Authoritative URL"] = source.get("Authoritative URL")


def _merge_scout_lifecycle(target: dict, source: dict) -> None:
    _copy_manual(target, source)
    candidates = [str(target.get("Gecko Status") or "New"), str(source.get("Gecko Status") or "New")]
    if target.get("Resume Created") or source.get("Resume Created"):
        candidates.append("Resume Created")
        target["Resume Created"] = "X"
    if target.get("Applied"):
        candidates.append("Applied")
    if target.get("Contacted"):
        candidates.append("Contacted")
    target["Gecko Status"] = max(candidates, key=lambda value: STATUS_RANK.get(value, 0))


def merge_application_rows(local_rows: list[dict], remote_rows: list[dict]) -> list[dict]:
    """Merge by Job Number while preserving manual Google Sheet fields and history."""
    merged = [dict(row) for row in local_rows]
    by_job = {
        str(row.get("Job Number") or "").strip(): row
        for row in merged if row.get("Job Number") not in (None, "")
    }
    for remote in remote_rows:
        key = str(remote.get("Job Number") or "").strip()
        existing = by_job.get(key) if key else None
        if existing is None:
            clone = dict(remote)
            merged.append(clone)
            if key:
                by_job[key] = clone
        else:
            _copy_custom(existing, remote, APPLICATION_HEADERS)
            _merge_scout_lifecycle(existing, remote)

    def rank(record: dict):
        value = record.get("Resume #")
        try:
            return (0, int(value))
        except (TypeError, ValueError):
            return (1, str(value or ""))

    merged.sort(key=rank)
    return merged


def merge_scout_rows(local_rows: list[dict], remote_rows: list[dict]) -> list[dict]:
    """Upsert by Scout ID or canonical URL without deleting historical records."""
    merged = [dict(row) for row in local_rows]
    by_id = {
        str(row.get("Scout ID")): row
        for row in merged if row.get("Scout ID") not in (None, "")
    }
    by_url: dict[str, dict] = {}
    for row in merged:
        for column in ("Job URL", "Enrichment URL"):
            identity = _canonical_identity(row.get(column))
            if identity:
                by_url[identity] = row
    for remote in remote_rows:
        existing = None
        scout_id = remote.get("Scout ID")
        if scout_id not in (None, ""):
            existing = by_id.get(str(scout_id))
        if existing is None:
            for column in ("Job URL", "Enrichment URL"):
                existing = by_url.get(_canonical_identity(remote.get(column)))
                if existing is not None:
                    break
        if existing is None:
            clone = dict(remote)
            merged.append(clone)
            if scout_id not in (None, ""):
                by_id[str(scout_id)] = clone
            for column in ("Job URL", "Enrichment URL"):
                identity = _canonical_identity(clone.get(column))
                if identity:
                    by_url[identity] = clone
        else:
            _copy_custom(existing, remote, SCOUT_HEADERS)
            _preserve_remote_url_verification(existing, remote)
            _copy_manual(existing, remote)
    merged.sort(key=scout_sort_key)
    return merged


def _text_key(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _resume_uri(value: Any, tracker_path: Path) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" in text:
        return text
    path = Path(text)
    if not path.is_absolute():
        path = tracker_path.parent / path
    return path.resolve().as_uri()


def attach_resume_links(application_rows: list[dict], scout_rows: list[dict], tracker_path: Path) -> None:
    """Backfill Scout resume links from matching application rows."""
    by_url = {}
    by_name = {}
    for application in application_rows:
        resume_link = _resume_uri(application.get("Resume Link"), tracker_path)
        if not resume_link:
            continue
        identity = _canonical_identity(application.get("Job Link"))
        if identity:
            by_url[identity] = resume_link
        name_key = (_text_key(application.get("Company")), _text_key(application.get("Job Title")))
        if all(name_key):
            by_name[name_key] = resume_link
    for scout in scout_rows:
        if scout.get("Resume Link"):
            scout["Resume Link"] = _resume_uri(scout["Resume Link"], tracker_path)
            continue
        resume_link = ""
        for column in ("Job URL", "Enrichment URL"):
            resume_link = by_url.get(_canonical_identity(scout.get(column)), "")
            if resume_link:
                break
        if not resume_link:
            resume_link = by_name.get(
                (_text_key(scout.get("Company")), _text_key(scout.get("Job Title"))), ""
            )
        if resume_link:
            scout["Resume Link"] = resume_link


def _values_from_records(headers: list[str], records: list[dict]) -> list[list[Any]]:
    return [headers] + [
        [_normalize_cell(record.get(header)) for header in headers]
        for record in records
    ]


def _metadata(api, spreadsheet_id: str) -> dict:
    return api.get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title,index,gridProperties),conditionalFormats)",
    ).execute()


def _ensure_required_sheets(api, values_api, spreadsheet_id: str) -> dict[str, dict]:
    metadata = _metadata(api, spreadsheet_id)
    sheets = metadata.get("sheets", [])
    by_title = {sheet["properties"]["title"]: sheet for sheet in sheets}
    requests = []

    if APPLICATION_SHEET not in by_title and SCOUT_SHEET not in by_title and len(sheets) == 1:
        only = sheets[0]
        only_title = only["properties"]["title"]
        current = values_api.get(
            spreadsheetId=spreadsheet_id,
            range=_sheet_range(only_title, "A"),
            valueRenderOption="UNFORMATTED_VALUE",
        ).execute().get("values", [])
        if not current:
            requests.append({
                "updateSheetProperties": {
                    "properties": {"sheetId": only["properties"]["sheetId"], "title": APPLICATION_SHEET},
                    "fields": "title",
                }
            })
            by_title[APPLICATION_SHEET] = only

    for title in (APPLICATION_SHEET, SCOUT_SHEET):
        if title not in by_title:
            requests.append({"addSheet": {"properties": {"title": title}}})
    if requests:
        api.batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
        metadata = _metadata(api, spreadsheet_id)
    return {sheet["properties"]["title"]: sheet for sheet in metadata.get("sheets", [])}


def _color(red: int, green: int, blue: int) -> dict[str, float]:
    return {"red": red / 255, "green": green / 255, "blue": blue / 255}


def _column_letter(index: int) -> str:
    """Return an A1 column name for a zero-based index."""
    value = index + 1
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _format_requests(sheet: dict, title: str, row_count: int, headers: list[str]) -> list[dict]:
    sheet_id = sheet["properties"]["sheetId"]
    column_count = len(headers)
    managed_headers = APPLICATION_HEADERS if title == APPLICATION_SHEET else SCOUT_HEADERS
    managed_widths = APPLICATION_COLUMN_WIDTHS if title == APPLICATION_SHEET else SCOUT_COLUMN_WIDTHS
    widths = dict(zip(managed_headers, managed_widths))
    requests: list[dict] = []
    for index in reversed(range(len(sheet.get("conditionalFormats", [])))):
        requests.append({"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": index}})
    requests.extend([
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                    "tabColor": _color(91, 155, 213),
                },
                "fields": "gridProperties.frozenRowCount,tabColor",
            }
        },
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": column_count},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": _color(31, 78, 120),
                    "textFormat": {"bold": True, "foregroundColor": _color(255, 255, 255)},
                    "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "CLIP",
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 30}, "fields": "pixelSize",
            }
        },
        {
            "setBasicFilter": {
                "filter": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": max(row_count, 1), "startColumnIndex": 0, "endColumnIndex": column_count}}
            }
        },
    ])
    for index, header in enumerate(headers):
        if header not in widths:
            continue
        width = widths[header]
        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": index, "endIndex": index + 1},
                "properties": {"pixelSize": max(70, int(width * 7))}, "fields": "pixelSize",
            }
        })
    if row_count > 1:
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": row_count, "startColumnIndex": 0, "endColumnIndex": column_count},
                "cell": {"userEnteredFormat": {"verticalAlignment": "TOP", "wrapStrategy": "CLIP"}},
                "fields": "userEnteredFormat(verticalAlignment,wrapStrategy)",
            }
        })
        date_headers = ("Date Created", "Date Found") if title == APPLICATION_SHEET else ("Date Posted", "Date Found", "Last Seen")
        for header in date_headers:
            column = headers.index(header)
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": row_count, "startColumnIndex": column, "endColumnIndex": column + 1},
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "mm/dd/yyyy"}}},
                    "fields": "userEnteredFormat.numberFormat",
                }
            })
        if title == SCOUT_SHEET:
            requests.extend([
                {
                    "repeatCell": {
                        "range": {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": row_count, "startColumnIndex": headers.index("Evidence Confidence"), "endColumnIndex": headers.index("Evidence Confidence") + 1},
                        "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
                        "fields": "userEnteredFormat.numberFormat",
                    }
                },
            ])

    def conditional(formula: str, rgb: tuple[int, int, int], index: int):
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": max(row_count, 2), "startColumnIndex": 0, "endColumnIndex": column_count}],
                    "booleanRule": {
                        "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                        "format": {"backgroundColor": _color(*rgb)},
                    },
                },
                "index": index,
            }
        })

    if title == SCOUT_SHEET:
        status = _column_letter(headers.index("Gecko Status"))
        applied = _column_letter(headers.index("Applied"))
        match = _column_letter(headers.index("Match Status"))
        conditional(f'=OR(${status}2="Applied",${status}2="Rejected",${status}2="Ignored",${applied}2<>"")', (231, 230, 230), 0)
        conditional(f'=${match}2="Confirmed Strong Match"', (226, 240, 217), 1)
        conditional(f'=${match}2="Near Match"', (255, 242, 204), 2)
    else:
        status = _column_letter(headers.index("Status"))
        applied = _column_letter(headers.index("Applied"))
        conditional(f'=OR(${status}2="applied",${status}2="rejected",${status}2="ignored",${applied}2<>"")', (231, 230, 230), 0)
    return requests


def _resume_link_format_requests(sheet_id: int, scout_rows: list[dict], headers: list[str] = SCOUT_HEADERS) -> list[dict]:
    """Apply hyperlinks that can launch local DOCX files from a browser sheet."""
    requests = []
    resume_column = headers.index("Resume Link")
    for row_index, record in enumerate(scout_rows, 1):
        link = str(record.get("Resume Link") or "").strip()
        if not link:
            continue
        # Google Sheets only activates ordinary web protocols. Route local files
        # through Gecko's localhost-only opener, which then hands the DOCX to Word.
        if link.lower().startswith("file:///"):
            filename = Path(unquote(urlparse(link).path)).name
            click_target = f"http://127.0.0.1:8765/open/{quote(filename)}"
        else:
            click_target = link
        requests.append({
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_index,
                    "endRowIndex": row_index + 1,
                    "startColumnIndex": resume_column,
                    "endColumnIndex": resume_column + 1,
                },
                "rows": [{
                    "values": [{
                        "userEnteredFormat": {
                            "textFormat": {
                                "foregroundColor": _color(17, 85, 204),
                                "underline": True,
                                "link": {"uri": click_target},
                            }
                        }
                    }]
                }],
                "fields": "userEnteredFormat.textFormat(foregroundColor,underline,link)",
            }
        })
    return requests


def _write_sheet(values_api, spreadsheet_id: str, title: str, end_column: str, values: list[list[Any]]) -> None:
    target = _sheet_range(title, end_column)
    values_api.clear(spreadsheetId=spreadsheet_id, range=target, body={}).execute()
    values_api.update(
        spreadsheetId=spreadsheet_id,
        range=f"'{title}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()


def _style_application_xlsx(ws) -> None:
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(vertical="center", wrap_text=False)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:N{max(ws.max_row, 1)}"
    for index, width in enumerate(APPLICATION_COLUMN_WIDTHS, 1):
        ws.column_dimensions[ws.cell(1, index).column_letter].width = width
    for row in range(2, ws.max_row + 1):
        for column in range(1, len(APPLICATION_HEADERS) + 1):
            ws.cell(row, column).alignment = Alignment(vertical="top", wrap_text=False)
        for column in (9, 13):
            if ws.cell(row, column).value:
                ws.cell(row, column).number_format = "mm/dd/yyyy"
        for column in (7, 8):
            cell = ws.cell(row, column)
            if cell.value:
                cell.hyperlink = str(cell.value)
                cell.style = "Hyperlink"


def _replace_xlsx_rows(ws, headers: list[str], records: list[dict]) -> None:
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    for record in records:
        ws.append([record.get(header) or None for header in headers])


def _save_xlsx_atomic(workbook, path: Path) -> None:
    with NamedTemporaryFile(prefix="google-sheets-backup-", suffix=".xlsx", dir=path.parent, delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        workbook.save(temp_path)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _sync_workbook_to_google(
    tracker_path: str | Path,
    *,
    config: GoogleSheetsConfig | None = None,
    service=None,
) -> GoogleSyncSummary:
    """Merge the XLSX backup with Google, preserving manual fields in both copies."""
    tracker_path = Path(tracker_path)
    if not tracker_path.is_file():
        raise ValueError(f"Tracker workbook does not exist: {tracker_path}")
    config = config or GoogleSheetsConfig.from_environment()
    service = service or build_sheets_service(config)
    api = service.spreadsheets()
    values_api = api.values()
    sheets = _ensure_required_sheets(api, values_api, config.spreadsheet_id)
    missing = [name for name in (APPLICATION_SHEET, SCOUT_SHEET) if name not in sheets]
    if missing:
        raise RuntimeError("Google Sheets API did not create required worksheets: " + ", ".join(missing))

    workbook = load_workbook(tracker_path)
    if APPLICATION_SHEET not in workbook.sheetnames or SCOUT_SHEET not in workbook.sheetnames:
        raise ValueError("XLSX tracker must contain both 'Job Tracker' and 'Job Scout' worksheets")
    local_application = _records_from_xlsx(workbook[APPLICATION_SHEET], APPLICATION_HEADERS)
    local_scout = _records_from_xlsx(workbook[SCOUT_SHEET], SCOUT_HEADERS)

    remote_application_values = values_api.get(
        spreadsheetId=config.spreadsheet_id,
        # Read the complete user-visible layout so reordered and custom columns
        # can be preserved during the merge.
        range=_sheet_range(APPLICATION_SHEET, "ZZ"),
        # Return formulas verbatim so user-owned custom columns survive the
        # clear-and-rewrite sync as formulas rather than frozen values.
        valueRenderOption="FORMULA",
        dateTimeRenderOption="FORMATTED_STRING",
    ).execute().get("values", [])
    remote_scout_values = values_api.get(
        spreadsheetId=config.spreadsheet_id,
        # Read beyond Gecko's managed columns so user-added columns can be
        # detected and ignored without being overwritten.
        range=_sheet_range(SCOUT_SHEET, "ZZ"),
        valueRenderOption="FORMULA",
        dateTimeRenderOption="FORMATTED_STRING",
    ).execute().get("values", [])
    remote_application = _records_from_values(remote_application_values, APPLICATION_HEADERS, APPLICATION_SHEET)
    remote_scout = _records_from_values(remote_scout_values, SCOUT_HEADERS, SCOUT_SHEET)
    application_headers = _output_headers(remote_application_values, APPLICATION_HEADERS)
    scout_headers = _output_headers(remote_scout_values, SCOUT_HEADERS)

    merged_application = merge_application_rows(local_application, remote_application)
    merged_scout = merge_scout_rows(local_scout, remote_scout)
    attach_resume_links(merged_application, merged_scout, tracker_path)
    application_values = _values_from_records(application_headers, merged_application)
    scout_values = _values_from_records(scout_headers, merged_scout)

    _write_sheet(
        values_api, config.spreadsheet_id, APPLICATION_SHEET,
        _column_letter(len(application_headers) - 1), application_values,
    )
    _write_sheet(
        values_api, config.spreadsheet_id, SCOUT_SHEET,
        _column_letter(len(scout_headers) - 1), scout_values,
    )

    format_requests = []
    format_requests.extend(_format_requests(sheets[APPLICATION_SHEET], APPLICATION_SHEET, len(application_values), application_headers))
    format_requests.extend(_format_requests(sheets[SCOUT_SHEET], SCOUT_SHEET, len(scout_values), scout_headers))
    format_requests.extend(
        _resume_link_format_requests(
            sheets[SCOUT_SHEET]["properties"]["sheetId"], merged_scout, scout_headers,
        )
    )
    api.batchUpdate(spreadsheetId=config.spreadsheet_id, body={"requests": format_requests}).execute()

    _replace_xlsx_rows(workbook[APPLICATION_SHEET], APPLICATION_HEADERS, merged_application)
    _replace_xlsx_rows(workbook[SCOUT_SHEET], SCOUT_HEADERS, merged_scout)
    _style_application_xlsx(workbook[APPLICATION_SHEET])
    style_scout_xlsx(workbook[SCOUT_SHEET])
    _save_xlsx_atomic(workbook, tracker_path)

    return GoogleSyncSummary(
        application_rows=len(merged_application),
        scout_rows=len(merged_scout),
        spreadsheet_id=config.spreadsheet_id,
    )


def sync_workbook_to_google(
    tracker_path: str | Path,
    *,
    config: GoogleSheetsConfig | None = None,
    service=None,
) -> GoogleSyncSummary:
    """Run synchronization and translate Google API failures into actionable errors."""
    try:
        return _sync_workbook_to_google(tracker_path, config=config, service=service)
    except Exception as error:
        if error.__class__.__module__.startswith("googleapiclient"):
            status = getattr(getattr(error, "resp", None), "status", None)
            if status == 404:
                raise RuntimeError(
                    "Google Sheet was not found or is not shared with the configured "
                    "service-account email; verify the Spreadsheet ID and Editor share"
                ) from error
            raise RuntimeError(f"Google Sheets API request failed: {error}") from error
        raise
