"""Set the Job Scout Apply? column from work arrangement and Utah location."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from google_tracker import GoogleTracker  # noqa: E402


def column_name(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(65 + remainder) + value
    return value


def apply_formula(headers: dict[str, int]) -> str:
    scout = column_name(headers["Scout ID"])
    location = column_name(headers["Location"])
    arrangement = column_name(headers["Work Arrangement"])
    return (
        f'=ARRAYFORMULA(IF(${scout}2:${scout}="","",IF((LOWER(TRIM(${arrangement}2:${arrangement}))="remote")+'
        f'REGEXMATCH(${location}2:${location}&"","(?i)(^|[^A-Za-z])(utah|ut)([^A-Za-z]|$)|'
        '(^|[^A-Za-z])(Salt Lake|Weber|Davis) County([^A-Za-z]|$)")>0,"yes","no")))'
    )


def main() -> int:
    tracker = GoogleTracker()
    tab = tracker.scout()
    required = {"Scout ID", "Apply?", "Location", "Work Arrangement"}
    if not required <= tab.headers.keys():
        raise RuntimeError("Job Scout is missing headers required for the Apply? formula")
    apply_column = tab.headers["Apply?"]
    apply_letter = column_name(apply_column)
    formula = apply_formula(tab.headers)
    values = tracker.api.values().get(
        spreadsheetId=tracker.config.spreadsheet_id,
        range=f"'{tab.title}'!{apply_letter}2:{apply_letter}{tab.grid_rows}",
        valueRenderOption="FORMULA",
    ).execute().get("values", [])
    if values and values[0] and values[0][0] == formula:
        print(f"Apply? formula already exists: {tracker.url()}")
        return 0
    if any(isinstance(row[0], str) and row[0].startswith("=") for row in values if row):
        raise RuntimeError("Apply? already contains a different formula; no cells were changed")

    backup = ROOT / "scratch" / "apply-formula"
    backup.mkdir(parents=True, exist_ok=True)
    snapshot = backup / f"apply-values-before-{datetime.now():%Y%m%d-%H%M%S}.json"
    snapshot.write_text(json.dumps({"sheet": tab.title, "column": apply_letter,
                                    "values": {str(row + 2): entry[0]
                                               for row, entry in enumerate(values) if entry}},
                                   indent=2), encoding="utf-8")

    tracker.api.batchUpdate(
        spreadsheetId=tracker.config.spreadsheet_id,
        body={"requests": [
            {"repeatCell": {"range": {"sheetId": tab.sheet_id, "startRowIndex": 1,
                                       "endRowIndex": tab.grid_rows,
                                       "startColumnIndex": apply_column - 1, "endColumnIndex": apply_column},
                            "cell": {}, "fields": "userEnteredValue"}},
            {"updateCells": {"range": {"sheetId": tab.sheet_id, "startRowIndex": 1,
                                        "endRowIndex": 2, "startColumnIndex": apply_column - 1,
                                        "endColumnIndex": apply_column},
                             "rows": [{"values": [{"userEnteredValue": {"formulaValue": formula}}]}],
                             "fields": "userEnteredValue"}},
        ]},
    ).execute()
    print(f"Apply? formula saved: {tracker.url()}\nPrevious values: {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
