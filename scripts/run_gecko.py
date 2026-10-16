"""Gecko on-demand pipeline, shared by the command and Windows Scheduled Task."""
from contextlib import contextmanager
import argparse
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
    ("Back up the updated tracker", "sync_gecko_local.py", []),
    ("Refresh daily results", "daily_report.py", ["--refresh-today"]),
    ("Export updated tracker to Google Sheets", "export_sqlite_tracker.py", []),
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


def main(job_ids=None):
    if job_ids is not None and (not job_ids or len(set(job_ids)) != len(job_ids) or any(type(i) is not int or i <= 0 for i in job_ids)):
        raise ValueError('Job IDs must be distinct positive integers')
    steps = STEPS
    if job_ids is not None:
        scoped = ['--ids', *map(str, sorted(job_ids))]
        steps = [
            ('Validate selected jobs and resume authorities', 'selected_daily.py', ['preflight', *scoped]),
            ('Daily report', 'daily_report.py', ['--dry-run']),
            ('Selected postings and tailored resumes', 'selected_daily.py', ['resumes', *scoped]),
            ('Employer responses for selected jobs', 'selected_daily.py', ['responses', *scoped]),
            *STEPS[2:],
        ]
    folder = ROOT / "reports/gecko-command"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("America/Denver"))
    run_id = stamp.strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"
    status = dict(run_id=run_id, started_at=stamp.isoformat(), status="running", steps=[])
    status_path = folder / "latest.json"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    if job_ids is not None:
        status['job_ids'] = sorted(job_ids)
        env['GECKO_ALLOWED_JOB_IDS'] = ','.join(map(str, sorted(job_ids)))
        env['GECKO_TRACKER_BACKEND'] = 'sqlite'
    python = Path(sys.executable).with_name("python.exe")
    try:
        with run_lock(), (folder / f"{run_id}.log").open("w", encoding="utf-8") as log:
            failure_code = 0
            for name, script, args in steps:
                status["current_step"] = name
                status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
                log.write(f"\nGecko: {name}\n")
                log.flush()
                result = subprocess.run([str(python), "-u", str(ROOT / "scripts" / script), *args],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW, check=False)
                status["steps"].append(dict(name=name, exit_code=result.returncode))
                if result.returncode:
                    failure_code = failure_code or result.returncode
                    # A failed preflight must stop all live work. Once daily work
                    # has run, refresh the tracker and report even after partial failure.
                    if script == 'selected_daily.py' and args[0] == 'preflight' or script == "daily_report.py" and args == ["--dry-run"]:
                        status["status"] = "failed"
                        return failure_code
            status["status"] = "failed" if failure_code else "complete"
            return failure_code
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-ids', type=int, nargs='+')
    raise SystemExit(main(parser.parse_args().job_ids))
