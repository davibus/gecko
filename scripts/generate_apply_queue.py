"""Generate Gecko V2 resumes for Job Scout rows marked Apply? = Yes.

The Resume Created worksheet field, located by its header, is the sole queue
completion flag. A DOCX already on disk does not skip a row.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from storage import DEFAULT_DB, JobStore  # noqa: E402
from google_tracker import GoogleTracker  # noqa: E402
import gecko_v2  # noqa: E402
import manage_job_tracker  # noqa: E402

REQUIRED = ("Scout ID", "Company", "Job Title", "Apply?", "Resume Created", "Resume Link")


@dataclass(frozen=True)
class QueueRow:
    row: int
    scout_id: int
    company: str
    title: str


@dataclass(frozen=True)
class Artifacts:
    resume: Path
    report: Path
    listing: Path


def _flag(value: object) -> str:
    return str(value or "").strip().casefold()


def read_queue(tracker: GoogleTracker) -> tuple[list[QueueRow], list[QueueRow]]:
    """Return pending and already-created Yes rows without trusting file existence."""
    tab = tracker.scout()
    missing = set(REQUIRED) - tab.headers.keys()
    if missing:
        raise ValueError("Job Scout is missing required columns: " + ", ".join(sorted(missing)))
    pending, skipped = [], []
    for row, data in tab.rows:
        if _flag(data.get("Apply?")) != "yes":
            continue
        raw_id = data.get("Scout ID")
        try:
            scout_id = int(raw_id)
        except (TypeError, ValueError):
            scout_id = 0
        item = QueueRow(row, scout_id, str(data.get("Company") or ""),
                        str(data.get("Job Title") or ""))
        if _flag(data.get("Resume Created")) == "x":
            skipped.append(item)
        else:
            pending.append(item)
    return pending, skipped


def _still_pending(tracker: GoogleTracker, item: QueueRow) -> bool:
    """Re-read the row just before generation in case it changed mid-batch."""
    row = next((data for number, data in tracker.scout().rows if number == item.row), None)
    return bool(row and str(row.get("Scout ID") or "") == str(item.scout_id)
                and _flag(row.get("Apply?")) == "yes" and _flag(row.get("Resume Created")) != "x")


def _completed(tracker: GoogleTracker, item: QueueRow) -> bool:
    row = next((data for number, data in tracker.scout().rows if number == item.row), None)
    return bool(row and _flag(row.get("Resume Created")) == "x" and row.get("Resume Link"))


def _job_number(job) -> str:
    if job.source.casefold() == "indeed":
        jk = parse_qs(urlsplit(job.url).query).get("jk", [])
        if jk and jk[0]:
            return jk[0]
    raw = str(job.source_job_id or "")
    safe = re.sub(r'[\\/:*?"<>|\s]+', "-", raw).strip("-.")
    return safe or f"scout-{job.id}"


def _archive_listing(job) -> Path:
    if not job.description.strip():
        raise ValueError("No stored job description is available for evidence-backed tailoring")
    company = re.sub(r'[\\/:*?"<>|]', "", job.company).replace(" ", "-").rstrip(" .")
    number = _job_number(job)
    path = ROOT / "input/job-descriptions" / f"{company}+{number}.md"
    if path.exists():
        existing = path.read_text(encoding="utf-8-sig")
        if f"**Scout ID:** {job.id}" not in existing:
            raise ValueError(f"Archived listing already exists for another job: {path.name}")
        return path
    text = (f"# {job.title}\n\n"
            f"- **Company:** {job.company}\n"
            f"- **Job Number:** {number}\n"
            f"- **Scout ID:** {job.id}\n"
            f"- **URL:** {job.authoritative_url or job.url}\n"
            f"- **Source:** {job.source}\n"
            f"- **Salary:** {job.salary}\n"
            f"- **Date Discovered:** {job.date_discovered}\n\n"
            f"## Job description\n\n{job.description.strip()}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def generate(item: QueueRow, db: Path) -> Artifacts:
    """Reuse Gecko V2 planning, rendering, Word QA, and match reporting."""
    with JobStore(db) as store:
        job = store.get(item.scout_id)
    if job is None:
        raise ValueError(f"Scout ID {item.scout_id} is absent from the Job Scout datastore")
    if job.company.casefold().strip() != item.company.casefold().strip() or job.title.casefold().strip() != item.title.casefold().strip():
        raise ValueError("Worksheet identity does not match the stored job")
    listing = _archive_listing(job)
    plan = gecko_v2.create_plan(listing.resolve())
    name = f"{plan['job']['safe_company']}+{plan['job']['job_number']}"
    scratch = ROOT / "scratch" / name
    scratch.mkdir(parents=True, exist_ok=True)
    plan_path = scratch / "tailoring-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    candidate = scratch / "queue-candidate.docx"
    gecko_v2.make_resume(plan, candidate)
    qa = gecko_v2.native_qa(plan, candidate, scratch)
    if qa["status"] != "pass":
        raise RuntimeError("V2 QA failed: " + "; ".join(qa["issues"]))
    final = ROOT / "output/resumes" / f"Dave-Call+{name}.docx"
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(candidate, final)
    report = gecko_v2.write_match_report(plan, qa)
    return Artifacts(final, report, listing)


def record_success(artifacts: Artifacts, tracker: GoogleTracker) -> None:
    """Use Gecko's established tracker final step; never write the marker early."""
    args = argparse.Namespace(resume=str(artifacts.resume), match_report=str(artifacts.report),
                              job_description=str(artifacts.listing), date_created=None)
    manage_job_tracker.add_job(args, tracker)


def run_queue(tracker: GoogleTracker, db: Path, *, dry_run: bool = False,
              generator=generate, recorder=record_success) -> int:
    pending, skipped = read_queue(tracker)
    created = 0
    failed: list[tuple[QueueRow, str]] = []
    for item in skipped:
        print(f"SKIP: {item.company} — {item.title} (Scout ID {item.scout_id}): Resume Created = X")
    for item in pending:
        if not _still_pending(tracker, item):
            print(f"SKIP: {item.company} — {item.title} (Scout ID {item.scout_id}): queue flags changed")
            continue
        if dry_run:
            print(f"WOULD CREATE: {item.company} — {item.title} (Scout ID {item.scout_id})")
            continue
        try:
            artifacts = generator(item, db)
            recorder(artifacts, tracker)
            if not _completed(tracker, item):
                raise RuntimeError("Tracker did not mark Resume Created = X and save the resume link")
            created += 1
            print(f"CREATED: {item.company} — {item.title}: {artifacts.resume}")
        except Exception as error:
            failed.append((item, str(error)))
            print(f"FAILED: {item.company} — {item.title}: {error}", file=sys.stderr)
    print("\nGecko Resume Queue Complete")
    print(f"Jobs marked Apply = Yes: {len(pending) + len(skipped)}")
    print(f"Already created/skipped: {len(skipped)}")
    print(f"New resumes created: {created}")
    print(f"Failed: {len(failed)}")
    if dry_run:
        print(f"Would create: {len(pending)}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true", help="Show queue decisions without generating or writing")
    args = parser.parse_args()
    return run_queue(GoogleTracker(), args.db.resolve(), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
