"""Read the current canonical Gecko master archive; no claims are introduced here."""

from __future__ import annotations

from pathlib import Path

MASTER_RESUME = (Path(__file__).resolve().parents[1] / "input" / "master-resume"
                 / "master-resume-v2.txt")


def extract_resume_text(path: str | Path) -> str:
    path = Path(path).resolve()
    if path != MASTER_RESUME.resolve():
        raise ValueError(f"Gecko evidence must come from the current master resume: {MASTER_RESUME}")
    try:
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise OSError(f"Required Gecko master resume is missing or unreadable: {path}") from error
    if not content.strip():
        raise ValueError(f"Required Gecko master resume is empty: {path}")
    return "\n".join(line.strip() for line in content.splitlines() if line.strip())
