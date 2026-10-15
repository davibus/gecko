"""Gecko on-demand pipeline, shared by the command and Windows Scheduled Task."""
from contextlib import contextmanager
from datetime import datetime
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STEPS = [
    ("Daily report", "daily_report.py", ["--dry-run"]),
    ("Daily discovery, tracker sync, and tailored resumes", "gecko_daily.py", ["--apply", "--sync-local"]),
    ("Final tracker and Cursor sync", "sync_gecko_local.py", []),
    ("Refresh Daily Tasks", "daily_report.py", ["--refresh-today"]),
]


@contextmanager
def run_lock():
    path = ROOT / "scratch/gecko-command/run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    folder = ROOT / "reports/gecko-command"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("America/Denver"))
    run_id = stamp.strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    status = dict(run_id=run_id, started_at=stamp.isoformat(), status="running", steps=[])
    status_path = folder / "latest.json"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    python = Path(sys.executable).with_name("python.exe")
    try:
        with run_lock(), (folder / f"{run_id}.log").open("w", encoding="utf-8") as log:
            for name, script, args in STEPS:
                status["current_step"] = name
                status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
                log.write(f"\nGecko: {name}\n")
                log.flush()
                result = subprocess.run([str(python), "-u", str(ROOT / "scripts" / script), *args],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW, check=False)
                status["steps"].append(dict(name=name, exit_code=result.returncode))
                if result.returncode:
                    status["status"] = "failed"
                    return result.returncode
            status["status"] = "complete"
            return 0
    except OSError as error:
        status["status"] = "blocked"
        status["error"] = f"{type(error).__name__}: {error}"
        return 1
    finally:
        status["updated_at"] = datetime.now(ZoneInfo("America/Denver")).isoformat()
        (folder / f"{run_id}.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
        if status["status"] != "blocked":
            status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
