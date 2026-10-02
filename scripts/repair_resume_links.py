"""Replace legacy "Open Resume" formulas with verified visible file URIs."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))

from google_tracker import (  # noqa: E402
    Config,
    GoogleTracker,
    verified_resume_file_uri,
    verified_resume_uri_target,
)

RESUME_DIR = ROOT / "output" / "resumes"
OPEN_RESUME_FORMULA = re.compile(
    r'^=HYPERLINK\(\s*"((?:[^"]|"")+)"\s*,\s*"Open Resume"\s*\)$',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Repair:
    row: int
    uri: str
    resume: str
    source: str


@dataclass(frozen=True)
class Unresolved:
    row: int
    reason: str


def _value(row: tuple[object, ...], column: int) -> str:
    return str(row[column - 1] if column <= len(row) else "").strip()


def _formula_target(formula: str) -> str:
    match = OPEN_RESUME_FORMULA.fullmatch(formula.strip())
    return match.group(1).replace('""', '"') if match else ""


def _job_identifiers(data: dict[str, object], formula_target: str) -> set[str]:
    identifiers: set[str] = set()
    url = str(data.get("Job URL") or "").strip()
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    for key in ("jk", "gh_jid"):
        identifiers.update(value.strip() for value in query.get(key, []) if value.strip())
    path = unquote(parsed.path)
    for pattern in (
        r"/(?:details|ad)/(\d+)(?:/|$)",
        r"/jobs/(\d+)(?:[-/]|$)",
        r"/([0-9a-f]{8}-[0-9a-f-]{27,}|[0-9a-f]{16,}|\d{6,})(?:/|$)",
    ):
        identifiers.update(re.findall(pattern, path, re.IGNORECASE))
    if formula_target:
        name = Path(unquote(urlsplit(formula_target).path)).name
        if name.casefold().endswith(".docx") and "+" in name:
            identifiers.add(name[:-5].rsplit("+", 1)[-1])
    scout_id = str(data.get("Scout ID") or "").strip()
    if scout_id:
        identifiers.add(f"scout-{scout_id}")
    return {value.casefold().lstrip("-") for value in identifiers if value}


def _normalized(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _resolve_from_metadata(
    data: dict[str, object], formula_target: str, resumes: list[Path],
) -> tuple[Path | None, str]:
    if formula_target:
        parsed = urlsplit(formula_target)
        if parsed.scheme.casefold() == "file":
            try:
                return Path(unquote(parsed.path).lstrip("/")).resolve(), "formula"
            except (OSError, ValueError):
                pass
        expected_name = Path(unquote(parsed.path)).name.casefold()
        exact_name = [path for path in resumes if path.name.casefold() == expected_name]
        if len(exact_name) == 1:
            return exact_name[0], "formula-filename"

    identifiers = _job_identifiers(data, formula_target)
    by_id = [
        path for path in resumes
        if path.stem.rsplit("+", 1)[-1].casefold().lstrip("-") in identifiers
    ]
    if len(by_id) == 1:
        return by_id[0], "job-identifier"
    candidates = by_id or resumes
    company = _normalized(data.get("Company"))
    title = _normalized(data.get("Job Title"))
    by_identity = [
        path for path in candidates
        if company and title and company in _normalized(path.stem) and title in _normalized(path.stem)
    ]
    if len(by_identity) == 1:
        return by_identity[0], "company-title"
    if len(by_id) > 1:
        return None, f"multiple resumes match job identifier: {', '.join(path.name for path in by_id)}"
    if len(by_identity) > 1:
        return None, f"multiple resumes match company/title: {', '.join(path.name for path in by_identity)}"
    return None, "no unique resume matched the formula, job identifier, company, and title"


def plan_repairs(tracker: GoogleTracker) -> tuple[int, int, list[Repair], list[Unresolved]]:
    formulas = tracker.scout(value_render_option="FORMULA")
    displayed = tracker.scout(value_render_option="FORMATTED_VALUE")
    if formulas.headers.get("Resume Link") != 17:
        raise RuntimeError("Configured intake worksheet does not have Resume Link in Column Q")
    display_rows = dict(displayed.raw_rows or {})
    resumes = sorted(RESUME_DIR.resolve().glob("*.docx"), key=lambda path: path.name.casefold())
    repairs: list[Repair] = []
    unresolved: list[Unresolved] = []
    found = 0
    for row, data in formulas.rows:
        shown = _value(display_rows.get(row, ()), formulas.headers["Resume Link"])
        if shown != "Open Resume":
            continue
        found += 1
        formula = str(data.get("Resume Link") or "")
        target = _formula_target(formula)
        path, source = _resolve_from_metadata(data, target, resumes)
        if path is None:
            unresolved.append(Unresolved(row, source))
            continue
        try:
            uri = verified_resume_file_uri(path)
        except (OSError, ValueError) as error:
            unresolved.append(Unresolved(row, str(error)))
            continue
        repairs.append(Repair(row, uri, path.name, source))
    return len(formulas.rows), found, repairs, unresolved


def apply_repairs(tracker: GoogleTracker, repairs: list[Repair]) -> None:
    if not repairs:
        return
    data = [
        {"range": f"'{tracker.config.scout_tab.replace(chr(39), chr(39) * 2)}'!Q{item.row}",
         "values": [[item.uri]]}
        for item in repairs
    ]
    tracker.api.values().batchUpdate(
        spreadsheetId=tracker.config.spreadsheet_id,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()


def verify_repairs(tracker: GoogleTracker, repairs: list[Repair]) -> list[Unresolved]:
    formulas = tracker.scout(value_render_option="FORMULA")
    displayed = tracker.scout(value_render_option="FORMATTED_VALUE")
    formula_rows = dict(formulas.raw_rows or {})
    display_rows = dict(displayed.raw_rows or {})
    failures: list[Unresolved] = []
    for item in repairs:
        formula_value = _value(formula_rows.get(item.row, ()), formulas.headers["Resume Link"])
        display_value = _value(display_rows.get(item.row, ()), displayed.headers["Resume Link"])
        try:
            canonical = verified_resume_uri_target(formula_value)
        except (OSError, ValueError) as error:
            failures.append(Unresolved(item.row, f"post-write URI verification failed: {error}"))
            continue
        if canonical != item.uri or display_value != item.uri:
            failures.append(Unresolved(item.row, "post-write formula/display value does not equal expected URI"))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="plan repairs without writing Google Sheets")
    mode.add_argument("--apply", action="store_true", help="write and verify repairs (the default)")
    parser.add_argument("--report", type=Path, help="optional JSON report path")
    args = parser.parse_args()
    apply_live = not args.dry_run
    tracker = GoogleTracker(Config.from_environment())
    inspected, found, repairs, unresolved = plan_repairs(tracker)
    verification: list[Unresolved] = []
    if apply_live:
        apply_repairs(tracker, repairs)
        verification = verify_repairs(tracker, repairs)
    result = {
        "worksheet": tracker.config.scout_tab,
        "column": "Q",
        "rows_inspected": inspected,
        "open_resume_found": found,
        "updated": len(repairs) if apply_live else 0,
        "repairable": len(repairs),
        "unresolved": [asdict(item) for item in unresolved],
        "verification_failures": [asdict(item) for item in verification],
        "verified": len(repairs) - len(verification) if apply_live else 0,
        "applied": apply_live,
    }
    text = json.dumps(result, indent=2)
    print(text)
    if args.report:
        report = args.report if args.report.is_absolute() else ROOT / args.report
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(text + "\n", encoding="utf-8")
    return 1 if unresolved or verification else 0


if __name__ == "__main__":
    raise SystemExit(main())
