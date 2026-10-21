"""Gecko Job Tracker contract. Discover tabs and resolve named headers.

The header snapshot documents the workbook observed on 2026-10-20. Runtime
operations must read current metadata and headers; snapshots are not write maps.
"""

from __future__ import annotations

WORKBOOK_TITLE = "Gecko Job Tracker"
SCOUT_TAB = "Job List"
DAILY_TASKS_TAB = "Daily Tasks"
DAILY_RUN_TAB = "Daily Run"  # New blocks insert at row 3; older history is preserved.
SCRATCH_TAB = "Scratch"  # User research ideas; mirror docs/scratch-column-ideas.md, no writer.
DELETED_JOBS_TAB = "Deleted Jobs"
REJECTED_TAB = "Rejected Jobs"
REQUIRED_TABS = (SCOUT_TAB, REJECTED_TAB)
OPTIONAL_TABS = (DAILY_TASKS_TAB, DAILY_RUN_TAB, DELETED_JOBS_TAB)
OBSERVED_TABS = (DAILY_TASKS_TAB, DAILY_RUN_TAB, SCOUT_TAB,
                 DELETED_JOBS_TAB, SCRATCH_TAB, REJECTED_TAB)
LEGACY_APPLICATION_TAB = "Job Tracker"  # Only for explicitly configured older workbooks.

INDEED_APPLICATION_HEADER = "Apply or on Company Website (If Indeed)"
LAST_RUN_HEADER = "Last Updated"  # Last actual Firecrawl/Gecko run, America/Denver.
LEGACY_SCOUT_HEADERS = (
    "ID", "Source", "Company", "Job Title", "Apply?",
    "Resume Created", "Applied", "Cost", LAST_RUN_HEADER, "Notes", INDEED_APPLICATION_HEADER,
    "Response", "Location", "Work Arrangement", "Employment Type", "Salary",
    "Job URL", "Resume Link", "Date Posted", "Date Found", "Last Seen",
)
CURRENT_SCOUT_HEADERS = (
    'ID',
    'Company',
    'Job Title',
    'Applied',
    'Applied Date',
    'Source',
    'Qualifies to Apply?',
    'Cover Letter',
    'CV Created Date',
    'Create Resume',
    'Resume Created',
    'Cost',
    'Previous Notes',
    'Apply or on Company Website (If Indeed)',
    'Response',
    'Location',
    'Work Arrangement',
    'Employment Type',
    'Salary',
    'Job URL',
    'Resume Link',
    'Resume Created Date',
    'Cover Letter Link',
    'Cover Letter Created Date',
    'Last Updated',
    'Date Posted',
    'Date Found',
    'Last Seen',
    'Personal priority',
    'Previous Applied Date',
    'Notes',
    'Job Description',
    'Enough Data',
    '# Words',
    '# Job Desc Words',
    'Total Words',
)

SCOUT_HEADER_ALIASES = {
    "Scout ID": ("ID", "Scout ID"),
    "Apply?": ("Qualifies to Apply?", "Qualifies", "Apply?", "Apply"),
}
SCOUT_FIELDS = (
    "Scout ID", "Source", "Company", "Job Title",
    "Location", "Work Arrangement", "Employment Type", "Salary", "Date Posted",
    "Date Found", "Last Seen", "Job URL", "Resume Link",
    INDEED_APPLICATION_HEADER,
)
PROTECTED_SCOUT_FIELDS = (
    "Apply?", "Resume Created", "Applied", "Cost", LAST_RUN_HEADER, "Notes", "Contacted", "Response",
)
RETIRED_SCOUT_HEADERS = (
    "Website", "Enrichment URL", "URL Status", "Authoritative URL",
)
REJECTED_HEADERS = (
    "Source", "Job ID", "Original Job URL", "Normalized Job URL",
    "Company", "Job Title", "Date Rejected", "Reason or Status",
)
REJECT_STATUSES = frozenset({"reject", "delete / reject", "delete/reject"})
RESUME_COMPLETION_MARKER = "X"
LEGACY_RESUME_MARKERS = frozenset({"x", "c"})
COST_EXCLUSION_MARKER = "x"
INDEED_EXPIRED_TEXTS = frozenset({"this job has expired on indeed", "expired"})
STATUS_LABELS = {
    "new": "New", "reviewing": "Reviewing", "selected": "Selected",
    "resume-created": "Resume Created", "applied": "Applied",
    "contacted": "Contacted", "interview": "Interview", "rejected": "Rejected",
    "ignored": "Ignored", "offer": "Offer",
}
STATUS_RANKS = {name: rank for rank, name in enumerate(STATUS_LABELS.values())}


def header_key(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def discover_tabs(properties: list[dict], *, required=REQUIRED_TABS) -> dict[str, dict]:
    """Classify live tabs without assigning behavior to unknown names."""
    tabs: dict[str, dict] = {}
    ids: set[int] = set()
    for prop in properties:
        title = str(prop.get("title") or "")
        sheet_id = prop.get("sheetId")
        if not title or title in tabs or sheet_id is None or sheet_id in ids:
            raise RuntimeError("Google workbook has missing or duplicate tab title/ID")
        ids.add(sheet_id)
        tabs[title] = {"sheet_id": sheet_id,
                       "role": ("required" if title in REQUIRED_TABS else
                                "optional" if title in OPTIONAL_TABS else "unassigned"),
                       "hidden": bool(prop.get("hidden", False)),
                       "grid": prop.get("gridProperties", {})}
    missing = sorted(set(required) - tabs.keys())
    if missing:
        raise RuntimeError("Google workbook is missing required tabs: " + ", ".join(missing))
    return tabs


def resolve_headers(names: list[str] | tuple[str, ...], *, required=()) -> dict[str, int]:
    """Map semantic fields to 1-based columns and reject silent schema drift."""
    nonblank = [(str(name).strip(), column) for column, name in enumerate(names, 1)
                if str(name).strip()]
    keys = [header_key(name) for name, _ in nonblank]
    if len(keys) != len(set(keys)):
        raise RuntimeError("Google worksheet has duplicate or ambiguous headers")
    headers = dict(nonblank)
    for canonical, aliases in SCOUT_HEADER_ALIASES.items():
        matches = [(name, column) for name, column in nonblank
                   if header_key(name) in {header_key(alias) for alias in aliases}]
        if len(matches) > 1:
            raise RuntimeError(f"Google worksheet has ambiguous header for {canonical!r}")
        if matches:
            headers[canonical] = matches[0][1]
    missing = sorted(set(required) - headers.keys())
    if missing:
        raise RuntimeError("Google worksheet is missing required headers: " + ", ".join(missing))
    return headers
