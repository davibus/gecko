"""Python client for Gecko's single Word-native validation entry point."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import os
import time
import uuid
import sys
from contextlib import contextmanager
from contextvars import ContextVar

_SESSION = ContextVar('gecko_word_session', default=None)


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_word_native.ps1"


class WordSession:
    """Use the existing bridge as a private sequential batch worker, started lazily."""
    def __init__(self):
        self.process = None
        self.directory = None
        self.log = None

    def root(self):
        # Sandbox callers retain the permanent interactive-user bridge path.
        if os.name != 'nt' or 'codexsandbox' in os.environ.get('USERNAME', '').lower():
            return None
        if self.process is not None:
            if self.process.poll() is not None:
                raise RuntimeError('Gecko-owned Word bridge exited; validation stopped.')
            return self.directory
        self.directory = ROOT / 'scratch/resume-word-sessions' / uuid.uuid4().hex
        self.directory.mkdir(parents=True)
        self.log = (self.directory / 'worker.log').open('w', encoding='utf-8')
        from silent_subprocess import windows_creationflags
        environment = dict(os.environ)
        environment['PATH'] = str(Path(sys.executable).parent) + os.pathsep + environment.get('PATH', '')
        self.process = subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive',
            '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass', '-File',
            str(ROOT / 'scripts/word_validation_bridge.ps1'), '-ScratchRoot', str(self.directory),
            '-PollSeconds', '1', '-SkipWordComProbe'], cwd=ROOT, stdout=self.log,
            stderr=subprocess.STDOUT, env=environment, creationflags=windows_creationflags())
        deadline = time.monotonic() + 20
        heartbeat = self.directory / 'word-validation-bridge-heartbeat.json'
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Gecko Word worker failed to start: ' + str(self.directory / 'worker.log'))
            if heartbeat.exists():
                return self.directory
            time.sleep(.1)
        raise RuntimeError('Gecko Word worker heartbeat timed out.')

    def close(self):
        if self.process is not None:
            (self.directory / 'stop-word-bridge').touch()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                # Never kill WINWORD by name, or touch any unrelated Word session.
                raise RuntimeError('Gecko Word worker did not exit cleanly; inspect ' + str(self.directory))
            finally:
                self.log.close()


@contextmanager
def word_session():
    if _SESSION.get() is not None:
        yield
        return
    session = WordSession()
    token = _SESSION.set(session)
    try:
        yield
    finally:
        try:
            session.close()
        finally:
            _SESSION.reset(token)


def active_bridge_root():
    session = _SESSION.get()
    return session.root() if session else None


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
    request_id = uuid.uuid4().hex
    result.unlink(missing_ok=True)
    pdf.unlink(missing_ok=True)
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
        '-RequestId', request_id,
    ]
    bridge_root = active_bridge_root()
    if bridge_root:
        command.extend(['-BridgeScratchRoot', str(bridge_root)])
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
    if (record and record.get('request_id') == request_id and pdf.is_file()
            and record.get("status") in {"native-valid", "native-invalid"}):
        return record
    detail = (completed.stderr or completed.stdout).strip()
    raise RuntimeError(detail or f"Word-native validator exited with code {completed.returncode}")
