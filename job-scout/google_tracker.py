"""Canonical Google Sheets tracker used by Gecko and Job Scout.

Only Gecko-owned cell values are written. Existing rows, user fields, formatting,
filters, validation, and sheet structure are never replaced during an upsert.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from normalize import canonicalize_url
from source_policy import is_jooble_candidate
from url_resolution import best_job_url

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_TAB = "Job Tracker"
SCOUT_TAB = "Job Scout"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SCOUT_LISTING_COLUMN = 18
SCOUT_RESUME_LINK_COLUMN = 19
NEW_SCOUT_ID_COLOR = {"red": 217 / 255, "green": 234 / 255, "blue": 211 / 255}
APPLICATION_FIELDS = ("Company", "Job Title", "Pay", "Job Number", "Job Link",
                      "Resume Link", "Date Created", "Source", "Date Found", "Status")
SCOUT_FIELDS = ("Scout ID", "Source", "Company", "Job Title", "Gecko Status",
                "Location", "Work Arrangement", "Employment Type", "Salary", "Date Posted",
                "Date Found", "Last Seen", "Job URL", "Resume Link")
PROTECTED_SCOUT_FIELDS = ("Apply?", "Resume Created", "Applied", "Contacted", "Response")
RETIRED_SCOUT_HEADERS = ("Website", "Enrichment URL", "URL Status", "Authoritative URL")


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


def apply_value(location: Any, work_arrangement: Any) -> str:
    """Derive Apply? from Gecko's normalized location and arrangement fields."""
    location_text = " ".join(str(location or "").split())
    arrangement_text = " ".join(str(work_arrangement or "").split())
    in_utah = bool(re.search(r"(?<![A-Za-z])(?:utah|ut)(?![A-Za-z])", location_text,
                             re.IGNORECASE))

    def is_remote(value: str) -> bool:
        if re.search(r"\b(?:not|isn't|is not)\s+(?:a\s+)?remote\b", value,
                     re.IGNORECASE):
            return False
        fully_remote = bool(re.search(
            r"\b(?:fully\s+remote|100\s*%\s+remote|remote\s+only)\b",
            value, re.IGNORECASE,
        ))
        if re.search(r"\bhybrid\b", value, re.IGNORECASE) and not fully_remote:
            return False
        return fully_remote or bool(re.search(
            r"\b(?:remote|work\s+from\s+home|work\s+from\s+anywhere)\b",
            value, re.IGNORECASE,
        ))

    return "Yes" if in_utah or is_remote(location_text) or is_remote(arrangement_text) else "No"


def marked(value: Any) -> bool:
    """An unchecked native checkbox is not a completed/manual mark."""
    return value not in (None, "", False) and _normal(value) not in {"false", "no"}


def _background_rgb(cell: dict[str, Any], format_name: str) -> dict[str, float] | None:
    cell_format = cell.get(format_name, {})
    style = cell_format.get("backgroundColorStyle", {})
    if style.get("themeColor") == "BACKGROUND":
        return None
    return style.get("rgbColor") or cell_format.get("backgroundColor")


def _is_gray(rgb: dict[str, float] | None) -> bool:
    if not rgb:
        return False
    channels = [float(rgb.get(name, 0)) for name in ("red", "green", "blue")]
    average = sum(channels) / len(channels)
    return max(channels) - min(channels) <= 0.03 and 0.65 <= average < 0.98


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
    header_values: tuple[str, ...] = ()
    raw_rows: dict[int, tuple[Any, ...]] | None = None


class GoogleTracker:
    def __init__(self, config: Config | None = None, service=None):
        self.config = config or Config.from_environment()
        self.service = service or build_service(self.config)
        self.api = self.service.spreadsheets()

    def tab(self, title: str, *, value_render_option: str = "UNFORMATTED_VALUE") -> Tab:
        try:
            metadata = self.api.get(spreadsheetId=self.config.spreadsheet_id,
                fields="sheets(properties(sheetId,title,gridProperties(rowCount)))").execute()
            matches = [item["properties"] for item in metadata.get("sheets", [])
                       if item["properties"]["title"] == title]
            if len(matches) != 1:
                raise RuntimeError(f"Google worksheet {title!r} was not found exactly once")
            values = self.api.values().get(spreadsheetId=self.config.spreadsheet_id,
                range=_a1(title, "A1:AZ"), valueRenderOption=value_render_option).execute().get("values", [])
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
                   matches[0].get("gridProperties", {}).get("rowCount", 1000),
                   tuple(names), {
                       number: tuple(values_row)
                       for number, values_row in enumerate(values[1:], 2)
                       if any(value not in (None, "") for value in values_row)
                   })

    def application(self) -> Tab:
        tab = self.tab(self.config.application_tab)
        required = {"Company", "Job Number", "Job Link", "Resume Link",
                    "Date Created", "Applied", "Contacted"}
        if not required <= tab.headers.keys() or not ({"Resume #", "Index"} & tab.headers.keys()):
            raise RuntimeError("Job Tracker is missing required application columns")
        return tab

    def scout(self, *, value_render_option: str = "UNFORMATTED_VALUE") -> Tab:
        tab = self.tab(self.config.scout_tab, value_render_option=value_render_option)
        if not {"Scout ID", "Job URL", "Gecko Status", "Resume Created", "Apply?"} <= tab.headers.keys():
            raise RuntimeError("Job Scout is missing required columns")
        # Column S is the permanent Resume Link column even if its header is blank
        # or a legacy sheet happens to call it something else. Keep the physical
        # column authoritative without inserting or moving any columns.
        tab.headers["Resume Link"] = SCOUT_RESUME_LINK_COLUMN
        for row, data in tab.rows:
            raw = (tab.raw_rows or {}).get(row, ())
            data["Resume Link"] = (
                raw[SCOUT_RESUME_LINK_COLUMN - 1]
                if len(raw) >= SCOUT_RESUME_LINK_COLUMN else ""
            )
        return tab

    def applied_response_rows(self) -> list[dict[str, Any]]:
        """Return applied Scout rows with optional application-tab context."""
        scout = self.scout()
        if "Response" not in scout.headers:
            raise RuntimeError("Job Scout is missing the Response column")

        try:
            application_rows = self.application().rows
        except RuntimeError as error:
            if "not found" not in str(error).casefold():
                raise
            application_rows = []

        by_url = {
            canonicalize_url(str(data.get("Job Link") or "")): data
            for _, data in application_rows if data.get("Job Link")
        }
        by_company_title = {
            (_normal(data.get("Company")), _normal(data.get("Job Title"))): data
            for _, data in application_rows
            if data.get("Company") and data.get("Job Title")
        }

        result = []
        advanced = {"applied", "contacted", "interview", "rejected", "offer"}
        for row_number, data in scout.rows:
            if not (marked(data.get("Applied")) or _normal(data.get("Gecko Status")) in advanced):
                continue
            application = by_url.get(canonicalize_url(str(data.get("Job URL") or "")))
            if application is None:
                application = by_company_title.get(
                    (_normal(data.get("Company")), _normal(data.get("Job Title")))
                )
            merged = dict(data)
            if application:
                for field in ("Job Number", "Date Created", "Job Link"):
                    if application.get(field) not in (None, ""):
                        merged[field] = application[field]
            merged["_row"] = row_number
            result.append(merged)
        return result

    def update_response_rows(self, updates: dict[int, str]) -> list[int]:
        """Update only nonidentical Response cells in one values batch."""
        if not updates:
            return []
        tab = self.scout()
        if "Response" not in tab.headers:
            raise RuntimeError("Job Scout is missing the Response column")
        current = {row: data for row, data in tab.rows}
        entries = []
        changed = []
        column = _col(tab.headers["Response"])
        for row, value in sorted(updates.items()):
            if row < 2 or row not in current:
                raise RuntimeError(f"Cannot update missing Job Scout row {row}")
            if current[row].get("Response", "") == value:
                continue
            entries.append({"range": _a1(tab.title, f"{column}{row}"), "values": [[value]]})
            changed.append(row)
        if not entries:
            return []
        try:
            self.api.values().batchUpdate(
                spreadsheetId=self.config.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": entries},
            ).execute()
        except Exception as error:
            raise RuntimeError(f"Cannot update Google Sheets Response cells: {error}") from error
        return changed

    def update_scout_notes(self, row: int, value: str) -> None:
        """Update only Notes on one existing Job Scout row."""
        tab = self.scout(value_render_option="FORMULA")
        if "Notes" not in tab.headers:
            raise RuntimeError("Job Scout is missing the Notes column")
        if not any(number == row for number, _ in tab.rows):
            raise RuntimeError(f"Cannot update missing Job Scout row {row}")
        self._write(tab, row, {"Notes": value})

    def delete_declined_scout_rows(self) -> list[int]:
        """Delete complete Job Scout rows whose Apply? or Notes value is exactly no."""
        tab = self.scout()
        if tab.headers.get("Apply?") != 6 or tab.headers.get("Notes") != 9:
            raise RuntimeError(
                "Job Scout cleanup requires Apply? in Column F and Notes in Column I; "
                "no rows were deleted"
            )
        rows = sorted((
            row for row, data in tab.rows
            if _normal(data.get("Apply?")) == "no" or _normal(data.get("Notes")) == "no"
        ), reverse=True)
        if not rows:
            return []
        requests = [{"deleteDimension": {"range": {
            "sheetId": tab.sheet_id,
            "dimension": "ROWS",
            "startIndex": row - 1,
            "endIndex": row,
        }}} for row in rows]
        try:
            self.api.batchUpdate(
                spreadsheetId=self.config.spreadsheet_id,
                body={"requests": requests},
            ).execute()
        except Exception as error:
            raise RuntimeError(f"Cannot delete declined Google Job Scout rows: {error}") from error

        remaining = [
            row for row, data in self.scout().rows
            if _normal(data.get("Apply?")) == "no" or _normal(data.get("Notes")) == "no"
        ]
        if remaining:
            raise RuntimeError(
                "Google Job Scout cleanup verification failed; declined rows remain: "
                + ", ".join(map(str, remaining))
            )
        return rows

    def migrate_scout_schema(self) -> dict[str, Any]:
        """Delete retired columns in place; a second run is a verified no-op."""
        tab = self.tab(self.config.scout_tab)
        targets = sorted(
            ((column, header) for header, column in tab.headers.items()
             if header in RETIRED_SCOUT_HEADERS),
            reverse=True,
        )
        if targets:
            requests = [{"deleteDimension": {"range": {
                "sheetId": tab.sheet_id, "dimension": "COLUMNS",
                "startIndex": column - 1, "endIndex": column,
            }}} for column, _ in targets]
            try:
                self.api.batchUpdate(
                    spreadsheetId=self.config.spreadsheet_id,
                    body={"requests": requests},
                ).execute()
            except Exception as error:
                raise RuntimeError(f"Cannot migrate Google Sheets {tab.title!r}: {error}") from error
        migrated = self.tab(self.config.scout_tab)
        remaining = sorted(set(migrated.headers) & set(RETIRED_SCOUT_HEADERS))
        if remaining:
            raise RuntimeError("Retired Job Scout headers remain: " + ", ".join(remaining))
        return {
            "deleted": [header for _, header in sorted(targets)],
            "headers": [name for name, _ in sorted(migrated.headers.items(), key=lambda item: item[1])],
        }

    def _write(self, tab: Tab, row: int, values: dict[str, Any]) -> None:
        entries = []
        current = next((record for number, record in tab.rows if number == row), {})
        for field, value in values.items():
            if field not in tab.headers:
                continue
            value = "" if value is None else value
            if current.get(field, "") == value:
                continue
            entries.append({"range": _a1(tab.title, f"{_col(tab.headers[field])}{row}"),
                            "values": [[value]]})
        if not entries:
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
        except Exception as error:
            raise RuntimeError(f"Cannot update Google Sheets {tab.title!r} row {row}: {error}") from error

    def _next_row(self, tab: Tab) -> int:
        return max((row for row, _ in tab.rows), default=1) + 1

    def update_manual_scout_row(self, tab: Tab, row: int, values: dict[str, Any]) -> None:
        """Update one existing intake row without changing structure or user-owned fields."""
        if row < 2 or not any(number == row for number, _ in tab.rows):
            raise RuntimeError(f"Cannot update missing Job Scout row {row}")
        allowed = set(SCOUT_FIELDS) | {"Notes"}
        unexpected = set(values) - allowed
        if unexpected:
            raise ValueError("Unsupported manual Job Scout fields: " + ", ".join(sorted(unexpected)))
        managed = dict(values)
        if {"Location", "Work Arrangement"} & managed.keys():
            current = next(data for number, data in tab.rows if number == row)
            managed["Apply?"] = apply_value(
                managed.get("Location", current.get("Location")),
                managed.get("Work Arrangement", current.get("Work Arrangement")),
            )
        self._write(tab, row, managed)

    def approve_manual_scout_row(
        self, row_number: int, *, company: str, title: str,
    ) -> None:
        """Fill a qualifying blank Apply? cell after re-verifying the exact row."""
        tab = self.scout(value_render_option="FORMULA")
        matches = [(row, data) for row, data in tab.rows if row == row_number]
        if len(matches) != 1:
            raise RuntimeError(f"Cannot locate Job Scout row {row_number}; no cell was changed")
        _, current = matches[0]
        if (_normal(current.get("Company")) != _normal(company)
                or _normal(current.get("Job Title")) != _normal(title)):
            raise RuntimeError("Manual Indeed row identity changed; Apply? was not updated")
        current_apply = str(current.get("Apply?") or "").strip()
        if current_apply:
            if _normal(current_apply) == "yes":
                return
            raise RuntimeError("Apply? now contains an explicit manual value; no cell was changed")
        if apply_value(
            current.get("Location"), current.get("Work Arrangement")
        ) != "Yes":
            raise RuntimeError("Job is not in Utah or remote; Apply? was not updated")
        self._write(tab, row_number, {"Apply?": "Yes"})

    def assign_manual_scout_id(
        self, row_number: int, scout_id: int, *, company: str, title: str,
    ) -> int:
        """Persist one positive, currently-unused ID on a verified blank-ID row."""
        if isinstance(scout_id, bool) or not isinstance(scout_id, int) or scout_id <= 0:
            raise ValueError("Scout ID must be a positive integer")
        tab = self.scout(value_render_option="FORMULA")
        existing_ids = [str(data.get("Scout ID") or "").strip()
                        for _, data in tab.rows if str(data.get("Scout ID") or "").strip()]
        if len(existing_ids) != len(set(existing_ids)):
            raise RuntimeError("Google Job Scout contains duplicate Scout ID values")
        matches = [(row, data) for row, data in tab.rows if row == row_number]
        if len(matches) != 1:
            raise RuntimeError(f"Cannot locate Job Scout row {row_number}; Scout ID was not assigned")
        _, current = matches[0]
        if (_normal(current.get("Company")) != _normal(company)
                or _normal(current.get("Job Title")) != _normal(title)):
            raise RuntimeError("Manual Indeed row identity changed; Scout ID was not assigned")
        current_id = str(current.get("Scout ID") or "").strip()
        if current_id:
            if current_id == str(scout_id):
                return scout_id
            raise RuntimeError("Manual Indeed row already has a different Scout ID")
        if str(scout_id) in existing_ids:
            raise RuntimeError(f"Scout ID {scout_id} is already in use")
        self._write(tab, row_number, {"Scout ID": scout_id})
        verified = self.scout(value_render_option="FORMULA")
        assigned = [(row, data) for row, data in verified.rows
                    if str(data.get("Scout ID") or "").strip() == str(scout_id)]
        if len(assigned) != 1 or assigned[0][0] != row_number:
            raise RuntimeError(f"Scout ID {scout_id} was not uniquely persisted")
        return scout_id

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
        added = updated = excluded = 0
        for job in jobs:
            url = best_job_url(job)
            if is_jooble_candidate(
                source=job.source,
                urls=(job.url, job.canonical_url, job.authoritative_url, url),
            ):
                excluded += 1
                continue
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
                "Apply?": apply_value(job.location, job.work_arrangement),
                "Location": job.location, "Work Arrangement": job.work_arrangement,
                "Employment Type": job.employment_type, "Salary": job.salary,
                "Date Posted": job.date_posted, "Date Found": job.date_discovered,
                "Last Seen": job.last_seen or job.date_discovered, "Job URL": url,
            }
            if existing:
                for stable in ("Scout ID", "Source", "Company", "Job Title", "Date Posted", "Date Found"):
                    values.pop(stable, None)
            managed_fields = set(SCOUT_FIELDS) | {"Apply?"}
            self._write(tab, row, {key: value for key, value in values.items()
                                   if key in managed_fields})
        return {"rows": len(tab.rows), "added": added, "updated": updated,
                "jooble_excluded": excluded}

    def highlight_scout_found_on(self, day: str) -> int:
        """Keep light green on Scout IDs first found today while preserving gray."""
        tab = self.scout()
        if "Date Found" not in tab.headers:
            raise RuntimeError("Job Scout is missing the Date Found column")
        column = tab.headers["Scout ID"] - 1
        populated = [(row, data) for row, data in tab.rows
                     if data.get("Scout ID") not in (None, "")]
        target_rows = {
            row for row, data in populated
            if str(data.get("Date Found") or "")[:10] == day
        }

        last_row = max((row for row, _ in populated), default=1)
        formats: dict[int, dict[str, Any]] = {}
        if last_row > 1:
            cell_range = f"{_col(column + 1)}2:{_col(column + 1)}{last_row}"
            try:
                grid = self.api.get(
                    spreadsheetId=self.config.spreadsheet_id,
                    ranges=[_a1(tab.title, cell_range)],
                    includeGridData=True,
                    fields=("sheets(data(startRow,rowData(values("
                            "userEnteredFormat(backgroundColor,backgroundColorStyle),"
                            "effectiveFormat(backgroundColor,backgroundColorStyle)))))"),
                ).execute()
                data = grid.get("sheets", [{}])[0].get("data", [{}])[0]
                start_row = int(data.get("startRow", 1)) + 1
                for offset, row_data in enumerate(data.get("rowData", [])):
                    values = row_data.get("values", [])
                    formats[start_row + offset] = values[0] if values else {}
            except Exception as error:
                raise RuntimeError(f"Cannot inspect Google Sheets Scout ID formatting: {error}") from error

        requests = []
        for row, _ in populated:
            cell = formats.get(row, {})
            effective_rgb = _background_rgb(cell, "effectiveFormat")
            if _is_gray(effective_rgb):
                continue
            user_rgb = _background_rgb(cell, "userEnteredFormat")
            if row in target_rows:
                cell_format = {"userEnteredFormat": {
                    "backgroundColorStyle": {"rgbColor": NEW_SCOUT_ID_COLOR},
                }}
            elif user_rgb:
                cell_format = {"userEnteredFormat": {
                    "backgroundColorStyle": {"themeColor": "BACKGROUND"},
                }}
            else:
                continue
            requests.append({"updateCells": {
                "range": {"sheetId": tab.sheet_id, "startRowIndex": row - 1, "endRowIndex": row,
                          "startColumnIndex": column, "endColumnIndex": column + 1},
                "rows": [{"values": [cell_format]}],
                "fields": "userEnteredFormat.backgroundColorStyle",
            }})
        if not requests:
            return len(target_rows)
        try:
            self.api.batchUpdate(spreadsheetId=self.config.spreadsheet_id,
                                 body={"requests": requests}).execute()
        except Exception as error:
            raise RuntimeError(f"Cannot highlight Google Sheets Scout IDs found on {day}: {error}") from error
        return len(target_rows)

    def mark_scout_resume(
        self, scout_id: int | None, resume_url: str, *, notes: str | None = None,
        require_approved: bool = True, row_number: int | None = None,
        allow_local: bool = False,
    ) -> int:
        """Atomically mark Column G and write the verified artifact location to Column S."""
        target = str(resume_url or "").strip()
        is_https = bool(re.fullmatch(r"https://[^\s]+", target, re.IGNORECASE))
        is_local = bool(
            re.fullmatch(r"file:///[A-Za-z]:/[^\r\n]+\.docx", target, re.IGNORECASE)
            or re.fullmatch(r"[A-Za-z]:[\\/][^\r\n]+\.docx", target, re.IGNORECASE)
        )
        if not is_https and not (allow_local and is_local):
            raise ValueError(
                "A persistent HTTPS URL is required unless this queue explicitly allows "
                "a verified local DOCX path"
            )
        tab = self.scout(value_render_option="FORMULA")
        if scout_id is None:
            matches = [(row, data) for row, data in tab.rows
                       if row == row_number and not str(data.get("Scout ID") or "").strip()]
        else:
            matches = [(row, data) for row, data in tab.rows
                       if str(data.get("Scout ID")) == str(scout_id)]
        if len(matches) != 1:
            identity = f"Scout ID {scout_id}" if scout_id is not None else f"blank-ID row {row_number}"
            raise RuntimeError(f"Cannot locate unique {identity} in Google Sheets")
        row, current = matches[0]
        if require_approved and _normal(current.get("Apply?")) != "yes":
            raise RuntimeError("Apply? is no longer Yes; no cell was changed")
        if tab.headers.get("Apply?") != 6 or tab.headers.get("Resume Created") != 7:
            raise RuntimeError("Apply? must be Column F and Resume Created must be Column G; no cell was changed")
        advanced = _normal(current.get("Gecko Status")) in {"applied", "contacted", "interview", "offer"}
        escaped = target.replace('"', '""')
        link_value = f'=HYPERLINK("{escaped}","Open Resume")' if is_https else target
        entries = []
        header_s = (tab.header_values[SCOUT_RESUME_LINK_COLUMN - 1]
                    if len(tab.header_values) >= SCOUT_RESUME_LINK_COLUMN else "")
        if not str(header_s).strip():
            entries.append({"range": _a1(tab.title, "S1"), "values": [["Resume Link"]]})
        if not advanced:
            entries.append({"range": _a1(tab.title, f"E{row}"), "values": [["Resume Created"]]})
        entries.extend([
            {"range": _a1(tab.title, f"S{row}"), "values": [[link_value]]},
            {"range": _a1(tab.title, f"G{row}"), "values": [["X"]]},
        ])
        if notes is not None and notes != str(current.get("Notes") or "").strip():
            if tab.headers.get("Notes") != 9:
                raise RuntimeError("Notes must be Column I; no cell was changed")
            entries.append({"range": _a1(tab.title, f"I{row}"), "values": [[notes]]})
        try:
            self.api.values().batchUpdate(
                spreadsheetId=self.config.spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": entries},
            ).execute()
        except Exception as error:
            raise RuntimeError(
                f"Cannot complete Google Sheets Job Scout row {row}: {error}"
            ) from error
        return row

    def remove_dead_scout(self, scout_ids: set[int]) -> set[int]:
        """Clear only Job Scout-managed values and verify those exact cells.

        Missing IDs are already clean, which makes interrupted/repeated cleanup
        idempotent. Manual columns are deliberately neither inspected nor changed.
        FORMULA rendering ensures a formula whose displayed result is blank is still
        cleared and cannot pass verification as an empty cell.
        """
        tab = self.scout(value_render_option="FORMULA")
        target_rows: dict[int, int] = {}
        write_errors: dict[int, str] = {}
        for row, data in tab.rows:
            try:
                scout_id = int(data.get("Scout ID"))
            except (TypeError, ValueError):
                continue
            if scout_id not in scout_ids:
                continue
            target_rows[row] = scout_id
            try:
                self._write(tab, row, {
                    field: "" for field in SCOUT_FIELDS if field in tab.headers
                })
            except RuntimeError as error:
                # Read back all managed cells below so the error identifies the
                # exact cells that remain instead of reporting only a row/ID.
                write_errors[row] = str(error)

        verified = self.scout(value_render_option="FORMULA")
        verified_rows = dict(verified.rows)
        failures = []
        for row, scout_id in target_rows.items():
            data = verified_rows.get(row, {})
            for field in SCOUT_FIELDS:
                if field not in verified.headers:
                    continue
                value = data.get(field, "")
                if value in (None, ""):
                    continue
                column = _col(verified.headers[field])
                reason = write_errors.get(row) or "write completed but the managed value remained"
                failures.append(
                    f"sheet={verified.title!r}, row={row}, column={column} ({field}), "
                    f"cell={column}{row}, remaining_value={value!r}, reason={reason}"
                )
        if failures:
            raise RuntimeError(
                "Google Sheets Job Scout cleanup left managed cells uncleared:\n- "
                + "\n- ".join(failures)
            )

        # Requested IDs not found on the sheet are already cleared. Returning the
        # full request set makes retries safe after a prior run cleared Sheets but
        # stopped before deleting the corresponding local record.
        return set(scout_ids)

    def url(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{quote(self.config.spreadsheet_id)}/edit"
