"""Run Gecko's existing daily workflow and record its outcome in Daily Run.

Run from Gecko Main: python scripts/gecko_daily.py --apply
The default is a dry run. Neither mode submits job applications.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from google_tracker import GoogleTracker  # noqa: E402
from tracker_schema import SCOUT_TAB  # noqa: E402
from daily_run_history import preflight_history, write_history  # noqa: E402
from inspect_tracker_schema import inventory  # noqa: E402

ZONE = ZoneInfo("America/Denver")
COUNT_LABELS = {
    "Jobs discovered": "Jobs Discovered",
    "New jobs added": "New Jobs Added",
    "Duplicates skipped": "Duplicates Skipped",
    "Manual Indeed rows processed": "Manual Indeed Rows Processed",
    "Manual Indeed duplicates flagged": "Manual Indeed Duplicates Flagged",
    "Manual Indeed retrieval failures": "Manual Indeed Retrieval Failures",
    "Declined rows preserved": "Declined Rows Preserved",
    "Resumes already existing": "Resumes Reused",
    "New Gecko resumes created": "Resumes Created",
    "Resume failures": "Resume Failures",
    "failures": "Workflow Failures",
    "Gmail emails checked": "Gmail Emails Checked",
    "Gmail responses matched": "Employer Responses Matched",
    "Response rows updated": "Response Rows Updated",
}


def counts_from_output(output: str) -> dict[str, int | str]:
    """Use only the existing daily command's labeled, final summary lines."""
    result: dict[str, int | str] = {name: "Unavailable" for name in COUNT_LABELS.values()}
    for line in output.splitlines():
        if line.startswith('Firecrawl efficiency: '):
            payload = json.loads(line.removeprefix('Firecrawl efficiency: '))
            for key, value in payload.items():
                result['Firecrawl ' + key.replace('_', ' ')] = (
                    json.dumps(value, sort_keys=True) if isinstance(value, (dict, list))
                    else 'Unavailable' if value is None else value)
        for label, name in COUNT_LABELS.items():
            match = re.fullmatch(rf"{re.escape(label)}:\s*(\d+)", line.strip())
            if match:
                result[name] = int(match.group(1))
    decoder = json.JSONDecoder()
    for match in re.finditer(r"(?m)^\{", output):
        try:
            payload, _ = decoder.raw_decode(output[match.start():])
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if "source_counts" in payload and "newly_discovered" in payload:
            result["Jobs Discovered"] = payload.get("fetched", "Unavailable")
            result["Duplicates Skipped"] = payload.get("duplicates", "Unavailable")
            result["New Jobs Added"] = payload.get("newly_discovered", "Unavailable")
            result["Provider Failures"] = len(payload.get("source_errors") or {})
            result["Indeed Jobs Found"] = (payload.get("source_counts") or {}).get("indeed", 0)
        if isinstance(payload.get("job_scout_worksheet"), dict):
            result["New Jobs Added"] = payload["job_scout_worksheet"].get(
                "added", result["New Jobs Added"])
    return result


def safe_error(exc: Exception) -> str:
    """Keep API errors and local credential paths out of the public audit."""
    message = str(exc)
    if isinstance(exc, RuntimeError) and message.startswith((
        "Daily Run tab is missing", "Configured job ledger differs",
        "Run ID already exists", "Authoritative master resume is missing",
        "Authoritative resume model is missing",
    )):
        return message
    if "missing header for 'Apply?'" in message or "ambiguous header for 'Apply?'" in message:
        return "Job List approval header is missing or ambiguous; daily workflow stopped"
    return f"{type(exc).__name__}: daily operation failed; inspect the configured services"


def validate_live_targets(tracker: GoogleTracker, run_id: str, run_date: str,
                          resume_ids: set[int] | None = None) -> dict:
    """Read the current workbook, destination, and canonical queue before writes."""
    if getattr(tracker, 'backend', '') == 'sqlite':
        from generate_apply_queue import read_queue, validate_requested_ids
        if resume_ids is not None:
            validate_requested_ids(tracker,resume_ids)
        queue = read_queue(tracker,eligible_scout_ids=resume_ids,auto_approve_geographic=True)
        for name in ('master-resume-v4.docx','MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf'):
            if not (ROOT/'input/master-resume'/name).is_file():
                raise RuntimeError('Authoritative resume input is missing')
        return {'backend':'sqlite','queue_preflight':{'eligible':len(queue.pending),'already_created':len(queue.already_created)}}
    result = inventory(tracker)
    if result["validation"]["daily_run_present"] is not True:
        raise RuntimeError("Daily Run tab is missing; no live workflow was started")
    if tracker.config.scout_tab != SCOUT_TAB:
        raise RuntimeError("Configured job ledger differs from the verified Gecko Main tab")
    fields = {"Run Date": run_date, "Run ID": run_id, "Jobs by Source": {}}
    _, _, existing = preflight_history(tracker, fields)
    if existing:
        raise RuntimeError("Run ID already exists in Daily Run; choose a new run ID")
    from generate_apply_queue import read_queue, validate_requested_ids
    if resume_ids is not None:
        result["resume_id_rows"] = validate_requested_ids(tracker, resume_ids)
    queue = read_queue(tracker, eligible_scout_ids=resume_ids,
                       auto_approve_geographic=True)
    if not (ROOT / "input/master-resume/master-resume-v4.docx").is_file():
        raise RuntimeError("Authoritative master resume is missing")
    if not (ROOT / "input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf").is_file():
        raise RuntimeError("Authoritative resume model is missing")
    result["queue_preflight"] = {
        "eligible": len(queue.pending),
        "already_created": len(queue.already_created),
        "cost_excluded": len(queue.cost_excluded),
        "rejected_excluded": len(queue.rejected_excluded),
        "duplicate_excluded": len(queue.duplicate_excluded),
    }
    return result


def source_counts(tracker: GoogleTracker) -> dict[str, int]:
    counts = Counter()
    for _, row in tracker.scout().rows:
        counts[str(row.get("Source") or "(blank)").strip()] += 1
    return dict(counts)


def history_fields(run_id: str, run_date: str, counts: dict, sources: dict,
                   *, dry_run: bool, exit_code: int, error: str = "",
                   attention_counts: dict | None = None) -> dict:
    attention = []
    attention_counts = attention_counts or {}
    if counts.get("Manual Indeed Retrieval Failures", 0) not in (0, "Unavailable"):
        attention.append("Manual Indeed retrieval failures")
    if counts.get("Resume Failures", 0) not in (0, "Unavailable"):
        attention.append("Resume generation failures")
    if counts.get("Gmail Emails Checked") == "Unavailable" and not dry_run:
        attention.append("Gmail check unavailable or failed")
    if counts.get("Workflow Failures", 0) not in (0, "Unavailable"):
        attention.append("Workflow or provider failures")
    if counts.get("Provider Failures", 0) not in (0, "Unavailable"):
        attention.append("Provider failures")
    if counts.get("Declined Rows Preserved", 0) not in (0, "Unavailable"):
        attention.append("Declined rows retained to protect formulas")
    if attention_counts.get("completed_without_link"):
        attention.append(f"{attention_counts['completed_without_link']} completed rows lack a resume link")
    if attention_counts.get("missing_identity"):
        attention.append(f"{attention_counts['missing_identity']} queue rows lack a stable identity")
    if error or exit_code:
        attention.append("Daily workflow failed; inspect the local audit")
    return {
        "Run Date": run_date, "Run ID": run_id,
        "Mode": "Dry Run" if dry_run else "Apply",
        "Overall Status": "FAIL" if error or exit_code else "PASS",
        **counts,
        "Errors": 1 if error or exit_code else 0,
        "Error Details": error or "None",
        "Attention Items": "; ".join(attention) or "None",
        "Applications Submitted": 0,
        "Jobs by Source": sources,
    }


def run_streamed(command, *, timeout, **kwargs):
    """Keep the live run log current while retaining output for the audit parser."""
    for key in ("capture_output", "text", "errors", "check"):
        kwargs.pop(key, None)
    chunks = []
    with tempfile.TemporaryDirectory() as directory, \
            open(Path(directory) / "stream.log", "wb") as output, \
            open(Path(directory) / "stream.log", "rb") as reader:
        with subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, **kwargs) as child:
            started = time.monotonic()
            position = 0
            while True:
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    if time.monotonic() - started >= timeout:
                        child.kill()
                        child.wait()
                        raise subprocess.TimeoutExpired(command, timeout)
                reader.seek(position)
                chunk = reader.read()
                position += len(chunk)
                if chunk:
                    chunks.append(chunk)
                    print(chunk.decode("utf-8", errors="backslashreplace"), end="", flush=True)
                if child.poll() is not None:
                    break
    return subprocess.CompletedProcess(command, child.returncode,
        b"".join(chunks).decode("utf-8", errors="backslashreplace"), "")


def run(*, apply: bool, resume_ids: set[int] | None = None,
        sync_local: bool = False,
        runner=run_streamed, tracker_factory=GoogleTracker,
        audit_root: Path | None = None) -> tuple[int, dict]:
    started = datetime.now(ZONE)
    run_date = started.date().isoformat()
    run_id = f"{started:%Y%m%dT%H%M%S}-{uuid4().hex[:10]}"
    report = {"run_id": run_id, "run_date": run_date,
              "mode": "apply" if apply else "dry-run", "started_at": started.isoformat(),
              "resume_ids": sorted(resume_ids) if resume_ids is not None else None,
              "preflight": {}, "counts": {}, "errors": [], "attention": [],
              "daily_run_written": False, "daily_run_row": None}
    root = audit_root or ROOT / "reports/daily"
    exit_code = 1
    output = ""
    try:
        tracker = tracker_factory()
        if apply:
            report["preflight"] = validate_live_targets(tracker, run_id, run_date,
                                                        resume_ids)
        else:
            report["preflight"] = inventory(tracker)
            from generate_apply_queue import read_queue, validate_requested_ids
            if resume_ids is not None:
                report["preflight"]["resume_id_rows"] = validate_requested_ids(
                    tracker, resume_ids)
            queue = read_queue(tracker, eligible_scout_ids=resume_ids,
                               auto_approve_geographic=True)
            report["preflight"]["queue_preflight"] = {
                "eligible": len(queue.pending), "already_created": len(queue.already_created),
                "cost_excluded": len(queue.cost_excluded),
                "rejected_excluded": len(queue.rejected_excluded),
                "duplicate_excluded": len(queue.duplicate_excluded),
            }
        command = [sys.executable, str(ROOT / "job-scout/scout.py"), "daily"]
        if sync_local:
            command.append("--sync-local")
        if resume_ids is not None:
            command.extend(["--resume-ids", *map(str, sorted(resume_ids))])
        if not apply:
            command.append("--dry-run")
        completed = runner(command, cwd=ROOT, capture_output=True, text=True,
                           errors="backslashreplace", check=False, timeout=86400 if sync_local else 1800,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        exit_code = completed.returncode
        report["counts"] = counts_from_output(completed.stdout or "")
        if exit_code:
            report["errors"].append(f"Daily workflow exited with code {exit_code}")
        if "Daily Job Scout complete" not in output:
            report["errors"].append("Daily workflow stopped before its final summary")
            exit_code = 1
        if "Cannot delete declined Job Scout rows" in output:
            report["errors"].append(
                "Declined-row cleanup blocked by formulas; no rows moved")
        failures = report["counts"].get("Workflow Failures")
        if isinstance(failures, int) and failures:
            report["errors"].append(f"Daily workflow reported {failures} failure(s)")
            exit_code = 1
        if "Gmail response tracking: failed" in output:
            report["errors"].append("Gmail response tracking failed")
            exit_code = 1
        if apply:
            # Report even a partially failed workflow; recheck the destination first.
            sources = source_counts(tracker)
            from generate_apply_queue import read_queue
            final_queue = read_queue(tracker, eligible_scout_ids=resume_ids,
                                     auto_approve_geographic=True)
            attention_counts = {
                "completed_without_link": sum(
                    str((item.fields or {}).get("Resume Created") or "").strip().casefold() == "x"
                    and not str((item.fields or {}).get("Resume Link") or "").strip()
                    for item in final_queue.already_created
                ),
                "missing_identity": len(final_queue.missing_identity),
            }
            fields = history_fields(run_id, run_date, report["counts"], sources,
                                    dry_run=False, exit_code=exit_code,
                                    error="; ".join(report["errors"]),
                                    attention_counts=attention_counts)
            report["attention_counts"] = attention_counts
            if getattr(tracker,'backend','') == 'sqlite':
                from sqlite_daily_report import save_run
                row, height = save_run(tracker,run_id,fields)
            else:
                row, height = write_history(tracker, fields)
            report["daily_run_written"] = height > 0
            report["daily_run_row"] = row
            report["attention"] = fields["Attention Items"].split("; ") if fields["Attention Items"] != "None" else []
    except Exception as exc:
        # Avoid exposing credentials or complete API exception payloads in logs.
        report["errors"].append(safe_error(exc))
        exit_code = 1
    finally:
        report["completed_at"] = datetime.now(ZONE).isoformat()
        folder = root / run_date
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{run_id}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        (folder / f"{run_id}.log").write_text(output, encoding="utf-8")
    return exit_code, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Run live workflow and write Daily Run")
    mode.add_argument("--dry-run", action="store_true", help="Preview discovery and queue without live tracker/resume writes")
    parser.add_argument("--resume-ids", type=int, nargs="+", metavar="ID",
                        help="For testing, limit resume generation to these live Column A IDs")
    parser.add_argument("--sync-local", action="store_true", help="Pull current tracker into local state before resumes")
    args = parser.parse_args(argv)
    if args.resume_ids and (len(args.resume_ids) != len(set(args.resume_ids))
                           or any(value <= 0 for value in args.resume_ids)):
        parser.error("--resume-ids requires distinct positive IDs")
    code, report = run(apply=args.apply,
                       sync_local=args.sync_local,
                       resume_ids=set(args.resume_ids) if args.resume_ids else None)
    print(f"Gecko daily {report['run_id']}: {'FAIL' if code else 'PASS'}")
    for label, value in report["counts"].items():
        print(f"{label}: {value}")
    print(f"Daily Run: {'row ' + str(report['daily_run_row']) if report['daily_run_written'] else 'not written'}")
    for error in report["errors"]:
        print(f"Error: {error}", file=sys.stderr)
    print(f"Audit: reports/daily/{report['run_date']}/{report['run_id']}.json")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
