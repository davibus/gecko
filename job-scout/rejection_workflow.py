"""Archive explicitly rejected Scout rows before removing them from the visible tab."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from google_tracker import GoogleTracker, _normal
from rejected_jobs import REJECT_STATUSES, rejection_record
from storage import JobStore


@dataclass
class RejectionSummary:
    marked: int = 0
    archived: int = 0
    removed: int = 0
    support_rows: list[int] = field(default_factory=list)
    removed_rows: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "marked": self.marked,
            "archived": self.archived,
            "removed": self.removed,
            "support_rows": list(self.support_rows),
            "removed_rows": list(self.removed_rows),
        }


def _scout_id(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


def _fingerprint(data: dict[str, object]) -> tuple[str, ...]:
    return tuple(str(data.get(name) or "").strip() for name in (
        "Scout ID", "Source", "Company", "Job Title", "Apply?", "Job URL",
    ))


def process_rejected_rows(
    tracker: GoogleTracker,
    store: JobStore,
    *,
    today: str | None = None,
) -> RejectionSummary:
    """Archive every explicit Reject row, verify storage, then delete exact visible rows."""
    tracker.rejected_jobs(create=True)
    tab = tracker.scout(value_render_option="FORMULA")
    targets = [
        (row, data) for row, data in tab.rows
        if _normal(data.get("Apply?")) in REJECT_STATUSES
    ]
    summary = RejectionSummary(marked=len(targets))
    if not targets:
        return summary

    rejected_on = today or date.today().isoformat()
    expected = {row: _fingerprint(data) for row, data in targets}
    records = []
    for row, data in targets:
        job = store.get(_scout_id(data.get("Scout ID"))) if _scout_id(data.get("Scout ID")) else None
        source = job.source if job else data.get("Source")
        job_id = job.source_job_id if job else ""
        url = data.get("Job URL") or (job.url if job else "")
        reason = data.get("Notes") or data.get("Apply?") or "Reject"
        record = rejection_record(
            source=source,
            job_id=job_id,
            url=url,
            company=data.get("Company") or (job.company if job else ""),
            title=data.get("Job Title") or (job.title if job else ""),
            date_rejected=rejected_on,
            reason=reason,
        )
        records.append(record)
    # This call returns only after the entire batch is read back and verified.
    # A failure here intentionally prevents any deletion of the visible rows.
    summary.support_rows = tracker.append_rejected_jobs(records)

    refreshed = tracker.scout(value_render_option="FORMULA")
    current = dict(refreshed.rows)
    changed = [row for row, fingerprint in expected.items()
               if row not in current or _fingerprint(current[row]) != fingerprint]
    if changed:
        raise RuntimeError(
            "Reject-marked rows changed before deletion; no visible row was deleted: "
            + ", ".join(map(str, changed))
        )
    summary.archived = len(records)
    summary.removed_rows = tracker.delete_scout_rows(
        list(expected), expected_fingerprints=expected,
    )
    summary.removed = len(summary.removed_rows)
    remaining = {_fingerprint(data) for _, data in tracker.scout().rows}
    failed = [row for row, fingerprint in expected.items() if fingerprint in remaining]
    if failed:
        raise RuntimeError(
            "Rejected Job Scout row deletion verification failed: "
            + ", ".join(map(str, failed))
        )
    return summary
