"""Load the compact, source-verified candidate profile used for AI screening."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASTER_RESUME = ROOT / "input" / "master-resume" / "Dave-Call-Resume.txt"
DEFAULT_PROFILE = Path(__file__).resolve().parent / "preferences" / "candidate-profile.json"


def load_candidate_profile(path: str | Path | None = None) -> dict:
    """Return a compact profile only when it matches the current master archive."""
    if not MASTER_RESUME.is_file():
        raise FileNotFoundError(f"Required Gecko master resume could not be found: {MASTER_RESUME}")
    target = Path(path) if path else DEFAULT_PROFILE
    if not target.is_file():
        raise FileNotFoundError(f"Job Scout candidate profile could not be found: {target}")
    profile = json.loads(target.read_text(encoding="utf-8-sig"))
    actual = hashlib.sha256(MASTER_RESUME.read_bytes()).hexdigest()
    if profile.get("master_resume_sha256") != actual:
        raise ValueError(
            "The compact Job Scout candidate profile is stale; update it from the current "
            "master resume before running AI evaluation."
        )
    required = {
        "target_roles", "major_skills", "seniority", "industries",
        "strongest_accomplishments", "paid_media_ppc", "e_commerce",
        "analytics", "ai_automation", "leadership",
    }
    missing = required - profile.keys()
    if missing:
        raise ValueError("Candidate profile is missing: " + ", ".join(sorted(missing)))
    return profile


def compact_profile_text(profile: dict) -> str:
    """Serialize only screening fields, excluding maintenance metadata."""
    return json.dumps(
        {key: value for key, value in profile.items() if key != "master_resume_sha256"},
        ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    )


def candidate_profile_hash(profile: dict) -> str:
    return hashlib.sha256(compact_profile_text(profile).encode("utf-8")).hexdigest()
