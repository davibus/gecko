"""Canonical Google Sheets tracker used by Gecko and Job Scout.

Only Gecko-owned cell values are written. Existing rows, user fields, formatting,
filters, validation, and sheet structure are never replaced during an upsert.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from normalize import canonicalize_url
from url_resolution import best_job_url, url_status_label

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_TAB = "Job Tracker"
SCOUT_TAB = "Job Scout"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
NEW_SCOUT_ID_COLOR = {"red": 217 / 255, "green": 234 / 255, "blue": 211 / 255}
APPLICATION_FIELDS = ("Company", "Job Title", "Pay", "Job Number", "Match Score", "Job Link",
                      "Resume Link", "Date Created", "Source", "Date Found", "Status")
SCOUT_FIELDS = ("Scout ID", "Source", "Company", "Job Title", "Gecko Status", "Match Score",
                "Evidence Confidence", "Match Status", "Location", "Work Arrangement",
                "Employment Type", "Salary", "Date Posted", "Date Found", "Last Seen",
                "Job URL", "Enrichment URL", "URL Status", "Authoritative URL")
PROTECTED_SCOUT_FIELDS = ("Apply?", "Resume Created", "Applied", "Contacted")
MATCH_SCORE_NUMBER_FORMAT = {"type": "NUMBER", "pattern": "0"}


def load_environment(project_root: Path = ROOT) -> None:
    for name in (".env.local", ".env.google-sheets.local"):
        path = project_root / name
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key.replace("_", "").isalnum() and not key[0].isdigit():
                os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Config:
    spreadsheet_id: str
    credentials_file: Path
    application_tab: str
    scout_tab: str

    @classmethod
    def from_environment(cls) -> "Config":
        load_environment()
        spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
        credentials = os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "").strip()
        if not spreadsheet_id or not credentials:
            raise RuntimeError("Google Sheets is required: set GOOGLE_SHEETS_SPREADSHEET_ID and GOOGLE_SHEETS_CREDENTIALS_FILE")
        path = Path(os.path.expandvars(credentials)).expanduser()
        if not path.is_file():
            raise RuntimeError(f"Google Sheets credentials file is unavailable: {path}")
        return cls(spreadsheet_id, path,
                   os.getenv("GOOGLE_SHEETS_TRACKER_TAB", APPLICATION_TAB).strip() or APPLICATION_TAB,
                   os.getenv("GOOGLE_SHEETS_SCOUT_TAB", SCOUT_TAB).strip() or SCOUT_TAB)


def build_service(config: Config):
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError("Google Sheets dependencies are missing; install job-scout/requirements.txt") from error
    credentials = Credentials.from_service_account_file(str(config.credentials_file), scopes=[SCOPE])
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _a1(tab: str, cell: str) -> str:
    return "'" + tab.replace("'", "''") + "'!" + cell


def _col(index: int) -> str:
    result = ""
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def _normal(value: Any) -> str:
    return ("" if value is None else str(value)).strip().casefold()


def normalize_match_score(value: Any) -> int:
    """Return a whole-number 0-100 score from supported score representations."""
    if isinstance(value, bool) or value in (None, ""):
        raise ValueError("Match Score must be a numeric value from 0 to 100")
    percentage_style = False
    if isinstance(value, int):
        number = float(value)
    elif isinstance(value, float):
        number = value
        percentage_style = 0 < value <= 1
    else:
        text = str(value).strip()
        ratio = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*/\s*100", text)
        percent = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*%", text)
        plain = re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text)
        if ratio:
            number = float(ratio.group(1))
        elif percent:
            number = float(percent.group(1))
        elif plain:
            number = float(text)
            percentage_style = "." in text and 0 < number <= 1
        else:
            raise ValueError(f"Invalid Match Score: {value!r}")
    if percentage_style:
        number *= 100
    if not math.isfinite(number) or not 0 <= number <= 100:
        raise ValueError(f"Match Score is outside 0-100: {value!r}")
    rounded = round(number)
    if not math.isclose(number, rounded, abs_tol=1e-9):
        raise ValueError(f"Match Score must resolve to a whole number: {value!r}")
    return int(rounded)


def marked(value: Any) -> bool:
    """An unchecked native checkbox is not a completed/manual mark."""
    return value not in (None, "", False) and _normal(value) not in {"false", "no"}


def job_key(record: dict[str, Any]) -> str:
    """Recover older numeric IDs from resume filenames when Sheets rounded them."""
    raw = record.get("Job Number")
    if isinstance(raw, (int, float)) or (isinstance(raw, str) and "e+" in raw.casefold()):
        link = unquote(urlsplit(str(record.get("Resume Link") or "")).path)
        suffix = link.rsplit("/", 1)[-1].rsplit("+", 1)[-1].removesuffix(".docx")
        if suffix and suffix.lstrip("-").isdigit():
            return _normal(suffix)
    return _normal(raw)


@dataclass
class Tab:
    title: str
    sheet_id: int
    headers: dict[str, int]
    rows: list[tuple[int, dict[str, Any]]]
    grid_rows: int


class GoogleTracker:
    def __init__(self, config: Config | None = None, service=None):
        self.config = config or Config.from_environment()
        self.service = service or build_service(self.config)
        self.api = self.service.spreadsheets()

    def tab(self, title: str) -> Tab:
        try:
            metadata = self.api.get(spreadsheetId=self.config.spreadsheet_id,
                fields="sheets(properties(sheetId,title,gridProperties(rowCount)))").execute()
            matches = [item["properties"] for item in metadata.get("sheets", [])
                       if item["properties"]["title"] == title]
            if len(matches) != 1:
                raise RuntimeError(f"Google worksheet {title!r} was not found exactly once")
            values = self.api.values().get(spreadsheetId=self.config.spreadsheet_id,
                range=_a1(title, "A1:AZ"), valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
        except Exception as error:
            raise RuntimeError(f"Cannot read Google Sheets {title!r}: {error}") from error
        if not values:
            raise RuntimeError(f"Google worksheet {title!r} has no header row")
        names = [str(value) for value in values[0]]
        if len(names) != len(set(names)):
            raise RuntimeError(f"Google worksheet {title!r} has duplicate headers")
        headers = {name: index for index, name in enumerate(names, 1) if name}
        rows = []
        for number, values_row in enumerate(values[1:], 2):
            if any(value not in (None, "") for value in values_row):
                rows.append((number, {name: values_row[index - 1] if index <= len(values_row) else ""
                                      for name, index in headers.items()}))
        return Tab(title, matches[0]["sheetId"], headers, rows,
                   matches[0].get("gridProperties", {}).get("rowCount", 1000))

    def application(self) -> Tab:
        tab = self.tab(self.config.application_tab)
        required = {"Company", "Job Number", "Match Score", "Job Link", "Resume Link",
                    "Date Created", "Applied", "Contacted"}
        if not required <= tab.headers.keys() or not ({"Resume #", "Index"} & tab.headers.keys()):
            raise RuntimeError("Job Tracker is missing required application columns")
        return tab

    def scout(self) -> Tab:
        tab = self.tab(self.config.scout_tab)
        if not {"Scout ID", "Job URL", "Gecko Status", "Resume Created", "Apply?"} <= tab.headers.keys():
            raise RuntimeError("Job Scout is missing required columns")
        return tab

    def _write(self, tab: Tab, row: int, values: dict[str, Any]) -> None:
        entries = []
        format_requests = []
        current = next((record for number, record in tab.rows if number == row), {})
        for field, value in values.items():
            if field not in tab.headers:
                continue
            value = "" if value is None else value
            if field == "Match Score" and value != "":
                value = normalize_match_score(value)
                column = tab.headers[field] - 1
                format_requests.append({"repeatCell": {
                    "range": {"sheetId": tab.sheet_id, "startRowIndex": row - 1,
                              "endRowIndex": row, "startColumnIndex": column,
                              "endColumnIndex": column + 1},
                    "cell": {"userEnteredFormat": {
                        "numberFormat": MATCH_SCORE_NUMBER_FORMAT}},
                    "fields": "userEnteredFormat.numberFormat",
                }})
            if current.get(field, "") == value:
                continue
            entries.append({"range": _a1(tab.title, f"{_col(tab.headers[field])}{row}"),
                            "values": [[value]]})
        if not entries and not format_requests:
            return
        try:
            if row > tab.grid_rows:
                self.api.batchUpdate(spreadsheetId=self.config.spreadsheet_id,
                    body={"requests": [{"appendDimension": {"sheetId": tab.sheet_id,
                        "dimension": "ROWS", "length": row - tab.grid_rows}}]}).execute()
                tab.grid_rows = row
            if entries:
                self.api.values().batchUpdate(spreadsheetId=self.config.spreadsheet_id,
                    body={"valueInputOption": "RAW", "data": entries}).execute()
            if format_requests:
                self.api.batchUpdate(spreadsheetId=self.config.spreadsheet_id,
                                     body={"requests": format_requests}).execute()
        except Exception as error:
            raise RuntimeError(f"Cannot update Google Sheets {tab.title!r} row {row}: {error}") from error

    def _match_score_cells(self, tab: Tab) -> list[tuple[int, dict[str, Any]]]:
        if "Match Score" not in tab.headers:
            raise RuntimeError(f"Google worksheet {tab.title!r} has no Match Score column")
        last_row = max((row for row, _ in tab.rows), default=1)
        column = _col(tab.headers["Match Score"])
        try:
            response = self.api.get(
                spreadsheetId=self.config.spreadsheet_id,
                ranges=[_a1(tab.title, f"{column}2:{column}{last_row}")],
                includeGridData=True,
                fields=("sheets(data(startRow,rowData(values(userEnteredValue,effectiveValue,"
                        "formattedValue,userEnteredFormat.numberFormat))))"),
            ).execute()
        except Exception as error:
            raise RuntimeError(f"Cannot inspect Google Sheets {tab.title!r} Match Score cells: {error}") from error
        cells = []
        for block in response.get("sheets", [{}])[0].get("data", []):
            start = block.get("startRow", 0)
            for offset, row_data in enumerate(block.get("rowData", [])):
                cell = (row_data.get("values") or [{}])[0]
                if cell.get("formattedValue", "") != "":
                    cells.append((start + offset + 1, cell))
        return cells

    @staticmethod
    def _score_cell_value(cell: dict[str, Any]) -> Any:
        for source in (cell.get("userEnteredValue", {}), cell.get("effectiveValue", {})):
            for key in ("numberValue", "stringValue"):
                if key in source:
                    return source[key]
        raise ValueError("Match Score cell has no usable numeric value")

    def normalize_match_scores(self, tab: Tab) -> dict[str, int]:
        """Normalize populated Match Score cells without touching blanks or other formatting."""
        cells = self._match_score_cells(tab)
        changes = []
        value_changes = format_changes = percent_displays = 0
        for row, cell in cells:
            score = normalize_match_score(self._score_cell_value(cell))
            entered = cell.get("userEnteredValue", {})
            value_ok = (set(entered) == {"numberValue"} and
                        float(entered["numberValue"]) == float(score))
            number_format = cell.get("userEnteredFormat", {}).get("numberFormat", {})
            format_ok = (number_format.get("type") == "NUMBER" and
                         number_format.get("pattern") == "0")
            if str(cell.get("formattedValue", "")).strip().endswith("%"):
                percent_displays += 1
            if not value_ok:
                value_changes += 1
            if not format_ok:
                format_changes += 1
            if not value_ok or not format_ok:
                changes.append((row, score))

        requests = []
        run = []
        for item in changes:
            if run and item[0] != run[-1][0] + 1:
                requests.append(self._score_update_request(tab, run))
                run = []
            run.append(item)
        if run:
            requests.append(self._score_update_request(tab, run))
        if requests:
            try:
                self.api.batchUpdate(spreadsheetId=self.config.spreadsheet_id,
                                     body={"requests": requests}).execute()
            except Exception as error:
                raise RuntimeError(f"Cannot normalize Google Sheets {tab.title!r} Match Scores: {error}") from error
        return {"populated": len(cells), "corrected": len(changes),
                "value_changes": value_changes, "format_changes": format_changes,
                "percent_displays": percent_displays}

    @staticmethod
    def _score_update_request(tab: Tab, run: list[tuple[int, int]]) -> dict[str, Any]:
        column = tab.headers["Match Score"] - 1
        return {"updateCells": {
            "range": {"sheetId": tab.sheet_id, "startRowIndex": run[0][0] - 1,
                      "endRowIndex": run[-1][0], "startColumnIndex": column,
                      "endColumnIndex": column + 1},
            "rows": [{"values": [{"userEnteredValue": {"numberValue": score},
                                    "userEnteredFormat": {
                                        "numberFormat": MATCH_SCORE_NUMBER_FORMAT}}]}
                     for _, score in run],
            "fields": "userEnteredValue,userEnteredFormat.numberFormat",
        }}

    def verify_match_scores(self, tab: Tab) -> int:
        cells = self._match_score_cells(tab)
        for row, cell in cells:
            entered = cell.get("userEnteredValue", {})
            number_format = cell.get("userEnteredFormat", {}).get("numberFormat", {})
            score = normalize_match_score(self._score_cell_value(cell))
            if (set(entered) != {"numberValue"} or entered["numberValue"] != score or
                    number_format != MATCH_SCORE_NUMBER_FORMAT or
                    cell.get("formattedValue") != str(score)):
                raise RuntimeError(f"Match Score verification failed at {tab.title}!{_col(tab.headers['Match Score'])}{row}")
        return len(cells)

    def _next_row(self, tab: Tab) -> int:
        return max((row for row, _ in tab.rows), default=1) + 1

    def _checkboxes(self, tab: Tab, row: int) -> None:
        requests = []
        for field in ("Applied", "Contacted"):
            if field not in tab.headers:
                continue
            column = tab.headers[field] - 1
            requests.append({"setDataValidation": {
                "range": {"sheetId": tab.sheet_id, "startRowIndex": row - 1, "endRowIndex": row,
                          "startColumnIndex": column, "endColumnIndex": column + 1},
                "rule": {"condition": {"type": "BOOLEAN"}, "strict": True, "showCustomUi": True}}})
        if requests:
            try:
                self.api.batchUpdate(spreadsheetId=self.config.spreadsheet_id,
                                     body={"requests": requests}).execute()
            except Exception as error:
                raise RuntimeError(f"Cannot initialize Google Sheets checkboxes at row {row}: {error}") from error

    def upsert_application(self, record: dict[str, Any]) -> tuple[int, bool]:
        """Find by Job Number, then update only managed fields or append once."""
        number = _normal(record.get("Job Number"))
        if not number:
            raise ValueError("Job Number is required")
        tab = self.application()
        matches = [row for row, data in tab.rows if job_key(data) == number]
        if len(matches) > 1:
            raise RuntimeError(f"Duplicate Job Number already exists in Google Sheets: {record['Job Number']}")
        managed = {field: record[field] for field in APPLICATION_FIELDS if field in record}
        if matches:
            existing = next(data for row, data in tab.rows if row == matches[0])
            managed.pop("Job Number", None)
            managed.pop("Date Created", None)
            for field in ("Pay", "Job Link", "Source", "Date Found"):
                if managed.get(field) in (None, ""):
                    managed.pop(field, None)
            if _normal(existing.get("Status")) in {"applied", "contacted", "interview", "offer"}:
                managed.pop("Status", None)
            self._write(tab, matches[0], managed)
            return matches[0], False
        row = self._next_row(tab)
        index_field = "Index" if "Index" in tab.headers else "Resume #"
        numeric = [int(data[index_field]) for _, data in tab.rows
                   if str(data.get(index_field, "")).strip().isdigit()]
        managed[index_field] = max(numeric, default=0) + 1
        self._write(tab, row, managed)
        # Initialize only this new row as native checkbox cells; existing user cells are untouched.
        self._checkboxes(tab, row)
        return row, True

    def find_application(self, job_number: str) -> tuple[int, dict] | None:
        tab = self.application()
        matches = [(row, data) for row, data in tab.rows
                   if job_key(data) == _normal(job_number)]
        if len(matches) > 1:
            raise RuntimeError(f"Duplicate Job Number exists in Google Sheets: {job_number}")
        return matches[0] if matches else None

    def upsert_scout(self, jobs: list, *, append_only: bool = False) -> dict[str, int]:
        tab = self.scout()
        ids = [str(data.get("Scout ID")) for _, data in tab.rows if data.get("Scout ID") not in (None, "")]
        if len(ids) != len(set(ids)):
            raise RuntimeError("Google Job Scout contains duplicate Scout ID values")
        by_id = {str(data.get("Scout ID")): row for row, data in tab.rows
                 if data.get("Scout ID") not in (None, "")}
        by_url = {canonicalize_url(str(data.get("Job URL") or "")): row for row, data in tab.rows
                  if data.get("Job URL")}
        added = updated = 0
        for job in jobs:
            url = best_job_url(job)
            row = by_id.get(str(job.id)) or by_url.get(canonicalize_url(url))
            if row and append_only:
                continue
            existing = next((data for number, data in tab.rows if number == row), {})
            labels = {"new": "New", "reviewing": "Reviewing", "selected": "Selected",
                      "resume-created": "Resume Created", "applied": "Applied", "contacted": "Contacted",
                      "interview": "Interview", "rejected": "Rejected", "ignored": "Ignored", "offer": "Offer"}
            ranks = {name: rank for rank, name in enumerate(labels.values())}
            incoming = labels.get(job.status, job.status.replace("-", " ").title())
            previous = str(existing.get("Gecko Status") or "New")
            status = incoming if ranks.get(incoming, 0) > ranks.get(previous, 0) else previous
            if not row:
                row = self._next_row(tab)
                tab.rows.append((row, {}))
                by_id[str(job.id)] = row
                if url:
                    by_url[canonicalize_url(url)] = row
                added += 1
            else:
                updated += 1
            values = {
                "Scout ID": job.id, "Source": job.source, "Company": job.company,
                "Job Title": job.title, "Gecko Status": status,
                "Match Score": job.match_score, "Evidence Confidence": job.evidence_confidence / 100,
                "Match Status": ("Confirmed Strong Match" if job.match_score >= 80 and
                                 job.evidence_confidence >= 65 and not job.provisional else
                                 "Provisional 80+" if job.match_score >= 80 else
                                 "Near Match" if job.match_score >= 70 else "Below Threshold"),
                "Location": job.location, "Work Arrangement": job.work_arrangement,
                "Employment Type": job.employment_type, "Salary": job.salary,
                "Date Posted": job.date_posted, "Date Found": job.date_discovered,
                "Last Seen": job.last_seen or job.date_discovered, "Job URL": url,
                "Enrichment URL": job.enriched_source_url,
                "URL Status": url_status_label(job), "Authoritative URL": job.authoritative_url,
            }
            if existing:
                for stable in ("Scout ID", "Source", "Company", "Job Title", "Date Posted", "Date Found"):
                    values.pop(stable, None)
            self._write(tab, row, {key: value for key, value in values.items() if key in SCOUT_FIELDS})
        return {"rows": len(tab.rows), "added": added, "updated": updated}

    def highlight_scout_found_on(self, day: str) -> int:
        """Color only the Scout ID cells for jobs first found on this date."""
        tab = self.scout()
        if "Date Found" not in tab.headers:
            raise RuntimeError("Job Scout is missing the Date Found column")
        rows = [row for row, data in tab.rows
                if data.get("Scout ID") not in (None, "") and str(data.get("Date Found") or "")[:10] == day]
        if not rows:
            return 0
        column = tab.headers["Scout ID"] - 1
        requests = [{"repeatCell": {
            "range": {"sheetId": tab.sheet_id, "startRowIndex": row - 1, "endRowIndex": row,
                      "startColumnIndex": column, "endColumnIndex": column + 1},
            "cell": {"userEnteredFormat": {"backgroundColor": NEW_SCOUT_ID_COLOR}},
            "fields": "userEnteredFormat.backgroundColor",
        }} for row in rows]
        try:
            self.api.batchUpdate(spreadsheetId=self.config.spreadsheet_id,
                                 body={"requests": requests}).execute()
        except Exception as error:
            raise RuntimeError(f"Cannot highlight Google Sheets Scout IDs found on {day}: {error}") from error
        return len(rows)

    def mark_scout_resume(self, scout_id: int, resume_url: str) -> None:
        tab = self.scout()
        matches = [row for row, data in tab.rows if str(data.get("Scout ID")) == str(scout_id)]
        if len(matches) != 1:
            raise RuntimeError(f"Cannot locate unique Scout ID {scout_id} in Google Sheets")
        current = next(data for row, data in tab.rows if row == matches[0])
        advanced = _normal(current.get("Gecko Status")) in {"applied", "contacted", "interview", "offer"}
        values = {"Resume Created": "X", "Resume Link": resume_url}
        if not advanced:
            values["Gecko Status"] = "Resume Created"
        self._write(tab, matches[0], values)

    def remove_dead_scout(self, scout_ids: set[int]) -> set[int]:
        tab = self.scout()
        removed = set()
        for row, data in tab.rows:
            try:
                scout_id = int(data.get("Scout ID"))
            except (TypeError, ValueError):
                continue
            if scout_id not in scout_ids:
                continue
            if any(marked(data.get(field)) for field in (*PROTECTED_SCOUT_FIELDS, "Resume Link")):
                continue
            if _normal(data.get("Gecko Status")) not in ("", "new", "reviewing"):
                continue
            custom = set(data) - set(SCOUT_FIELDS) - set(PROTECTED_SCOUT_FIELDS) - {"Resume Link"}
            if any(data.get(field) not in (None, "") for field in custom):
                continue
            self._write(tab, row, {field: "" for field in SCOUT_FIELDS if field in tab.headers})
            removed.add(scout_id)
        return removed

    def url(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{quote(self.config.spreadsheet_id)}/edit"
