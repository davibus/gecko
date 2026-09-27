"""Manual Indeed URL intake for existing Job Scout worksheet rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re
from urllib.parse import urlsplit

from google_tracker import GoogleTracker, Tab
from normalize import canonicalize_url, normalize
from sources.base import ProviderError
from sources.indeed import (
    ManualIndeedProvider,
    canonical_indeed_url,
    extract_indeed_job_key,
)
from storage import JobStore


DUPLICATE_PREFIX = "Duplicate —"
RETRIEVAL_FAILURE = "Indeed retrieval failed — manual review required"


@dataclass(frozen=True)
class DuplicateReference:
    scout_id: int | None = None
    row: int | None = None
    reason: str = ""

    def message(self) -> str:
        target = f"Scout ID {self.scout_id}" if self.scout_id is not None else f"row {self.row}"
        return f"{DUPLICATE_PREFIX} {target} ({self.reason})"


@dataclass
class ManualIndeedSummary:
    scanned: int = 0
    processed: int = 0
    duplicates: int = 0
    failures: int = 0
    skipped: int = 0
    new_job_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "processed": self.processed,
            "duplicates": self.duplicates,
            "failures": self.failures,
            "skipped": self.skipped,
            "new_job_ids": list(self.new_job_ids),
        }


def is_indeed_url(url: str) -> bool:
    try:
        host = (urlsplit(str(url or "").strip()).hostname or "").casefold().rstrip(".")
    except ValueError:
        return False
    return host == "indeed.com" or host.endswith(".indeed.com")


def _identity_text(value: object) -> str:
    """Normalize case, whitespace, and harmless punctuation for exact identity checks."""
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _identity(company: object, title: object, location: object) -> tuple[str, str, str] | None:
    result = tuple(_identity_text(value) for value in (company, title, location))
    return result if all(result) else None


def _scout_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value or "").strip()
    match = re.fullmatch(r"(?:JS-)?(\d+)", text, re.I)
    return int(match.group(1)) if match and int(match.group(1)) > 0 else None


def next_scout_id(tab: Tab, store: JobStore) -> int:
    """Allocate above every Sheet and SQLite ID, independent of physical row order."""
    sheet_ids = [_scout_id(data.get("Scout ID")) for _, data in tab.rows]
    return max([0, store.highest_scout_id(),
                *(value for value in sheet_ids if value is not None)]) + 1


def _canonical_record_url(url: object) -> str:
    value = str(url or "").strip()
    return canonical_indeed_url(value) or canonicalize_url(value)


def _sheet_duplicate(
    tab: Tab,
    *,
    current_row: int,
    jk: str,
    url: str,
    identity: tuple[str, str, str] | None = None,
) -> DuplicateReference | None:
    canonical = _canonical_record_url(url)
    for row, data in tab.rows:
        if row == current_row:
            continue
        existing_id = _scout_id(data.get("Scout ID"))
        existing_identity = _identity(data.get("Company"), data.get("Job Title"), data.get("Location"))
        # A URL-only row later in the Sheet is another pending intake, not the original record.
        established = existing_id is not None or existing_identity is not None
        if not established:
            continue
        existing_url = str(data.get("Job URL") or "")
        existing_jk = extract_indeed_job_key(existing_url)
        if jk and existing_jk and jk.casefold() == existing_jk.casefold():
            return DuplicateReference(existing_id, row, "Indeed JK already exists")
        if canonical and canonical == _canonical_record_url(existing_url):
            return DuplicateReference(existing_id, row, "canonical job URL already exists")
        if identity and existing_identity == identity:
            return DuplicateReference(existing_id, row, "company/title/location already exists")
    return None


def _store_duplicate(
    store: JobStore,
    *,
    jk: str,
    url: str,
    identity: tuple[str, str, str] | None = None,
) -> DuplicateReference | None:
    canonical = _canonical_record_url(url)
    for job in store.all():
        source_ids = {
            str(job.source_job_id or "").casefold()
            if job.source.casefold() == "indeed" else "",
            *(str(link.get("source_job_id") or "").casefold()
              for link in job.source_links
              if str(link.get("source") or "").casefold() == "indeed"),
        }
        if jk and jk.casefold() in source_ids:
            return DuplicateReference(job.id, reason="Indeed JK already exists")
        urls = {job.url, job.canonical_url, job.authoritative_url,
                *(str(link.get("url") or "") for link in job.source_links)}
        if canonical and any(canonical == _canonical_record_url(item) for item in urls if item):
            return DuplicateReference(job.id, reason="canonical job URL already exists")
        if identity and _identity(job.company, job.title, job.location) == identity:
            return DuplicateReference(job.id, reason="company/title/location already exists")
    return None


def _find_duplicate(
    tab: Tab,
    store: JobStore,
    *,
    current_row: int,
    jk: str,
    url: str,
    identity: tuple[str, str, str] | None = None,
) -> DuplicateReference | None:
    return (_sheet_duplicate(
        tab, current_row=current_row, jk=jk, url=url, identity=identity,
    ) or _store_duplicate(store, jk=jk, url=url, identity=identity))


def _terminal_note(value: object) -> bool:
    text = str(value or "").strip()
    return text.startswith(DUPLICATE_PREFIX) or text.startswith(RETRIEVAL_FAILURE)


def _status_update(tab: Tab, message: str) -> dict[str, str]:
    """Prefer Notes, with the existing Gecko Status column as a minimal fallback."""
    return {"Notes": message} if "Notes" in tab.headers else {"Gecko Status": message}


def process_manual_indeed_rows(
    tracker: GoogleTracker,
    store: JobStore,
    *,
    provider: ManualIndeedProvider | None = None,
    today: str | None = None,
) -> ManualIndeedSummary:
    """Process unassigned Indeed URLs already pasted into the Job URL column."""
    provider = provider or ManualIndeedProvider()
    found_on = today or date.today().isoformat()
    tab = tracker.scout()
    summary = ManualIndeedSummary()

    for row, data in tab.rows:
        pasted_url = str(data.get("Job URL") or "").strip()
        if not is_indeed_url(pasted_url):
            continue
        summary.scanned += 1
        if (_scout_id(data.get("Scout ID")) is not None
                or _terminal_note(data.get("Notes"))
                or _terminal_note(data.get("Gecko Status"))):
            summary.skipped += 1
            continue

        jk = extract_indeed_job_key(pasted_url)
        duplicate = _find_duplicate(
            tab, store, current_row=row, jk=jk, url=pasted_url,
        )
        if duplicate:
            message = duplicate.message()
            update = _status_update(tab, message)
            tracker.update_manual_scout_row(tab, row, update)
            data.update(update)
            summary.duplicates += 1
            continue

        try:
            raw = provider.retrieve(pasted_url)
            job = normalize(raw, discovered=found_on)
        except (ProviderError, OSError, ValueError, UnicodeError) as error:
            message = f"{RETRIEVAL_FAILURE}: {error}"
            update = _status_update(tab, message)
            tracker.update_manual_scout_row(tab, row, update)
            data.update(update)
            summary.failures += 1
            continue

        duplicate = _find_duplicate(
            tab, store, current_row=row, jk=jk, url=pasted_url,
            identity=_identity(job.company, job.title, job.location),
        )
        if duplicate:
            message = duplicate.message()
            update = _status_update(tab, message)
            tracker.update_manual_scout_row(tab, row, update)
            data.update(update)
            summary.duplicates += 1
            continue

        scout_id = next_scout_id(tab, store)
        job.id = store.save(job, job_id=scout_id)
        values = {
            "Scout ID": scout_id,
            "Source": "indeed",
            "Company": job.company,
            "Job Title": job.title,
            "Gecko Status": "New",
            "Location": job.location,
            "Work Arrangement": job.work_arrangement,
            "Employment Type": job.employment_type,
            "Salary": job.salary,
            "Date Posted": job.date_posted,
            "Date Found": job.date_discovered,
            "Last Seen": job.last_seen,
        }
        tracker.update_manual_scout_row(tab, row, values)
        data.update(values)
        summary.processed += 1
        summary.new_job_ids.append(scout_id)

    return summary
