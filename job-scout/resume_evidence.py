"""Read the current canonical Gecko master archive; no claims are introduced here."""

from __future__ import annotations

from pathlib import Path


def extract_resume_text(path: str | Path) -> str:
    path = Path(path)
    if path.name != "Dave-Call-Resume.txt":
        raise ValueError("Gecko evidence must come from Dave-Call-Resume.txt")
    return "\n".join(line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip())
