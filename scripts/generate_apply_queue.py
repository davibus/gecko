"""Process live Google Job Scout rows with Apply? = Yes and Resume Created blank."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from storage import DEFAULT_DB, JobStore  # noqa: E402
from google_tracker import GoogleTracker  # noqa: E402
from description_retrieval import (  # noqa: E402
    DescriptionRetrievalResult,
    RetrievalAttempt,
    description_is_sufficient,
    retrieve_full_description,
)
from handoff import job_number as scout_job_number  # noqa: E402
from source_policy import is_jooble_candidate  # noqa: E402
import gecko_v2  # noqa: E402
import manage_job_tracker  # noqa: E402

REQUIRED = ("Scout ID", "Company", "Job Title", "Apply?", "Resume Created", "Job URL")


@dataclass(frozen=True)
class QueueRow:
    row: int
    scout_id: int
    company: str
    title: str
    job_url: str = ""
    source: str = ""


@dataclass(frozen=True)
class Artifacts:
    resume: Path
    report: Path
    listing: Path
    existing: bool = False
    retrieval_attempts: tuple[RetrievalAttempt, ...] = ()


@dataclass(frozen=True)
class QueueFailure:
    item: QueueRow
    reason: str
    original_url: str = ""
    authoritative_url: str = ""
    attempts: tuple[RetrievalAttempt, ...] = ()


@dataclass(frozen=True)
class QueueSnapshot:
    pending: list[QueueRow]
    already_created: list[QueueRow]
    not_approved: list[QueueRow]
    jooble_excluded: list[QueueRow]


@dataclass(frozen=True)
class QueueRunResult:
    snapshot: QueueSnapshot
    successes: list[tuple[QueueRow, Artifacts]]
    failures: list[QueueFailure]
    created: int = 0
    recovered: int = 0
    changed: int = 0
    unexpected: tuple[QueueRow, ...] = ()
    dry_run: bool = False

    @property
    def exit_code(self) -> int:
        return 1 if self.failures or self.unexpected else 0


class DescriptionUnavailableError(ValueError):
    def __init__(self, result: DescriptionRetrievalResult, original_url: str):
        super().__init__(result.error or "Full job description unavailable")
        self.result = result
        self.original_url = original_url


class QueueProcessingError(RuntimeError):
    def __init__(self, reason: str, item: QueueRow, attempts: tuple[RetrievalAttempt, ...]):
        super().__init__(reason)
        self.original_url = item.job_url
        self.authoritative_url = ""
        self.attempts = attempts


def _flag(value: object) -> str:
    return str(value or "").strip().casefold()


def _retry_sheet(action):
    for attempt in range(6):
        try:
            return action()
        except RuntimeError as error:
            message = str(error).casefold()
            if attempt == 5 or not any(term in message for term in ("429", "rate_limit_exceeded", "quota exceeded")):
                raise
            time.sleep(15 * (attempt + 1))


def read_queue(
    tracker: GoogleTracker, eligible_scout_ids: set[int] | None = None
) -> QueueSnapshot:
    """Classify live rows, optionally restricted to the current daily discovery set."""
    tab = _retry_sheet(tracker.scout)
    missing = set(REQUIRED) - tab.headers.keys()
    if missing:
        raise ValueError("Job Scout is missing required columns: " + ", ".join(sorted(missing)))
    pending, already_created, not_approved, jooble_excluded = [], [], [], []
    for row, data in tab.rows:
        raw_id = data.get("Scout ID")
        try:
            scout_id = int(raw_id)
        except (TypeError, ValueError):
            scout_id = 0
        if eligible_scout_ids is not None and scout_id not in eligible_scout_ids:
            continue
        item = QueueRow(row, scout_id, str(data.get("Company") or ""),
                        str(data.get("Job Title") or ""), str(data.get("Job URL") or ""),
                        str(data.get("Source") or ""))
        if is_jooble_candidate(
            source=item.source,
            urls=(item.job_url,),
        ):
            jooble_excluded.append(item)
        elif _flag(data.get("Apply?")) != "yes":
            not_approved.append(item)
        elif _flag(data.get("Resume Created")) == "":
            pending.append(item)
        else:
            already_created.append(item)
    return QueueSnapshot(pending, already_created, not_approved, jooble_excluded)


def _still_pending(tracker: GoogleTracker, item: QueueRow) -> bool:
    """Re-read the row just before generation in case it changed mid-batch."""
    row = next((data for number, data in _retry_sheet(tracker.scout).rows if number == item.row), None)
    return bool(row and str(row.get("Scout ID") or "") == str(item.scout_id)
                and _flag(row.get("Apply?")) == "yes" and _flag(row.get("Resume Created")) == "")


def _job_number(job) -> str:
    if job.source.casefold() == "indeed":
        jk = parse_qs(urlsplit(job.url).query).get("jk", [])
        if jk and jk[0]:
            return jk[0]
    return scout_job_number(job)


def _saved_listing(item: QueueRow) -> Path | None:
    """Find a complete archived listing by Scout ID, including older filenames."""
    for path in (ROOT / "input/job-descriptions").glob("*.md"):
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        if re.search(rf"(?m)^- \*\*Scout ID:\*\*\s*{item.scout_id}\s*$", content):
            meta = gecko_v2.listing_metadata(content, path)
            if (meta["company"].strip().casefold() == item.company.strip().casefold()
                    and description_is_sufficient(content.split("## ")[-1].strip())):
                return path
    return None


def _original_source_url(job, item: QueueRow) -> str:
    aggregators = [
        link.get("url", "") for link in job.source_links
        if link.get("source", "").casefold() in {"jooble", "adzuna"}
    ]
    return job.original_url or next(iter(aggregators), "") or job.url or item.job_url


def _persist_queue_retrieval(job, result: DescriptionRetrievalResult, store: JobStore) -> None:
    if result.authoritative_url and result.authoritative_url != job.authoritative_url:
        job.authoritative_url = result.authoritative_url
        job.url_verification_status = "verified"
        store.save_url_resolution(job)
    if result.status != "succeeded" or not result.source_url:
        return
    current = max((job.description or "", job.enriched_description or ""), key=len)
    if len(result.description) <= len(current):
        return
    if job.enrichment_status == "not_attempted":
        job.original_description = job.description
        job.original_url = job.url
    job.enriched_description = result.description
    job.enriched_source_url = result.source_url
    job.enriched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    job.enrichment_status = "succeeded"
    job.enrichment_error = ""
    store.save_enrichment(job)


def _archive_listing(job, item: QueueRow, store: JobStore) -> tuple[Path, tuple[RetrievalAttempt, ...]]:
    saved = _saved_listing(item)
    if saved:
        attempt = RetrievalAttempt(
            "saved archived description", str(saved), "accepted", "complete archived listing"
        )
        return saved, (attempt,)
    company = re.sub(r'[\\/:*?"<>|]', "", job.company).replace(" ", "-").rstrip(" .")
    number = _job_number(job)
    path = ROOT / "input/job-descriptions" / f"{company}+{number}.md"
    if path.exists():
        existing = path.read_text(encoding="utf-8-sig")
        if f"**Scout ID:**" in existing and f"**Scout ID:** {job.id}" not in existing:
            raise ValueError(f"Archived listing belongs to another Scout job: {path.name}")
        meta = gecko_v2.listing_metadata(existing, path)
        if (meta["company"].strip().casefold() != job.company.strip().casefold() or
                meta["job_number"] != number):
            raise ValueError(f"Archived listing is incomplete or belongs to another job: {path.name}")
        if "## " in existing and description_is_sufficient(existing.split("## ")[-1].strip()):
            attempt = RetrievalAttempt(
                "saved archived description", str(path), "accepted", "complete archived listing"
            )
            return path, (attempt,)
    original_url = _original_source_url(job, item)
    result = retrieve_full_description(
        job,
        authoritative_urls=(job.authoritative_url,),
        redirect_urls=(job.url_redirect_url,),
        ats_urls=(job.enriched_source_url,),
        aggregator_urls=(original_url, item.job_url),
    )
    if result.status != "succeeded" or not description_is_sufficient(result.description):
        raise DescriptionUnavailableError(result, original_url)
    _persist_queue_retrieval(job, result, store)
    description = result.description
    text = (f"# {job.title}\n\n"
            f"- **Company:** {job.company}\n"
            f"- **Job Number:** {number}\n"
            f"- **Scout ID:** {job.id}\n"
            f"- **URL:** {result.authoritative_url or job.authoritative_url or job.url}\n"
            f"- **Original Source URL:** {original_url}\n"
            f"- **Authoritative URL:** {result.authoritative_url or job.authoritative_url}\n"
            f"- **Description Source URL:** {result.source_url}\n"
            f"- **Source:** {job.source}\n"
            f"- **Salary:** {job.salary}\n"
            f"- **Date Discovered:** {job.date_discovered}\n\n"
            f"## Job description\n\n{description}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, tuple(result.attempts)


def generate(item: QueueRow, db: Path) -> Artifacts:
    """Reuse Gecko V2 planning, rendering, Word QA, and match reporting."""
    with JobStore(db) as store:
        job = store.get(item.scout_id)
        if job is not None and (job.company.casefold().strip() != item.company.casefold().strip()
                                or job.title.casefold().strip() != item.title.casefold().strip()):
            raise ValueError("Worksheet identity does not match the stored job")
        if job is not None:
            listing, attempts = _archive_listing(job, item, store)
        else:
            listing, attempts = _saved_listing(item), ()
    if listing is None:
        raise ValueError(f"Scout ID {item.scout_id} has no stored record or complete saved description")
    try:
        return _finish_generation(item, listing, attempts)
    except Exception as error:
        if isinstance(error, (DescriptionUnavailableError, QueueProcessingError)):
            raise
        raise QueueProcessingError(str(error), item, attempts) from error


def _finish_generation(
    item: QueueRow, listing: Path, attempts: tuple[RetrievalAttempt, ...]
) -> Artifacts:
    plan = gecko_v2.create_plan(listing.resolve())
    if (plan["job"]["company"].strip().casefold() != item.company.strip().casefold()
            or plan["job"]["title"].strip().casefold() != item.title.strip().casefold()):
        raise ValueError("Saved listing identity does not match the live Scout row")
    name = f"{plan['job']['safe_company']}+{plan['job']['job_number']}"
    scratch = ROOT / "scratch" / name
    scratch.mkdir(parents=True, exist_ok=True)
    plan_path = scratch / "tailoring-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    final = ROOT / "output/resumes" / gecko_v2.resume_filename(
        plan["job"]["company"], plan["job"]["title"], plan["job"]["job_number"])
    candidate = scratch / "queue-candidate.docx"
    matches = list(final.parent.glob(f"Dave-Call+{plan['job']['safe_company']}+*+{plan['job']['job_number']}.docx"))
    if final not in matches and len(matches) == 1:
        final = matches[0]
    if len(matches) > 1:
        raise ValueError("Multiple candidate resumes exist for this job number; resolve the duplicate first")
    existing = final.is_file()
    qa = gecko_v2.native_qa(plan, final, scratch) if existing else {"status": "fail"}
    rebuilt = False
    if qa["status"] != "pass":
        gecko_v2.make_resume(plan, candidate)
        qa = gecko_v2.native_qa(plan, candidate, scratch)
        rebuilt = True
    if qa["status"] != "pass":
        raise RuntimeError("V2 QA failed: " + "; ".join(qa["issues"]))
    if rebuilt:
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(candidate, final)
        existing = False
    report = gecko_v2.write_match_report(plan, qa)
    return Artifacts(final, report, listing, existing, attempts)


def record_success(item: QueueRow, artifacts: Artifacts, tracker: GoogleTracker) -> None:
    """Record the validated resume through the canonical tracker integration."""
    if not artifacts.resume.is_file() or not artifacts.report.is_file():
        raise ValueError("Final DOCX and match report are missing")
    if not _still_pending(tracker, item):
        raise RuntimeError("Apply? or Resume Created changed before tracker update")
    _retry_sheet(lambda: manage_job_tracker.record_completed_resume(
        artifacts.resume, artifacts.report, artifacts.listing, tracker
    ))


def _log(logger, message: str) -> None:
    if logger is not None:
        logger(message)


def run_queue(
    tracker: GoogleTracker,
    db: Path,
    *,
    dry_run: bool = False,
    eligible_scout_ids: set[int] | None = None,
    generator=generate,
    recorder=record_success,
    logger=None,
    print_summary: bool = True,
) -> QueueRunResult:
    snapshot = read_queue(tracker, eligible_scout_ids)
    pending = snapshot.pending
    skipped = snapshot.already_created
    created = recovered = 0
    successes: list[tuple[QueueRow, Artifacts]] = []
    changed = 0
    failed: list[QueueFailure] = []
    print(f"Eligible rows: {len(pending)}; skipped with a nonblank marker: {len(skipped)}", flush=True)
    if snapshot.jooble_excluded:
        print(f"Jooble rows rejected before Gecko: {len(snapshot.jooble_excluded)}", flush=True)
    _log(logger, f"Eligible rows: {len(pending)}; already marked: {len(skipped)}")
    print("Row | Scout ID | Company | Job title", flush=True)
    for item in pending:
        print(f"{item.row} | {item.scout_id} | {item.company} | {item.title}", flush=True)
    if not dry_run:
        print("Processing eligible jobs now.", flush=True)
    for item in pending:
        try:
            # A dry run is a single read-only snapshot. Re-reading every row adds
            # API traffic and is unnecessary because no lifecycle write follows.
            if not dry_run and not _still_pending(tracker, item):
                print(f"SKIP: row {item.row} (Scout ID {item.scout_id}): queue flags changed")
                changed += 1
                continue
            if dry_run:
                print(f"WOULD CREATE: row {item.row} (Scout ID {item.scout_id})")
                continue
            artifacts = generator(item, db)
            recorder(item, artifacts, tracker)
            recovered += int(artifacts.existing)
            created += int(not artifacts.existing)
            successes.append((item, artifacts))
            print(f"{'VERIFIED EXISTING' if artifacts.existing else 'CREATED'}: row {item.row} "
                  f"(Scout ID {item.scout_id}), {item.company} / {item.title}: "
                  f"{artifacts.resume}", flush=True)
            _log(logger, f"SUCCESS row={item.row} scout_id={item.scout_id} "
                 f"resume={artifacts.resume}")
            for attempt in artifacts.retrieval_attempts:
                _log(logger, "  " + attempt.summary())
        except Exception as error:
            if isinstance(error, DescriptionUnavailableError):
                failure = QueueFailure(
                    item=item,
                    reason=error.result.error or str(error),
                    original_url=error.original_url,
                    authoritative_url=error.result.authoritative_url,
                    attempts=tuple(error.result.attempts),
                )
            elif isinstance(error, QueueProcessingError):
                failure = QueueFailure(
                    item=item,
                    reason=str(error),
                    original_url=error.original_url,
                    authoritative_url=error.authoritative_url,
                    attempts=error.attempts,
                )
            else:
                failure = QueueFailure(
                    item=item,
                    reason=str(error),
                    original_url=item.job_url,
                    authoritative_url="",
                )
            failed.append(failure)
            print(f"FAILED: row {item.row} (Scout ID {item.scout_id}), "
                  f"{item.company} / {item.title}: {error}", file=sys.stderr, flush=True)
            _log(logger, f"FAIL row={item.row} scout_id={item.scout_id} reason={failure.reason}")
            for attempt in failure.attempts:
                _log(logger, "  " + attempt.summary())
        if not dry_run:
            _write_report(pending, skipped, successes, failed, changed)
    remaining = pending if dry_run else read_queue(tracker, eligible_scout_ids).pending
    failed_ids = {failure.item.scout_id for failure in failed}
    unexpected = [] if dry_run else [item for item in remaining if item.scout_id not in failed_ids]
    result = QueueRunResult(
        snapshot=snapshot, successes=successes, failures=failed, created=created,
        recovered=recovered, changed=changed, unexpected=tuple(unexpected),
        dry_run=dry_run,
    )
    if print_summary:
        print("\nGecko Resume Queue Complete")
        print(f"Eligible jobs found: {len(pending)}")
        print(f"Skipped: {len(skipped) + changed}")
        print(f"Jooble rows excluded: {len(snapshot.jooble_excluded)}")
        print(f"New resumes created: {created}")
        print(f"Existing valid resumes discovered and marked: {recovered}")
        print(f"Failed: {len(failed)}")
        print("Rows marked X: " + (", ".join(str(item.row) for item, _ in successes) or "none"))
        print(f"Remaining eligible rows: {len(remaining)}; unexpected: {len(unexpected)}")
        if dry_run:
            print(f"Would create: {len(pending)}")
    return result


def _write_report(pending, skipped, successes, failed, changed) -> None:
    path = ROOT / "output/apply-queue-results.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Gecko apply queue results", "", f"Eligible jobs found: {len(pending)}",
             f"Skipped: {len(skipped) + changed}",
             f"New resumes created: {sum(not result.existing for _, result in successes)}",
             f"Existing valid resumes discovered and marked: {sum(result.existing for _, result in successes)}",
             f"Failed: {len(failed)}", "", "## Successful jobs", ""]
    for item, result in successes:
        lines.append(f"- Row {item.row}; Scout ID {item.scout_id}; {item.company}; {item.title}; "
                     f"{result.resume}")
    lines.extend(["", "## Failures", ""])
    for failure in failed:
        item = failure.item
        lines.extend([
            f"### Row {item.row}: Scout ID {item.scout_id} — {item.company} — {item.title}",
            "",
            f"- Original source URL: {failure.original_url or '(not stored)'}",
            f"- Authoritative URL: {failure.authoritative_url or '(not found)'}",
            "- Retrieval attempts:",
        ])
        if failure.attempts:
            lines.extend(f"  - {attempt.summary()}" for attempt in failure.attempts)
        else:
            lines.append("  - No URL retrieval attempt was reached before this failure.")
        lines.extend([
            f"- Final reason: {failure.reason.replace(chr(10), ' ')}",
            "",
        ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_run_log(message: str) -> None:
    path = ROOT / "output/apply-queue-run.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def main() -> int:
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true", help="Show queue decisions without generating or writing")
    args = parser.parse_args()
    _append_run_log(f"RUN START dry_run={args.dry_run} db={args.db.resolve()}")
    result = run_queue(
        GoogleTracker(), args.db.resolve(), dry_run=args.dry_run,
        logger=_append_run_log,
    )
    _append_run_log(f"RUN END exit_code={result.exit_code}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
