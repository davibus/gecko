"""Read the canonical Gecko resume; no claims are introduced here."""

from __future__ import annotations

from pathlib import Path


def extract_resume_text(path: str | Path) -> str:
    path = Path(path)
    try:
        import fitz
    except ImportError as error:
        raise RuntimeError("PyMuPDF is required to read Gecko's master resume (pip install pymupdf)") from error
    with fitz.open(path) as document:
        return "\n".join(page.get_text() for page in document)
