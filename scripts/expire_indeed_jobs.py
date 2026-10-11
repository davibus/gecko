"""Normalize existing expired Indeed statuses with targeted, verified Sheet writes."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "job-scout"))
from google_tracker import (  # noqa: E402
    GoogleTracker, INDEED_APPLICATION_HEADER, _a1, _col, is_expired_indeed,
)


def update_expired_rows(tracker: GoogleTracker, batch_size: int = 25) -> dict:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    before = tracker.scout(value_render_option="FORMULA")
    displayed = tracker.scout()
    if displayed.sheet_id != before.sheet_id or displayed.header_values != before.header_values:
        raise RuntimeError("Job Scout headers changed during expiration inventory")
    status_col = before.headers[INDEED_APPLICATION_HEADER]
    apply_col = before.headers["Apply?"]
    original = before.raw_rows or {}
    anchors = [(row, col) for row, raw in original.items()
               for col, value in enumerate(raw, 1)
               if isinstance(value, str) and value.lstrip().upper().startswith("=ARRAYFORMULA(")]
    formula_rows = dict(before.rows)
    writes: dict[tuple[int, int], str] = {}
    skipped: list[str] = []
    matched: list[int] = []
    for row, data in displayed.rows:
        status = data.get(INDEED_APPLICATION_HEADER)
        if not is_expired_indeed(status):
            continue
        matched.append(row)
        for col, field, desired in ((status_col, INDEED_APPLICATION_HEADER, "Expired"),
                                    (apply_col, "Apply?", "No")):
            current = formula_rows[row].get(field, "")
            if current == desired:
                continue
            cell = f"{_col(col)}{row} ({field})"
            if isinstance(current, str) and current.startswith("="):
                skipped.append(cell)
            elif any(row >= anchor_row and col >= anchor_col
                     for anchor_row, anchor_col in anchors):
                skipped.append(cell + " (possible ARRAYFORMULA output)")
            else:
                writes[(row, col)] = desired
    rows_updated: set[int] = set()
    for start in range(0, len(writes), batch_size):
        chunk = list(writes.items())[start:start + batch_size]
        entries = [{"range": _a1(before.title, f"{_col(col)}{row}"), "values": [[value]]}
                   for (row, col), value in chunk]
        tracker.api.values().batchUpdate(
            spreadsheetId=tracker.config.spreadsheet_id,
            body={"valueInputOption": "RAW", "data": entries},
        ).execute()
        rows_updated.update(row for (row, _), _ in chunk)
    after = tracker.scout(value_render_option="FORMULA")
    if after.sheet_id != before.sheet_id or after.header_values != before.header_values:
        raise RuntimeError("Job Scout headers changed during expiration update")
    actual = after.raw_rows or {}
    if set(actual) != set(original):
        raise RuntimeError("Job Scout row structure changed during expiration update")
    for row in original:
        left, right = original[row], actual[row]
        for col in range(1, max(len(left), len(right)) + 1):
            old = left[col - 1] if col <= len(left) else ""
            new = right[col - 1] if col <= len(right) else ""
            expected = writes.get((row, col), old)
            if new != expected:
                raise RuntimeError(f"Job Scout readback mismatch at {_col(col)}{row}: "
                                   f"expected {expected!r}, found {new!r}")
    return {"matching_rows": len(matched), "rows_updated": len(rows_updated),
            "cells_updated": len(writes), "updated_rows": sorted(rows_updated),
            "verified_cells": len(writes), "skipped_formula_cells": skipped,
            "unrelated_cells_preserved": True}


if __name__ == "__main__":
    print(json.dumps(update_expired_rows(GoogleTracker()), indent=2))
