"""Read the current canonical Gecko master archive; no claims are introduced here."""

from __future__ import annotations

from pathlib import Path
from resume_source import read_master_text

MASTER_RESUME = (Path(__file__).resolve().parents[1] / "input" / "master-resume"
                 / "master-resume-v4.docx")


def extract_resume_text(path: str | Path) -> str:
    path = Path(path).resolve()
    if path != MASTER_RESUME.resolve():
        raise ValueError(f"Gecko evidence must come from the current master resume: {MASTER_RESUME}")
    content = read_master_text(path)
    return "\n".join(line.strip() for line in content.splitlines() if line.strip())
