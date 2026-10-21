"""Synchronize the existing primary Sheet while the parent Gecko run holds its lock."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "job-scout"))
import sheet_sync

if __name__ == "__main__":
    if sheet_sync.enabled():
        try:
            print(json.dumps(sheet_sync.sync()))
        except Exception as error:
            sheet_sync.record_error(error)
            raise
