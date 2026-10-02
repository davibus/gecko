"""Process eligible live Google Job Scout rows through the Gecko resume workflow."""

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
from urllib.parse import parse_qs, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from storage import DEFAULT_DB, JobStore  # noqa: E402
from google_tracker import (  # noqa: E402
    GoogleTracker,
    apply_value,
)
from manual_indeed import next_scout_id  # noqa: E402
from description_retrieval import (  # noqa: E402
    DescriptionRetrievalResult,
    RetrievalAttempt,
    retrieve_full_description,
)
from handoff import job_number as scout_job_number  # noqa: E402
from models import RawListing  # noqa: E402
from normalize import normalize  # noqa: E402
import gecko_v2  # noqa: E402
import manage_job_tracker  # noqa: E402

REQUIRED = (
    "Scout ID", "Company", "Job Title", "Apply?", "Resume Created", "Cost",
    "Job URL", "Resume Link",
)
COMPLETION_MARKER = "X"
LEGACY_COMPLETION_MARKERS = frozenset({"c", "x"})


@dataclass(frozen=True)
class QueueRow:
    row: int
    scout_id: int | None
    company: str
    title: str
    job_url: str = ""
    source: str = ""
    fields: dict[str, object] | None = None
    listing_content: str = ""


@dataclass(frozen=True)
class Artifacts:
    resume: Path
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
    link_backfill: list[QueueRow]
    duplicate_excluded: list[QueueRow]
    missing_identity: list[QueueRow]
    cost_excluded: list[QueueRow]
    decisions: list[tuple[QueueRow, str]]
    stats: dict[str, int]


@dataclass(frozen=True)
class QueueRunResult:
    snapshot: QueueSnapshot
    successes: list[tuple[QueueRow, Artifacts]]
    failures: list[QueueFailure]
    created: int = 0
    recovered: int = 0
    changed: int = 0
    apply_values_set: int = 0
    scout_ids_assigned: int = 0
    resume_links_written: int = 0
    rows_marked_created: int = 0
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


def _resume_completed(value: object) -> bool:
    """Recognize the canonical X marker and Gecko's prior C marker."""
    return _flag(value) in LEGACY_COMPLETION_MARKERS


def _scout_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    text = str(value or "").strip()
    match = re.fullmatch(r"(?:JS-)?(\d+)", text, re.IGNORECASE)
    number = int(match.group(1)) if match else 0
    return number if number > 0 else None


def _identity_text(value: object) -> str:
    """Compare Sheet/listing identity while ignoring punctuation encoding damage."""
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _indeed_job_key(value: object) -> str:
    url = str(value or "").strip()
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").casefold().removeprefix("www.")
    if hostname != "indeed.com" and not hostname.endswith(".indeed.com"):
        return ""
    values = parse_qs(parsed.query).get("jk", [])
    return values[0].strip() if values and values[0].strip() else ""


def _is_indeed_url(value: object) -> bool:
    parsed = urlsplit(str(value or "").strip())
    hostname = (parsed.hostname or "").casefold().removeprefix("www.")
    return hostname == "indeed.com" or hostname.endswith(".indeed.com")


def _url_only(value: object) -> bool:
    return bool(re.fullmatch(r"https?://\S+", str(value or "").strip(), re.IGNORECASE))


def _listing_value(data: dict[str, object]) -> str:
    for name in ("Job Listing", "Job Description", "Listing", "Description"):
        value = str(data.get(name) or "").strip()
        if value:
            return value
    return str(data.get("Job URL") or "").strip()


def _usable_listing(value: object) -> bool:
    text = " ".join(str(value or "").split()).strip()
    if not text or _url_only(text):
        return False
    return len(re.findall(r"[A-Za-z]{2,}", text)) >= 3


def _structured_context(item: QueueRow) -> list[str]:
    fields = item.fields or {}
    return [str(fields.get(label) or "").strip()
            for label in ("Location", "Work Arrangement", "Employment Type", "Salary")
            if str(fields.get(label) or "").strip()]


def _has_reliable_job_information(item: QueueRow) -> bool:
    return _usable_listing(item.listing_content) or bool(_structured_context(item))


def _geographic_qualification(item: QueueRow) -> str:
    fields = item.fields or {}
    location = fields.get("Location")
    arrangement = fields.get("Work Arrangement")
    decision = apply_value(location, arrangement)
    if decision != "Yes":
        return ""
    if re.search(r"(?<![A-Za-z])(?:utah|ut)(?![A-Za-z])", str(location or ""),
                 re.IGNORECASE):
        return "Utah"
    return "Remote"


def _queue_item(tab, row: int, data: dict[str, object]) -> QueueRow:
    listing_value = _listing_value(data)
    raw_url = str(data.get("Job URL") or "").strip()
    job_url = raw_url if _url_only(raw_url) else (listing_value if _url_only(listing_value) else "")
    listing_content = listing_value if not _url_only(listing_value) else ""
    return QueueRow(
        row, _scout_id(data.get("Scout ID")), str(data.get("Company") or ""),
        str(data.get("Job Title") or ""), job_url, str(data.get("Source") or ""),
        dict(data), listing_content,
    )


def _matches_source(data: dict[str, object], source: str | None) -> bool:
    if source is None:
        return True
    if source.casefold() != "indeed":
        raise ValueError(f"Unsupported queue source: {source}")
    if _flag(data.get("Source")) == "indeed":
        return True
    return _is_indeed_url(data.get("Job URL"))


def _duplicate_key(item: QueueRow) -> tuple[str, str] | None:
    indeed_key = _indeed_job_key(item.job_url)
    if indeed_key:
        return "indeed", indeed_key.casefold()
    url = item.job_url.strip().casefold().rstrip("/")
    if url:
        return "url", url
    if item.scout_id is not None:
        return "scout", str(item.scout_id)
    return None


def _valid_resume_link(value: object) -> bool:
    text = str(value or "").strip()
    if re.fullmatch(r"https://[^\s]+", text, re.IGNORECASE):
        return True
    if re.fullmatch(r"file:///[A-Za-z]:/[^\r\n]+\.docx", text, re.IGNORECASE):
        parsed = urlsplit(text)
        local = unquote(parsed.path)
        if re.fullmatch(r"/[A-Za-z]:/.*", local):
            local = local[1:]
        path = Path(local).resolve()
        return (path.parent == (ROOT / "output" / "resumes").resolve()
                and path.is_file() and path.stat().st_size > 0)
    return False


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
    tracker: GoogleTracker,
    eligible_scout_ids: set[int] | None = None,
    source: str | None = None,
    *,
    auto_approve_geographic: bool = False,
) -> QueueSnapshot:
    """Classify live rows, optionally restricted to the current daily discovery set."""
    tab = _retry_sheet(lambda: tracker.scout(value_render_option="FORMULA"))
    missing = set(REQUIRED) - tab.headers.keys()
    if missing:
        raise ValueError("Job Scout is missing required columns: " + ", ".join(sorted(missing)))
    matched: list[QueueRow] = []
    for row, data in tab.rows:
        if not _matches_source(data, source):
            continue
        matched.append(_queue_item(tab, row, data))

    pending, already_created, not_approved, jooble_excluded, link_backfill = [], [], [], [], []
    duplicate_excluded, missing_identity, cost_excluded, decisions = [], [], [], []
    stats = {
        "indeed_rows_checked": len(matched), "utah_qualifying": 0,
        "remote_qualifying": 0, "would_set_apply_yes": 0, "already_approved": 0,
        "explicitly_declined": 0, "explicit_manual_values": 0,
        "outside_utah_non_remote": 0, "would_assign_scout_id": 0,
        "eligible_for_resume": 0, "already_completed": 0,
        "missing_usable_listing": 0, "duplicate_exclusions": 0,
        "cost_excluded": 0, "repair_eligible": 0,
    }
    completed_keys = {
        key for item in matched
        if (_resume_completed((item.fields or {}).get("Resume Created"))
            and _flag((item.fields or {}).get("Cost")) != "x")
        for key in [_duplicate_key(item)] if key is not None
    }
    seen_pending: set[tuple[str, str]] = set()
    for item in matched:
        data = item.fields or {}
        if _flag(data.get("Cost")) == "x":
            cost_excluded.append(item)
            stats["cost_excluded"] += 1
            decisions.append((item, "SKIP: Cost = X"))
            continue
        qualification = (
            _geographic_qualification(item)
            if source == "indeed" or auto_approve_geographic else ""
        )
        if qualification == "Utah":
            stats["utah_qualifying"] += 1
        elif qualification == "Remote":
            stats["remote_qualifying"] += 1
        if not _usable_listing(item.listing_content) and not item.job_url:
            stats["missing_usable_listing"] += 1
        needs_global_backfill = (
            _flag(data.get("Apply?")) == "yes"
            and _resume_completed(data.get("Resume Created"))
            and not _valid_resume_link(data.get("Resume Link"))
        )
        if (eligible_scout_ids is not None
                and (item.scout_id is None or item.scout_id not in eligible_scout_ids)
                and not needs_global_backfill
                and source is None):
            continue
        if _resume_completed(data.get("Resume Created")):
            stats["already_completed"] += 1
            if not _valid_resume_link(data.get("Resume Link")):
                if _flag(data.get("Apply?")) == "yes":
                    link_backfill.append(item)
                    stats["repair_eligible"] += 1
                    decisions.append((item, "REPAIR: Resume Created = X and Resume Link is blank"))
                else:
                    already_created.append(item)
                    decisions.append((item, "SKIP: Resume already created"))
            else:
                already_created.append(item)
                decisions.append((item, "SKIP: Resume already created"))
        elif not item.company.strip() or not item.title.strip():
            missing_identity.append(item)
            decisions.append((item, "SKIP: missing required job identity"))
        else:
            current_apply = str(data.get("Apply?") or "").strip()
            normalized_apply = _flag(current_apply)
            auto_apply = ((source == "indeed" or auto_approve_geographic)
                          and bool(qualification) and normalized_apply != "yes")
            if normalized_apply == "yes":
                stats["already_approved"] += 1
            elif auto_apply:
                stats["would_set_apply_yes"] += 1
            elif not current_apply and (source == "indeed" or auto_approve_geographic):
                stats["outside_utah_non_remote"] += 1
                not_approved.append(item)
                decisions.append((item, "SKIP: outside Utah and not remote"))
                continue
            elif normalized_apply == "no":
                stats["explicitly_declined"] += 1
                not_approved.append(item)
                decisions.append((item, "SKIP: Apply? explicitly No"))
                continue
            elif normalized_apply != "yes":
                stats["explicit_manual_values"] += 1
                not_approved.append(item)
                decisions.append((
                    item,
                    f"SKIP: Apply? explicit value {current_apply!r} prevents automatic approval",
                ))
                continue
            if ((key := _duplicate_key(item)) is not None
                    and (key in completed_keys or key in seen_pending)):
                duplicate_excluded.append(item)
                stats["duplicate_exclusions"] += 1
                decisions.append((item, "SKIP: duplicate job"))
                continue
            pending.append(item)
            key = _duplicate_key(item)
            if key is not None:
                seen_pending.add(key)
            stats["eligible_for_resume"] += 1
            if item.scout_id is None:
                stats["would_assign_scout_id"] += 1
            if _usable_listing(item.listing_content):
                listing_note = "usable Job URL/listing content"
            elif item.job_url:
                listing_note = "Job URL; description retrieval would run"
            else:
                listing_note = "no usable Job URL/listing"
            id_note = (f"existing Scout ID {item.scout_id}" if item.scout_id is not None
                       else "WOULD ASSIGN SCOUT ID")
            if auto_apply:
                decision = (f"WOULD SET APPLY? = Yes | {qualification} | {id_note} | "
                            f"{listing_note} | WOULD RUN Gecko resume generation | "
                            "WOULD SAVE LOCAL output/resumes")
            else:
                decision = (f"ELIGIBLE | {id_note} | {listing_note} | "
                            "WOULD RUN Gecko resume generation | "
                            "WOULD SAVE LOCAL output/resumes")
            decisions.append((item, decision))
    stats["would_assign_scout_id"] += sum(
        1 for item in link_backfill if item.scout_id is None
    )
    return QueueSnapshot(
        pending, already_created, not_approved, jooble_excluded, link_backfill,
        duplicate_excluded, missing_identity, cost_excluded, decisions, stats,
    )


def _still_pending(tracker: GoogleTracker, item: QueueRow, *, link_backfill: bool = False) -> bool:
    """Re-read the row just before generation in case it changed mid-batch."""
    matches = [data for row, data in _retry_sheet(
        lambda: tracker.scout(value_render_option="FORMULA")
    ).rows if (
        (item.scout_id is not None and str(data.get("Scout ID") or "") == str(item.scout_id))
        or (item.scout_id is None and row == item.row and not str(data.get("Scout ID") or "").strip())
    )]
    if len(matches) != 1:
        return False
    row = matches[0]
    identity_matches = (
        _flag(row.get("Company")) == _flag(item.company)
        and _flag(row.get("Job Title")) == _flag(item.title)
    )
    if not identity_matches:
        return False
    if link_backfill:
        return (_flag(row.get("Cost")) != "x"
                and _flag(row.get("Apply?")) == "yes"
                and _resume_completed(row.get("Resume Created"))
                and not _valid_resume_link(row.get("Resume Link")))
    return (_flag(row.get("Apply?")) == "yes"
            and _flag(row.get("Cost")) != "x"
            and not _resume_completed(row.get("Resume Created")))


def _refresh_item(tracker: GoogleTracker, item: QueueRow) -> QueueRow:
    tab = _retry_sheet(lambda: tracker.scout(value_render_option="FORMULA"))
    if item.scout_id is not None:
        matches = [(row, data) for row, data in tab.rows
                   if _scout_id(data.get("Scout ID")) == item.scout_id]
    else:
        matches = [(row, data) for row, data in tab.rows if row == item.row]
    if len(matches) != 1:
        raise RuntimeError("Could not re-read the unique Job Scout row")
    row, data = matches[0]
    refreshed = _queue_item(tab, row, data)
    if (_flag(refreshed.company) != _flag(item.company)
            or _flag(refreshed.title) != _flag(item.title)):
        raise RuntimeError("Job Scout row identity changed before resume generation")
    return refreshed


@dataclass
class _BatchScoutIdAllocator:
    """Reserve monotonically increasing IDs across one queue run."""

    next_value: int
    reserved: set[int]

    @classmethod
    def from_live_state(
        cls, tracker: GoogleTracker, db: Path,
    ) -> "_BatchScoutIdAllocator":
        tab = _retry_sheet(lambda: tracker.scout(value_render_option="FORMULA"))
        with JobStore(db) as store:
            first = next_scout_id(tab, store)
        reserved = {
            value for _, data in tab.rows
            if (value := _scout_id(data.get("Scout ID"))) is not None
        }
        return cls(first, reserved)

    def assign(self, tracker: GoogleTracker, item: QueueRow) -> int:
        """Persist one reserved ID, refreshing if another writer wins a race."""
        for _ in range(6):
            while self.next_value in self.reserved or self.next_value <= 0:
                self.next_value += 1
            candidate = self.next_value
            try:
                assigned = _retry_sheet(lambda: tracker.assign_manual_scout_id(
                    item.row, candidate, company=item.company, title=item.title,
                ))
            except RuntimeError as error:
                if "already in use" not in str(error).casefold():
                    raise
                live = _retry_sheet(lambda: tracker.scout(value_render_option="FORMULA"))
                self.reserved.update(
                    value for _, data in live.rows
                    if (value := _scout_id(data.get("Scout ID"))) is not None
                )
                self.next_value = max([candidate, *self.reserved], default=candidate) + 1
                continue
            self.reserved.add(assigned)
            self.next_value = assigned + 1
            return assigned
        raise RuntimeError("Could not allocate a unique Scout ID after refreshing live IDs")


def _prepare_indeed_item(
    tracker: GoogleTracker,
    item: QueueRow,
    db: Path,
    allocator: _BatchScoutIdAllocator | None = None,
) -> QueueRow:
    """Apply a qualifying blank decision, then allocate the canonical Scout ID."""
    current = _refresh_item(tracker, item)
    apply_value = str((current.fields or {}).get("Apply?") or "").strip()
    qualification = _geographic_qualification(current)
    if qualification and _flag(apply_value) != "yes":
        _retry_sheet(lambda: tracker.approve_manual_scout_row(
            current.row, company=current.company, title=current.title,
        ))
        current = _refresh_item(tracker, current)
    if _flag((current.fields or {}).get("Apply?")) != "yes":
        raise RuntimeError("Apply? is no longer Yes; resume generation was not started")
    if _flag((current.fields or {}).get("Cost")) == "x":
        raise RuntimeError("Cost is X; resume generation was not started")
    if current.scout_id is None:
        if allocator is None:
            allocator = _BatchScoutIdAllocator.from_live_state(tracker, db)
        allocator.assign(tracker, current)
        current = _refresh_item(tracker, current)
    if current.scout_id is None or current.scout_id <= 0:
        raise RuntimeError("A unique positive Scout ID was not assigned")
    return current


def _job_number(job) -> str:
    if job.source.casefold() == "indeed":
        jk = parse_qs(urlsplit(job.url).query).get("jk", [])
        if jk and jk[0]:
            return jk[0]
    return scout_job_number(job)


def _saved_listing(item: QueueRow) -> Path | None:
    """Find an archived listing for this exact live row without imposing a length floor."""
    for path in (ROOT / "input/job-descriptions").glob("*.md"):
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        meta = gecko_v2.listing_metadata(content, path)
        scout_matches = (
            item.scout_id is not None
            and re.search(rf"(?m)^- \*\*Scout ID:\*\*\s*{item.scout_id}\s*$", content)
        )
        number_matches = item.scout_id is None and meta["job_number"] == _row_job_number(item)
        if ((scout_matches or number_matches)
                and _identity_text(meta["company"]) == _identity_text(item.company)
                and _identity_text(meta["title"]) == _identity_text(item.title)):
            return path
    return None


def _row_job_number(item: QueueRow) -> str:
    if jk := _indeed_job_key(item.job_url):
        return jk
    return f"scout-{item.scout_id or item.row}"


def _archive_row_context(item: QueueRow) -> Path:
    """Archive reliable Sheet context when no matching stored job record exists."""
    if not item.company.strip() or not item.title.strip():
        missing = " and ".join(name for name, value in (
            ("company", item.company), ("job title", item.title)
        ) if not value.strip())
        raise ValueError(
            f"Resume not created: {missing} is missing, so the target position cannot be identified."
        )
    if not _has_reliable_job_information(item):
        raise ValueError(
            "Resume not created: Job URL has no usable job listing and the structured row "
            "does not contain enough reliable job information."
        )
    company = re.sub(r'[\\/:*?"<>|]', "", item.company).replace(" ", "-").rstrip(" .")
    number = _row_job_number(item)
    path = ROOT / "input/job-descriptions" / f"{company}+{number}.md"
    fields = item.fields or {}
    context = [
        f"Target position: {item.title}",
        f"Company: {item.company}",
    ]
    for label in ("Location", "Work Arrangement", "Employment Type", "Salary"):
        value = str(fields.get(label) or "").strip()
        if value:
            context.append(f"{label}: {value}")
    scout_line = f"- **Scout ID:** {item.scout_id}\n" if item.scout_id is not None else ""
    effective_source = item.source.strip() or ("Indeed" if _is_indeed_url(item.job_url) else "")
    primary = item.listing_content.strip()
    description = (
        f"## Job description (Google Sheet Job URL/listing field)\n\n{primary}\n\n"
        if _usable_listing(primary) else ""
    )
    text = (f"# {item.title}\n\n"
            f"- **Company:** {item.company}\n"
            f"- **Job Number:** {number}\n"
            f"{scout_line}"
            f"- **URL:** {item.job_url}\n"
            f"- **Source:** {effective_source}\n"
            f"- **Salary:** {fields.get('Salary') or ''}\n\n"
            f"{description}"
            f"## Structured job information\n\n" + "\n".join(context) + "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


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


def _archive_listing(
    job, item: QueueRow, store: JobStore, *, persist_retrieval: bool = True,
) -> tuple[Path, tuple[RetrievalAttempt, ...]]:
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
        if "## " in existing:
            attempt = RetrievalAttempt(
                "saved archived description", str(path), "accepted", "archived job context"
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
    if result.status == "succeeded" and result.description.strip():
        if persist_retrieval:
            _persist_queue_retrieval(job, result, store)
        description = result.description
        description_url = result.source_url
    else:
        description = max((job.enriched_description or "", job.description or ""), key=len).strip()
        description_url = job.enriched_source_url or job.original_url or job.url
        if not description:
            description = (f"Target position: {job.title}\nCompany: {job.company}\n"
                           f"Location: {job.location}\nWork arrangement: {job.work_arrangement}\n"
                           f"Employment type: {job.employment_type}")
        result.attempts.append(RetrievalAttempt(
            "available stored job context", description_url, "accepted",
            "used without a minimum description-length requirement",
        ))
    scout_line = f"- **Scout ID:** {job.id}\n" if job.id is not None else ""
    text = (f"# {job.title}\n\n"
            f"- **Company:** {job.company}\n"
            f"- **Job Number:** {number}\n"
            f"{scout_line}"
            f"- **URL:** {result.authoritative_url or job.authoritative_url or job.url}\n"
            f"- **Original Source URL:** {original_url}\n"
            f"- **Authoritative URL:** {result.authoritative_url or job.authoritative_url}\n"
            f"- **Description Source URL:** {description_url}\n"
            f"- **Source:** {job.source}\n"
            f"- **Salary:** {job.salary}\n"
            f"- **Date Discovered:** {job.date_discovered}\n\n"
            f"## Job description\n\n{description}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, tuple(result.attempts)


def _job_from_sheet_row(item: QueueRow):
    fields = item.fields or {}
    raw = RawListing(
        source=item.source.strip() or "indeed",
        source_job_id=_indeed_job_key(item.job_url) or f"scout-{item.scout_id or item.row}",
        url=item.job_url,
        title=item.title,
        company=item.company,
        location=str(fields.get("Location") or ""),
        description=item.listing_content,
        employment_type=str(fields.get("Employment Type") or ""),
        salary=str(fields.get("Salary") or ""),
        remote_type=str(fields.get("Work Arrangement") or ""),
    )
    job = normalize(raw)
    job.id = item.scout_id
    return job


def generate(item: QueueRow, db: Path, *, force_recreate: bool = False) -> Artifacts:
    """Reuse Gecko V2 planning, rendering, and Word QA."""
    with JobStore(db) as store:
        job = store.get(item.scout_id) if item.scout_id is not None else None
        if _usable_listing(item.listing_content):
            listing, attempts = _archive_row_context(item), (
                RetrievalAttempt(
                    "Google Sheet Job URL/listing field", "Job Scout", "accepted",
                    "used as the primary job listing",
                ),
            )
        elif job is not None and (job.company.casefold().strip() == item.company.casefold().strip()
                                and job.title.casefold().strip() == item.title.casefold().strip()):
            listing, attempts = _archive_listing(job, item, store)
        elif item.job_url:
            listing, attempts = _archive_listing(
                _job_from_sheet_row(item), item, store, persist_retrieval=False,
            )
        else:
            listing, attempts = _saved_listing(item), ()
            if listing is None:
                listing = _archive_row_context(item)
    if listing is None:
        raise ValueError(f"Scout ID {item.scout_id} has no stored record or complete saved description")
    try:
        return _finish_generation(item, listing, attempts, force_recreate=force_recreate)
    except Exception as error:
        if isinstance(error, (DescriptionUnavailableError, QueueProcessingError)):
            raise
        raise QueueProcessingError(str(error), item, attempts) from error


def recreate(item: QueueRow, db: Path) -> Artifacts:
    """Rebuild a repair-row resume from current authorities without replacing old files."""
    return generate(item, db, force_recreate=True)


def _validated_artifact_near(
    scratch: Path, output_dir: Path,
) -> Path | None:
    """Recover a uniquely timestamp-correlated artifact from an interrupted old run."""
    status_path = scratch / "validation-status.json"
    if not status_path.is_file():
        return None
    try:
        status = json.loads(status_path.read_text(encoding="utf-8-sig"))
        if status.get("status") != "native-valid":
            return None
        validated_at = datetime.fromisoformat(str(status["validated_at"])).timestamp()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    matches = [
        path for path in output_dir.glob("*.docx")
        if path.is_file() and path.stat().st_size > 0
        and abs(path.stat().st_mtime - validated_at) <= 8
    ]
    return matches[0] if len(matches) == 1 else None


def _find_existing_resume(plan: dict, scratch: Path) -> Path | None:
    """Locate only an artifact tied to the canonical job identity or QA record."""
    output_dir = ROOT / "output/resumes"
    expected = output_dir / gecko_v2.resume_filename(
        plan["job"]["company"], plan["job"]["title"], plan["job"]["job_number"]
    )
    if expected.is_file() and expected.stat().st_size > 0:
        return expected
    numbered = list(output_dir.glob(
        f"Dave-Call+{plan['job']['safe_company']}+*+{plan['job']['job_number']}.docx"
    ))
    if len(numbered) == 1 and numbered[0].stat().st_size > 0:
        return numbered[0]
    # Older interrupted manual runs briefly emitted the same canonical name
    # without the final job-number field. Accept it only as a unique exact name.
    legacy = output_dir / (expected.name.rsplit("+", 1)[0] + ".docx")
    if legacy.is_file() and legacy.stat().st_size > 0:
        return legacy
    return _validated_artifact_near(scratch, output_dir)


def _dry_run_existing_resume(item: QueueRow) -> Path | None:
    """Read-only best-effort detection for dry-run action reporting."""
    job_number = _indeed_job_key(item.job_url) or (
        f"scout-{item.scout_id}" if item.scout_id is not None else ""
    )
    if not job_number:
        return None
    output_dir = ROOT / "output/resumes"
    expected = output_dir / gecko_v2.resume_filename(item.company, item.title, job_number)
    if expected.is_file() and expected.stat().st_size > 0:
        return expected
    legacy = output_dir / (expected.name.rsplit("+", 1)[0] + ".docx")
    if legacy.is_file() and legacy.stat().st_size > 0:
        return legacy
    safe_company = re.sub(r'[\\/:*?"<>|]', "", item.company).replace(" ", "-").rstrip(" .")
    scratch = ROOT / "scratch" / f"{safe_company}+{job_number}"
    return _validated_artifact_near(scratch, output_dir)


def recover_existing(item: QueueRow, db: Path) -> Artifacts:
    """Reliably identify an existing validated resume without generating a duplicate."""
    with JobStore(db) as store:
        job = store.get(item.scout_id) if item.scout_id is not None else None
        if job is not None and (job.company.casefold().strip() == item.company.casefold().strip()
                                and job.title.casefold().strip() == item.title.casefold().strip()):
            listing, attempts = _archive_listing(job, item, store)
        else:
            listing, attempts = _saved_listing(item), ()
    if listing is None:
        raise RuntimeError(
            "Resume Created is complete but no exact archived listing identifies the existing resume"
        )
    plan = gecko_v2.create_plan(listing.resolve())
    if (_identity_text(plan["job"]["company"]) != _identity_text(item.company)
            or _identity_text(plan["job"]["title"]) != _identity_text(item.title)):
        raise RuntimeError("Existing archived listing identity does not match the live Scout row")
    scratch = ROOT / "scratch" / f"{plan['job']['safe_company']}+{plan['job']['job_number']}"
    final = _find_existing_resume(plan, scratch)
    if final is None:
        raise RuntimeError(
            "Resume Created is complete but an exact existing DOCX could not be identified; no duplicate was generated"
        )
    scratch.mkdir(parents=True, exist_ok=True)
    qa = gecko_v2.native_qa(plan, final, scratch)
    if qa["status"] != "pass":
        raise RuntimeError("Existing resume failed Word-native QA; Resume Link was not updated")
    return Artifacts(final, listing, True, attempts)


def _finish_generation(
    item: QueueRow, listing: Path, attempts: tuple[RetrievalAttempt, ...],
    *, force_recreate: bool = False,
) -> Artifacts:
    plan = gecko_v2.create_plan(listing.resolve())
    if (_identity_text(plan["job"]["company"]) != _identity_text(item.company)
            or _identity_text(plan["job"]["title"]) != _identity_text(item.title)):
        raise ValueError("Saved listing identity does not match the live Scout row")
    name = f"{plan['job']['safe_company']}+{plan['job']['job_number']}"
    scratch = ROOT / "scratch" / name
    scratch.mkdir(parents=True, exist_ok=True)
    plan_path = scratch / "tailoring-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    expected = ROOT / "output/resumes" / gecko_v2.resume_filename(
        plan["job"]["company"], plan["job"]["title"], plan["job"]["job_number"])
    candidate = scratch / "queue-candidate.docx"
    final = None if force_recreate else _find_existing_resume(plan, scratch)
    final = final or expected
    existing = not force_recreate and final.is_file() and final.stat().st_size > 0
    qa = gecko_v2.native_qa(plan, final, scratch) if existing else {"status": "fail"}
    rebuilt = False
    if qa["status"] != "pass":
        gecko_v2.make_resume(plan, candidate)
        qa = gecko_v2.native_qa(plan, candidate, scratch)
        rebuilt = True
    if qa["status"] != "pass":
        raise RuntimeError("V2 QA failed: " + "; ".join(qa["issues"]))
    if rebuilt:
        expected.parent.mkdir(parents=True, exist_ok=True)
        destination = expected
        if destination.exists():
            base, job_number = expected.stem.rsplit("+", 1)
            version = 2
            while True:
                versioned = expected.with_name(f"{base}+v{version}+{job_number}.docx")
                if not versioned.exists():
                    destination = versioned
                    break
                version += 1
        os.replace(candidate, destination)
        final = destination
        existing = False
    return Artifacts(final, listing, existing, attempts)


def record_success(item: QueueRow, artifacts: Artifacts, tracker: GoogleTracker) -> None:
    """Record the validated resume through the canonical tracker integration."""
    if not artifacts.resume.is_file() or artifacts.resume.stat().st_size <= 0:
        raise ValueError("Final DOCX is missing or empty")
    if not (_still_pending(tracker, item)
            or _still_pending(tracker, item, link_backfill=True)):
        raise RuntimeError("Apply? or Resume Created changed before tracker update")
    _retry_sheet(lambda: manage_job_tracker.record_queue_success(
        artifacts.resume, artifacts.listing, item.scout_id, item.row, tracker,
        completion_marker=COMPLETION_MARKER,
        require_approved=not _resume_completed(
            (item.fields or {}).get("Resume Created")
        ),
    ))


def record_local_success(item: QueueRow, artifacts: Artifacts, tracker: GoogleTracker) -> None:
    """Record a validated resume using its absolute local DOCX path."""
    if not artifacts.resume.is_file() or artifacts.resume.stat().st_size <= 0:
        raise ValueError("Final local DOCX is missing or empty")
    if not (_still_pending(tracker, item)
            or _still_pending(tracker, item, link_backfill=True)):
        raise RuntimeError("Apply? or Resume Created changed before tracker update")
    completed_backfill = _resume_completed((item.fields or {}).get("Resume Created"))
    _retry_sheet(lambda: manage_job_tracker.record_queue_success_local(
        artifacts.resume, artifacts.listing, item.scout_id, item.row, tracker,
        require_approved=not completed_backfill,
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
    source: str | None = None,
    auto_approve_geographic: bool = False,
    generator=generate,
    existing_generator=recreate,
    recorder=None,
    failure_recorder=manage_job_tracker.record_queue_failure,
    logger=None,
    print_summary: bool = True,
) -> QueueRunResult:
    recorder = recorder or record_success
    snapshot = read_queue(
        tracker, eligible_scout_ids, source,
        auto_approve_geographic=auto_approve_geographic,
    )

    # Source-specific Indeed runs and the all-source daily workflow normalize
    # matching Utah/remote rows to Apply? = Yes, including preexisting rows.
    # Nonqualifying rows and unrelated cells are never changed.
    apply_values_set = 0
    if (source == "indeed" or auto_approve_geographic) and not dry_run:
        all_items = {
            item.row: item
            for group in (
                snapshot.pending, snapshot.already_created, snapshot.not_approved,
                snapshot.link_backfill, snapshot.duplicate_excluded,
                snapshot.missing_identity, snapshot.cost_excluded,
            )
            for item in group
        }
        for item in all_items.values():
            if (_flag((item.fields or {}).get("Cost")) != "x"
                    and _geographic_qualification(item)
                    and _flag((item.fields or {}).get("Apply?")) != "yes"):
                _retry_sheet(lambda item=item: tracker.approve_manual_scout_row(
                    item.row, company=item.company, title=item.title,
                ))
                apply_values_set += 1
        if apply_values_set:
            snapshot = read_queue(
                tracker, eligible_scout_ids, source,
                auto_approve_geographic=auto_approve_geographic,
            )
    pending = snapshot.pending
    backfill = snapshot.link_backfill
    work = pending + backfill
    skipped = snapshot.already_created
    excluded = (len(snapshot.already_created) + len(snapshot.not_approved)
                + len(snapshot.jooble_excluded) + len(snapshot.duplicate_excluded)
                + len(snapshot.missing_identity) + len(snapshot.cost_excluded))
    checked = (len(snapshot.pending) + len(snapshot.already_created) + len(snapshot.link_backfill)
               + len(snapshot.not_approved) + len(snapshot.jooble_excluded)
               + len(snapshot.duplicate_excluded) + len(snapshot.missing_identity)
               + len(snapshot.cost_excluded))
    created = recovered = 0
    successes: list[tuple[QueueRow, Artifacts]] = []
    changed = 0
    scout_ids_assigned = 0
    failed: list[QueueFailure] = []

    def capture_failure(failed_item: QueueRow, error: Exception) -> None:
        if isinstance(error, DescriptionUnavailableError):
            failure = QueueFailure(
                item=failed_item,
                reason=error.result.error or str(error),
                original_url=error.original_url,
                authoritative_url=error.result.authoritative_url,
                attempts=tuple(error.result.attempts),
            )
        elif isinstance(error, QueueProcessingError):
            failure = QueueFailure(
                item=failed_item,
                reason=str(error),
                original_url=error.original_url,
                authoritative_url=error.authoritative_url,
                attempts=error.attempts,
            )
        else:
            failure = QueueFailure(
                item=failed_item, reason=str(error), original_url=failed_item.job_url,
                authoritative_url="",
            )
        failed.append(failure)
        try:
            _retry_sheet(lambda: failure_recorder(
                failed_item.scout_id, failed_item.row, failure.reason, tracker,
            ))
        except Exception as note_error:
            failure = QueueFailure(
                item=failure.item,
                reason=f"{failure.reason} (Notes update also failed: {note_error})",
                original_url=failure.original_url,
                authoritative_url=failure.authoritative_url,
                attempts=failure.attempts,
            )
            failed[-1] = failure
        print(f"FAILED: {failed_item.company}  {failed_item.title}", file=sys.stderr, flush=True)
        print(f"Reason: {failure.reason}", file=sys.stderr, flush=True)
        _log(logger, f"FAIL row={failed_item.row} scout_id={failed_item.scout_id} reason={failure.reason}")
        for attempt in failure.attempts:
            _log(logger, "  " + attempt.summary())

    print(f"Found {len(pending)} jobs requiring resumes.", flush=True)
    print(f"Found {len(backfill)} completed jobs requiring Resume Link backfill.", flush=True)
    print(f"Tracker rows checked: {checked}", flush=True)
    print(f"Skipped with a completed Resume Created marker: {len(skipped)}", flush=True)
    _log(logger, f"Eligible rows: {len(pending)}; already marked: {len(skipped)}")
    if dry_run:
        print("Dry-run row diagnostics:", flush=True)
        for item, decision in snapshot.decisions:
            print(f"Row {item.row} | {item.company} | {item.title} | {decision}", flush=True)
    print("Row | Scout ID | Company | Job title", flush=True)
    for item in work:
        print(f"{item.row} | {item.scout_id or ''} | {item.company} | {item.title}", flush=True)
    if not dry_run:
        print("Processing eligible jobs now.", flush=True)
    backfill_rows = {item.row for item in backfill}

    # Prepare every manual row before the slower Word generation phase. This
    # prevents an interruption or one generation failure from leaving later
    # qualifying rows without Apply? or a durable Scout ID.
    if source == "indeed" and not dry_run:
        prepared_work: list[QueueRow] = []
        allocator = None
        try:
            if any(item.scout_id is None for item in work):
                allocator = _BatchScoutIdAllocator.from_live_state(tracker, db)
        except Exception as error:
            # Existing-ID rows can still be processed; blank-ID rows report an
            # isolated preparation failure below.
            _log(logger, f"Scout ID allocator initialization failed: {error}")
        for original in work:
            try:
                if original.row in backfill_rows:
                    prepared = _refresh_item(tracker, original)
                    if prepared.scout_id is None:
                        raise RuntimeError("Completed resume link backfill has no Scout ID")
                    prepared_work.append(prepared)
                    continue
                if original.scout_id is None and allocator is None:
                    raise RuntimeError("Scout ID allocator could not be initialized")
                prepared = _prepare_indeed_item(tracker, original, db, allocator)
                if original.scout_id is None and prepared.scout_id is not None:
                    scout_ids_assigned += 1
                prepared_work.append(prepared)
            except Exception as error:
                capture_failure(original, error)
        work = prepared_work

    for index, item in enumerate(work, 1):
        try:
            # A dry run is a single read-only snapshot. Re-reading every row adds
            # API traffic and is unnecessary because no lifecycle write follows.
            is_backfill = item.row in backfill_rows
            if dry_run:
                action = ("WOULD RECREATE | WOULD WRITE RESUME LINK | KEEP RESUME CREATED = X"
                          if is_backfill else
                          "WOULD CREATE | WOULD WRITE RESUME LINK | WOULD MARK RESUME CREATED = X")
                print(f"[{index}/{len(work)}] Row {item.row} | {item.company} | "
                      f"{item.title} | {action}")
                continue
            if not _still_pending(tracker, item, link_backfill=is_backfill):
                print(f"SKIP: row {item.row} (Scout ID {item.scout_id}): queue flags changed")
                changed += 1
                continue
            action = "Recreating Gecko resume" if is_backfill else "Creating Gecko resume"
            print(f"[{index}/{len(work)}] {action}: {item.company}  {item.title}", flush=True)
            if is_backfill:
                artifacts = existing_generator(item, db)
            else:
                artifacts = generator(item, db)
            recorder(item, artifacts, tracker)
            recovered += int(artifacts.existing)
            created += int(not artifacts.existing)
            successes.append((item, artifacts))
            print(f"Resume created: {artifacts.resume}", flush=True)
            print(f"Updated Gecko Job Tracker row {item.row}: Resume Created = {COMPLETION_MARKER}", flush=True)
            _log(logger, f"SUCCESS row={item.row} scout_id={item.scout_id} "
                 f"resume={artifacts.resume}")
            for attempt in artifacts.retrieval_attempts:
                _log(logger, "  " + attempt.summary())
        except Exception as error:
            capture_failure(item, error)
    if dry_run:
        remaining = work
    else:
        refreshed = read_queue(
            tracker, eligible_scout_ids, source,
            auto_approve_geographic=auto_approve_geographic,
        )
        remaining = refreshed.pending + refreshed.link_backfill
    failed_rows = {failure.item.row for failure in failed}
    unexpected = [] if dry_run else [item for item in remaining if item.row not in failed_rows]
    result = QueueRunResult(
        snapshot=snapshot, successes=successes, failures=failed, created=created,
        recovered=recovered, changed=changed, apply_values_set=apply_values_set,
        scout_ids_assigned=scout_ids_assigned, resume_links_written=len(successes),
        rows_marked_created=len(successes), unexpected=tuple(unexpected),
        dry_run=dry_run,
    )
    if print_summary:
        print("\nGecko Resume Queue Complete")
        print(f"Tracker rows checked: {checked}")
        print(f"Eligible jobs: {len(work)}")
        print(f"New resumes eligible: {len(pending)}")
        print(f"Repair rows eligible: {len(backfill)}")
        print(f"Completed rows skipped: {len(skipped)}")
        print(f"Cost-excluded rows: {len(snapshot.cost_excluded)}")
        print(f"Skipped: {excluded + changed}")
        print(f"Resumes created: {created + recovered}")
        print(f"Existing valid resumes discovered and marked: {recovered}")
        print(f"Processed: {len(successes) + len(failed) + changed}")
        print(f"Apply? values auto-set: {apply_values_set}")
        print(f"Scout IDs assigned: {scout_ids_assigned}")
        print(f"Resume Links written: {len(successes)}")
        print(f"Rows marked Resume Created: {len(successes)}")
        print(f"Failed: {len(failed)}")
        print(f"Google Sheet rows updated: {len(successes)}")
        print(f"Rows marked {COMPLETION_MARKER}: " + (
            ", ".join(str(item.row) for item, _ in successes) or "none"
        ))
        print(f"Remaining eligible rows: {len(remaining)}; unexpected: {len(unexpected)}")
        if dry_run:
            print(f"Would process: {len(work)}")
        if source == "indeed":
            stats = snapshot.stats
            print("\nIndeed workflow totals")
            print(f"Indeed rows checked: {stats['indeed_rows_checked']}")
            print(f"Utah qualifying: {stats['utah_qualifying']}")
            print(f"Remote qualifying: {stats['remote_qualifying']}")
            print(f"Would set Apply? = Yes: {stats['would_set_apply_yes']}")
            print(f"Already approved: {stats['already_approved']}")
            print(f"Explicitly declined: {stats['explicitly_declined']}")
            print(f"Other explicit Apply? values: {stats['explicit_manual_values']}")
            print(f"Outside Utah/non-remote: {stats['outside_utah_non_remote']}")
            print(f"Would assign Scout ID: {stats['would_assign_scout_id']}")
            print(f"Eligible for Gecko resume: {stats['eligible_for_resume']}")
            print(f"Already completed: {stats['already_completed']}")
            print(f"Repair eligible: {stats['repair_eligible']}")
            print(f"Cost-excluded: {stats['cost_excluded']}")
            print(f"Missing usable Job URL/listing: {stats['missing_usable_listing']}")
            print(f"Duplicate exclusions: {stats['duplicate_exclusions']}")
            print(f"Would process: {len(work)}")
    return result


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
    parser.add_argument(
        "--source", choices=("indeed",),
        help=("Process this source, including Indeed Utah/remote approval, "
              "resume generation, and completion repair"),
    )
    parser.add_argument("--dry-run", action="store_true", help="Show queue decisions without generating or writing")
    args = parser.parse_args()
    logger = None if args.dry_run else _append_run_log
    if logger is not None:
        logger(f"RUN START dry_run={args.dry_run} source={args.source or 'all'} db={args.db.resolve()}")
    result = run_queue(
        GoogleTracker(), args.db.resolve(), dry_run=args.dry_run, source=args.source,
        logger=logger,
    )
    if logger is not None:
        logger(f"RUN END exit_code={result.exit_code}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
