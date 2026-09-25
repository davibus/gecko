"""Set the Job Scout Apply? column from work arrangement and Utah location."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from google_tracker import GoogleTracker  # noqa: E402

FORMULA = (
    '=ARRAYFORMULA(IF($A2:$A="","",IF((LOWER(TRIM($N2:$N))="remote")+'
    'REGEXMATCH($M2:$M&"","(?i)(^|[^A-Za-z])(utah|ut)([^A-Za-z]|$)|'
    '(^|[^A-Za-z])(Salt Lake|Weber|Davis) County([^A-Za-z]|$)")>0,"yes","no")))'
)


def main() -> int:
    tracker = GoogleTracker()
    tab = tracker.scout()
    expected = {"Scout ID": 1, "Apply?": 6, "Location": 13, "Work Arrangement": 14}
    if any(tab.headers.get(name) != column for name, column in expected.items()):
        raise RuntimeError("Job Scout columns changed; no formula was written")
    values = tracker.api.values().get(
        spreadsheetId=tracker.config.spreadsheet_id,
        range=f"'{tab.title}'!F2:F{tab.grid_rows}",
        valueRenderOption="FORMULA",
    ).execute().get("values", [])
    if values and values[0] and values[0][0] == FORMULA:
        print(f"Apply? formula already exists: {tracker.url()}")
        return 0
    if any(isinstance(row[0], str) and row[0].startswith("=") for row in values if row):
        raise RuntimeError("Apply? already contains a different formula; no cells were changed")

    backup = ROOT / "scratch" / "apply-formula"
    backup.mkdir(parents=True, exist_ok=True)
    snapshot = backup / f"apply-values-before-{datetime.now():%Y%m%d-%H%M%S}.json"
    snapshot.write_text(json.dumps({"sheet": tab.title, "column": "F",
                                    "values": {str(row + 2): entry[0]
                                               for row, entry in enumerate(values) if entry}},
                                   indent=2), encoding="utf-8")

    tracker.api.batchUpdate(
        spreadsheetId=tracker.config.spreadsheet_id,
        body={"requests": [
            {"repeatCell": {"range": {"sheetId": tab.sheet_id, "startRowIndex": 1,
                                       "endRowIndex": tab.grid_rows,
                                       "startColumnIndex": 5, "endColumnIndex": 6},
                            "cell": {}, "fields": "userEnteredValue"}},
            {"updateCells": {"range": {"sheetId": tab.sheet_id, "startRowIndex": 1,
                                        "endRowIndex": 2, "startColumnIndex": 5,
                                        "endColumnIndex": 6},
                             "rows": [{"values": [{"userEnteredValue": {"formulaValue": FORMULA}}]}],
                             "fields": "userEnteredValue"}},
        ]},
    ).execute()
    print(f"Apply? formula saved: {tracker.url()}\nPrevious values: {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
