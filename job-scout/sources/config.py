"""Job source configuration with validated defaults and environment overrides."""

from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULT_PATH = Path(__file__).resolve().parents[1] / "preferences" / "job-sources.json"


def _boolean(value, default=True) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid provider enabled value: {value!r}")


def load_source_config(path: str | Path | None = None) -> dict:
    target = Path(path or os.getenv("JOB_SCOUT_SOURCES_CONFIG", "") or DEFAULT_PATH)
    if not target.is_file():
        raise ValueError(f"Job source configuration was not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("providers"), dict):
        raise ValueError("Job source configuration requires a providers object")
    providers = payload["providers"]
    payload["max_workers"] = int(os.getenv(
        "JOB_SCOUT_SOURCE_CONCURRENCY", payload.get("max_workers", 6)
    ))
    payload["max_results_per_source"] = int(os.getenv(
        "JOB_SCOUT_MAX_RESULTS_PER_SOURCE", payload.get("max_results_per_source", 50)
    ))
    if not 1 <= payload["max_workers"] <= 16:
        raise ValueError("Job source concurrency must be between 1 and 16")
    if payload["max_results_per_source"] < 1:
        raise ValueError("Job source result limit must be at least 1")
    for name, settings in providers.items():
        if not isinstance(settings, dict):
            raise ValueError(f"Provider {name!r} configuration must be an object")
        environment = os.getenv(f"JOB_SCOUT_{name.upper().replace('-', '_')}_ENABLED")
        settings["enabled"] = _boolean(environment, _boolean(settings.get("enabled"), True))
        limit = settings.get("max_results_per_run")
        if limit is not None and int(limit) < 1:
            raise ValueError(f"Provider {name!r} max_results_per_run must be at least 1")
    if providers.get("jooble", {}).get("enabled"):
        raise ValueError("Jooble cannot be enabled in Gecko Job Scout")
    return payload
