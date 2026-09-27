"""Python client for Gecko's single Word-native validation entry point."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_word_native.ps1"


def validate_word_native(
    docx_path: str | Path,
    pdf_path: str | Path,
    result_path: str | Path | None = None,
    *,
    timeout: int = 360,
) -> dict:
    """Run the authoritative validator and return its native status record.

    A native-invalid two-page result is returned even though the PowerShell
    command exits nonzero. Infrastructure and handoff failures raise instead.
    """

    docx = Path(docx_path).resolve()
    pdf = Path(pdf_path).resolve()
    result = Path(result_path).resolve() if result_path else pdf.with_suffix(".validation.json")
    result.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(VALIDATOR),
        "-DocxPath",
        str(docx),
        "-PdfPath",
        str(pdf),
        "-ResultPath",
        str(result),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    record = None
    if result.is_file():
        try:
            record = json.loads(result.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            record = None
    if record and record.get("status") in {"native-valid", "native-invalid"}:
        return record
    detail = (completed.stderr or completed.stdout).strip()
    raise RuntimeError(detail or f"Word-native validator exited with code {completed.returncode}")
