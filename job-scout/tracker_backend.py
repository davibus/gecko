"""Explicit tracker cutover; missing or invalid configuration never silently falls back."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "job-scout/preferences/tracker-backend.json"
DATABASE = ROOT / "job-scout/data/jobs.sqlite3"


def sqlite_enabled():
    override = os.getenv("GECKO_TRACKER_BACKEND")
    mode = override or (json.loads(CONFIG.read_text(encoding="utf-8"))["backend"] if CONFIG.exists() else "sheets")
    if mode not in {"sqlite", "sheets"}:
        raise RuntimeError("Unknown tracker backend; no tracker was opened")
    return mode == "sqlite"
