"""Stage an existing, matched output resume for OpenClaw's managed upload API."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
import zipfile


def stage(resume: Path, output_root: Path, inbound_root: Path) -> dict:
    source = resume.resolve(strict=True)
    root = output_root.resolve(strict=True)
    if source.parent != root or source.suffix.lower() != ".docx":
        raise ValueError("Resume must be a DOCX directly inside output/resumes")
    data = source.read_bytes()
    if not data or len(data) >= 50 * 1024 * 1024:
        raise ValueError("Resume must be nonempty and smaller than 50 MiB")
    with zipfile.ZipFile(source) as document:
        if "word/document.xml" not in document.namelist():
            raise ValueError("File is not a Word document")
    digest = hashlib.sha256(data).hexdigest()
    inbound_root.mkdir(parents=True, exist_ok=True)
    destination = inbound_root / source.name
    if destination.is_symlink():
        raise ValueError("Refusing a symlink in managed inbound media")
    if destination.exists():
        if destination.read_bytes() != data:
            raise ValueError("A different staged file already has this name; preserve both and investigate")
    else:
        with destination.open("xb") as handle:
            handle.write(data)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise ValueError("Staged file verification failed")
    return {"source": str(source), "path": str(destination),
            "media_ref": "media://inbound/" + quote(source.name, safe=""),
            "filename": source.name, "bytes": len(data), "sha256": digest}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", type=Path, required=True,
                        help="Exact resume matched to the requested job; never guess by newest file")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    print(json.dumps(stage(args.resume, project / "output" / "resumes",
                           Path.home() / ".openclaw" / "media" / "inbound")))


if __name__ == "__main__":
    main()
