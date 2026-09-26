"""Highlight pending Apply? selections in the existing Job Scout sheet."""

from __future__ import annotations

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


def main() -> int:
    tracker = GoogleTracker()
    tab = tracker.scout()
    required = {"Apply?", "Resume Created"}
    if not required <= tab.headers.keys():
        raise RuntimeError("Job Scout is missing Apply? or Resume Created")
    apply_column = tab.headers["Apply?"]
    resume_column = tab.headers["Resume Created"]
    formula = (f'=AND(LOWER(TRIM(${column_name(apply_column)}2))="yes",'
               f'UPPER(TRIM(${column_name(resume_column)}2))<>"X")')
    metadata = tracker.api.get(
        spreadsheetId=tracker.config.spreadsheet_id,
        fields="sheets(properties(sheetId,title,gridProperties(rowCount)),conditionalFormats)",
    ).execute()
    sheet = next(item for item in metadata["sheets"]
                 if item["properties"]["sheetId"] == tab.sheet_id)
    rule = {
        "ranges": [{"sheetId": tab.sheet_id, "startRowIndex": 1,
                    "startColumnIndex": apply_column - 1, "endColumnIndex": apply_column}],
        "booleanRule": {
            "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
            "format": {"backgroundColor": {"red": 1, "green": 0.92156863, "blue": 0.6}},
        },
    }
    existing = next((index for index, candidate in enumerate(sheet.get("conditionalFormats", []))
                     if any(value.get("userEnteredValue") == formula
                            for value in candidate.get("booleanRule", {}).get("condition", {}).get("values", []))),
                    None)
    if existing is not None:
        current = sheet["conditionalFormats"][existing]
        color = current.get("booleanRule", {}).get("format", {}).get("backgroundColor", {})
        target = rule["booleanRule"]["format"]["backgroundColor"]
        expected_range = dict(rule["ranges"][0],
                              endRowIndex=sheet["properties"]["gridProperties"]["rowCount"])
        if (current.get("ranges") == [expected_range] and
                all(abs(color.get(channel, 0) - value) < 0.00001
                    for channel, value in target.items())):
            print(f"Pending Apply? highlight already exists: {tracker.url()}")
            return 0
    request = ({"addConditionalFormatRule": {"index": 0, "rule": rule}}
               if existing is None else
               {"updateConditionalFormatRule": {"index": existing, "rule": rule}})
    tracker.api.batchUpdate(
        spreadsheetId=tracker.config.spreadsheet_id,
        body={"requests": [request]},
    ).execute()
    print(f"Pending Apply? highlight saved: {tracker.url()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
