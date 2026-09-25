"""Process live Google Job Scout rows with Apply? = Yes and Resume Created blank."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import html
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
from enrichment import _greenhouse_candidates, _page_candidates, _title_similarity  # noqa: E402
from handoff import job_number as scout_job_number  # noqa: E402
from normalize import clean_text  # noqa: E402
from sources.base import SearchRequest  # noqa: E402
from sources.http import get_document  # noqa: E402
from sources.web import SCRIPT_RE, WebCareerProvider, _job_nodes, _text  # noqa: E402
import gecko_v2  # noqa: E402
import manage_job_tracker  # noqa: E402

REQUIRED = ("Scout ID", "Company", "Job Title", "Apply?", "Resume Created", "Job URL", "Match Score")


@dataclass(frozen=True)
class QueueRow:
    row: int
    scout_id: int
    company: str
    title: str
    job_url: str = ""
    match_score: str = ""
    authoritative_url: str = ""
    enrichment_url: str = ""


@dataclass(frozen=True)
class Artifacts:
    resume: Path
    report: Path
    listing: Path
    existing: bool = False


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


def read_queue(tracker: GoogleTracker) -> tuple[list[QueueRow], list[QueueRow]]:
    """Return pending and already-created Yes rows without trusting file existence."""
    tab = _retry_sheet(tracker.scout)
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
                        str(data.get("Job Title") or ""), str(data.get("Job URL") or ""),
                        str(data.get("Match Score") or ""),
                        str(data.get("Authoritative URL") or ""),
                        str(data.get("Enrichment URL") or ""))
        if _flag(data.get("Resume Created")) == "":
            pending.append(item)
        else:
            skipped.append(item)
    return pending, skipped


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
                    and len(content.split("## ")[-1].strip()) >= 600):
                return path
    return None


def _search_full_description(job) -> str:
    """Try Job Scout's configured career search for the exact employer and role."""
    provider = WebCareerProvider()
    if not provider.configured():
        return ""
    company_tokens = [word for word in re.findall(r"[a-z0-9]+", job.company.casefold())
                      if word not in {"the", "inc", "llc", "ltd", "group", "company", "corporation"}]
    company_words = [word for word in company_tokens if len(word) > 2] or company_tokens
    if not company_words:
        return ""
    company_anchor = company_words[0]
    request = SearchRequest(f"{job.company} {job.title}", results_per_page=8)
    for backend in provider.backends:
        try:
            urls = provider._result_urls(backend, request, f"{job.company} {job.title} careers")
        except Exception:
            continue
        for url in urls:
            try:
                document = get_document(url)
                page = document.body.decode("utf-8", errors="replace")
            except Exception:
                continue
            for block in SCRIPT_RE.findall(page):
                try:
                    nodes = list(_job_nodes(json.loads(html.unescape(block).strip())))
                except (ValueError, TypeError):
                    continue
                for node in nodes:
                    employer = _text(node.get("hiringOrganization"))
                    employer_words = set(re.findall(r"[a-z0-9]+", employer.casefold()))
                    if company_anchor not in employer_words:
                        continue
                    if _title_similarity(job.title, _text(node.get("title"))) < .65:
                        continue
                    description = clean_text(node.get("description"))
                    if len(description) >= 600:
                        return description
            semantic, _ = _page_candidates(page, document.final_url, job)
            for candidate in semantic:
                excerpt_words = set(re.findall(r"[a-z0-9]+", candidate.description[:1000].casefold()))
                if (not candidate.structured and candidate.title_similarity >= .65
                        and company_anchor in excerpt_words
                        and len(candidate.description) >= 600):
                    return candidate.description
    return ""


def _archive_listing(job, item: QueueRow) -> Path:
    saved = _saved_listing(item)
    if saved:
        return saved
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
        if "## " in existing and len(existing.split("## ")[-1].strip()) >= 600:
            return path
    description = (job.enriched_description or job.description).strip()
    if len(description) < 600:
        candidates = []
        errors = []
        urls = (item.authoritative_url, item.enrichment_url, job.enriched_source_url,
                job.authoritative_url, item.job_url, job.url, job.canonical_url,
                *(link.get("url", "") for link in job.source_links))
        for url in dict.fromkeys(filter(None, urls)):
            if urlsplit(url).scheme not in {"http", "https"}:
                continue
            try:
                document = get_document(url)
                if document.content_type.lower() in {"application/json", "application/ld+json"}:
                    found = _greenhouse_candidates(json.loads(document.body), job)
                elif document.content_type.lower() in {"text/html", "application/xhtml+xml", ""}:
                    found, _ = _page_candidates(document.body.decode("utf-8", errors="replace"),
                                                document.final_url, job)
                else:
                    continue
                candidates.extend(candidate for candidate in found
                                  if candidate.title_similarity >= .25 and len(candidate.description) >= 600)
            except Exception as error:
                errors.append(str(error))
        if candidates:
            description = max(candidates, key=lambda candidate: (
                candidate.official, candidate.structured, len(candidate.description))).description
        else:
            description = _search_full_description(job) or description
        if len(description) < 600:
            raise ValueError("Full job description unavailable; stored excerpt is short. " +
                             (errors[-1] if errors else "No matching full text found in career search."))
    if not description:
        raise ValueError("No job description is available for evidence-backed tailoring")
    text = (f"# {job.title}\n\n"
            f"- **Company:** {job.company}\n"
            f"- **Job Number:** {number}\n"
            f"- **Scout ID:** {job.id}\n"
            f"- **URL:** {job.authoritative_url or job.url}\n"
            f"- **Source:** {job.source}\n"
            f"- **Salary:** {job.salary}\n"
            f"- **Date Discovered:** {job.date_discovered}\n\n"
            f"## Job description\n\n{description}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def generate(item: QueueRow, db: Path) -> Artifacts:
    """Reuse Gecko V2 planning, rendering, Word QA, and match reporting."""
    with JobStore(db) as store:
        job = store.get(item.scout_id)
    if job is not None and (job.company.casefold().strip() != item.company.casefold().strip()
                            or job.title.casefold().strip() != item.title.casefold().strip()):
        raise ValueError("Worksheet identity does not match the stored job")
    listing = _archive_listing(job, item) if job is not None else _saved_listing(item)
    if listing is None:
        raise ValueError(f"Scout ID {item.scout_id} has no stored record or complete saved description")
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
    return Artifacts(final, report, listing, existing)


def record_success(item: QueueRow, artifacts: Artifacts, tracker: GoogleTracker) -> None:
    """Mark the selected Scout row after both final files pass validation."""
    if not artifacts.resume.is_file() or not artifacts.report.is_file():
        raise ValueError("Final DOCX and match report are missing")
    if not _still_pending(tracker, item):
        raise RuntimeError("Apply? or Resume Created changed before tracker update")
    _retry_sheet(lambda: manage_job_tracker.mark_batch_resume(item.scout_id, item.row, tracker))


def run_queue(tracker: GoogleTracker, db: Path, *, dry_run: bool = False,
              generator=generate, recorder=record_success) -> int:
    pending, skipped = read_queue(tracker)
    created = recovered = 0
    successes: list[tuple[QueueRow, Artifacts, str]] = []
    changed = 0
    failed: list[tuple[QueueRow, str]] = []
    print(f"Eligible rows: {len(pending)}; skipped with a nonblank marker: {len(skipped)}", flush=True)
    print("Row | Scout ID | Company | Job title", flush=True)
    for item in pending:
        print(f"{item.row} | {item.scout_id} | {item.company} | {item.title}", flush=True)
    if not dry_run:
        print("Processing eligible jobs now.", flush=True)
    for item in pending:
        try:
            if not _still_pending(tracker, item):
                print(f"SKIP: row {item.row} (Scout ID {item.scout_id}): queue flags changed")
                changed += 1
                continue
            if dry_run:
                print(f"WOULD CREATE: row {item.row} (Scout ID {item.scout_id})")
                continue
            artifacts = generator(item, db)
            score = manage_job_tracker.extract_score(artifacts.report.read_text(encoding="utf-8-sig"))
            if not score:
                raise ValueError("Match report has no valid Match Score")
            recorder(item, artifacts, tracker)
            recovered += int(artifacts.existing)
            created += int(not artifacts.existing)
            successes.append((item, artifacts, score))
            print(f"{'VERIFIED EXISTING' if artifacts.existing else 'CREATED'}: row {item.row} "
                  f"(Scout ID {item.scout_id}), {item.company} / {item.title}: "
                  f"{artifacts.resume} | {score}", flush=True)
        except Exception as error:
            failed.append((item, str(error)))
            print(f"FAILED: row {item.row} (Scout ID {item.scout_id}), "
                  f"{item.company} / {item.title}: {error}", file=sys.stderr, flush=True)
        if not dry_run:
            _write_report(pending, skipped, successes, failed, changed)
    remaining = [] if dry_run else read_queue(tracker)[0]
    failed_ids = {item.scout_id for item, _ in failed}
    unexpected = [item for item in remaining if item.scout_id not in failed_ids]
    print("\nGecko Resume Queue Complete")
    print(f"Eligible jobs found: {len(pending)}")
    print(f"Skipped: {len(skipped) + changed}")
    print(f"New resumes created: {created}")
    print(f"Existing valid resumes discovered and marked: {recovered}")
    print(f"Failed: {len(failed)}")
    print("Rows marked X: " + (", ".join(str(item.row) for item, _, _ in successes) or "none"))
    print(f"Remaining eligible rows: {len(remaining)}; unexpected: {len(unexpected)}")
    if dry_run:
        print(f"Would create: {len(pending)}")
    return 1 if failed or unexpected else 0


def _write_report(pending, skipped, successes, failed, changed) -> None:
    path = ROOT / "output/apply-queue-results.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Gecko apply queue results", "", f"Eligible jobs found: {len(pending)}",
             f"Skipped: {len(skipped) + changed}",
             f"New resumes created: {sum(not result.existing for _, result, _ in successes)}",
             f"Existing valid resumes discovered and marked: {sum(result.existing for _, result, _ in successes)}",
             f"Failed: {len(failed)}", "", "## Successful jobs", ""]
    for item, result, score in successes:
        lines.append(f"- Row {item.row}; Scout ID {item.scout_id}; {item.company}; {item.title}; "
                     f"{result.resume}; Match Score {score}")
    lines.extend(["", "## Failures", ""])
    for item, reason in failed:
        lines.append(f"- Row {item.row}; Scout ID {item.scout_id}; {item.company}; {item.title}; "
                     f"{reason.replace(chr(10), ' ')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true", help="Show queue decisions without generating or writing")
    args = parser.parse_args()
    return run_queue(GoogleTracker(), args.db.resolve(), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
