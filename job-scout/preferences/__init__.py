"""Load and validate Gecko's editable Job Scout preferences."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_PATH = Path(__file__).with_name("default.json")


def load_preferences(path: str | Path | None = None) -> dict:
    source = Path(path) if path else DEFAULT_PATH
    data = json.loads(source.read_text(encoding="utf-8"))
    required = {"target_roles", "preferred_locations", "excluded_seniority"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Preferences are missing: {', '.join(sorted(missing))}")
    return data
