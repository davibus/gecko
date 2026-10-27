"""Read-only, one-job Gecko Main handoff for the OpenClaw application assistant."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
sys.path.insert(0, str(ROOT / "scripts"))

from google_tracker import GoogleTracker, verified_resume_uri_target  # noqa: E402
from rejected_jobs import REJECT_STATUSES, normalize_job_url  # noqa: E402
from tracker_schema import INDEED_APPLICATION_HEADER, REJECTED_TAB, resolve_headers  # noqa: E402
from sources.indeed import extract_indeed_job_key  # noqa: E402
from check_job_links import ThrottledFetcher, check_job_url  # noqa: E402
import resume_naming

QUEUE = ROOT / "openclaw" / "application-queue"
REQUIRED = ("Scout ID", "Source", "Company", "Job Title", "Apply?", "Resume Created",
            "Applied", "Cost", "Notes", "Job URL", "Resume Link", INDEED_APPLICATION_HEADER)
SECRET_QUERY = re.compile(r"(?:token|secret|password|passwd|api[_-]?key|auth|signature|session|credential)", re.I)
EXPIRED = {"expired", "this job has expired on indeed", "job no longer available"}
APPLIED = {"applied", "already applied", "application submitted", "submitted"}


class PackageBlocked(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def val(row: dict, key: str) -> str:
    return str(row.get(key) or "").strip()


def safe_url(raw: str) -> str:
    try:
        parts = urlsplit(raw.strip())
        host = (parts.hostname or "").casefold().rstrip(".")
        if (parts.scheme.casefold() != "https" or not host or parts.username or parts.password
                or parts.fragment or host == "localhost" or host.endswith(".local")
                or any(SECRET_QUERY.search(k) for k in re.findall(r"(?:^|&)([^=&]+)=", parts.query))):
            raise ValueError
        from sources.http import _validate_public_url
        _validate_public_url(raw)
    except Exception:
        raise PackageBlocked("invalid_application_url") from None
    return raw.strip()


def is_aggregator(url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    return any(host == item or host.endswith("." + item) for item in
               ("indeed.com", "linkedin.com", "glassdoor.com", "ziprecruiter.com",
                "monster.com", "jooble.org", "jobicy.com"))


def verify_application_url(url: str, company: str, title: str) -> str:
    url = safe_url(url)
    if is_aggregator(url):
        raise PackageBlocked("company_application_url_required")
    try:
        result = check_job_url(url, ThrottledFetcher(timeout=12, delay=0.8), retries=0)
    except Exception:
        raise PackageBlocked("application_url_unverified") from None
    final = safe_url(result.final_url or url)
    if is_aggregator(final) or result.status != "exists" or result.http_status != 200:
        raise PackageBlocked("application_url_unverified")
    # A successful HTTP response alone can be a generic careers page or a login page.
    from validate_job_list import identity_supported
    if not identity_supported(result, company, title):
        raise PackageBlocked("application_job_identity_unverified")
    return final


def resolve_resume(raw: str, root: Path = ROOT) -> Path:
    if not raw or raw.lstrip().startswith("="):
        raise PackageBlocked("missing_or_formula_resume_link")
    try:
        parts = urlsplit(raw.strip())
        if parts.scheme.casefold() == 'https' and root.resolve() == ROOT.resolve():
            from resume_delivery import local_path
            path = local_path(raw.strip())
            if path is None:
                raise ValueError
            return path
        if parts.scheme.casefold() != "file" or parts.netloc not in ("", "localhost") or parts.query or parts.fragment:
            raise ValueError
        local = unquote(parts.path)
        if re.fullmatch(r"/[A-Za-z]:/.*", local):
            local = local[1:]
        path = Path(local).resolve()
        resume_dir = (root / "output" / "resumes").resolve()
        if path.parent != resume_dir or path.suffix.casefold() != ".docx" or not path.is_file() or path.stat().st_size == 0:
            raise ValueError
        # Reuse Gecko's canonical URI check in the real checkout.
        if root.resolve() == ROOT.resolve():
            verified_resume_uri_target(raw.strip())
        return path
    except (ValueError, OSError):
        raise PackageBlocked("missing_or_invalid_resume") from None


def description_for(job_id: str, row: dict, root: Path = ROOT) -> tuple[Path, str]:
    folder = root / "input" / "job-descriptions"
    matches = []
    for path in folder.glob("*.md"):
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        if not re.search(rf"(?mi)^\s*-\s*\*\*Scout ID:\*\*\s*{re.escape(job_id)}\s*$", content):
            continue
        if val(row, "Company").casefold() not in content[:2500].casefold() or val(row, "Job Title").casefold() not in content[:2500].casefold():
            continue
        matches.append((path.resolve(), content))
    if len(matches) != 1:
        raise PackageBlocked("description_missing_or_ambiguous")
    path, content = matches[0]
    if path.parent != folder.resolve():
        raise PackageBlocked("invalid_description_path")
    number = re.search(r"(?mi)^\s*-\s*\*\*(?:Job Number|Job Key \(Indeed jk\)):\*\*\s*`?([^`\s]+)", content)
    return path, number.group(1) if number else path.stem.rsplit("+", 1)[-1]


def validate_resume_identity(path: Path, row: dict, job_number: str) -> None:
    name = path.stem
    parts = name.split("+")
    if len(parts) < 4 or parts[0] != "Dave-Call" or resume_naming.job_number(path).casefold() != job_number.casefold():
        raise PackageBlocked("resume_job_id_mismatch")
    def key(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.casefold())
    if key(parts[1]) != key(val(row, "Company")) or not key(parts[2]).startswith(key(val(row, "Job Title"))[:18]):
        raise PackageBlocked("resume_job_identity_mismatch")


def select_job(tab, job_id: str | None, physical_row: int | None) -> tuple[int, dict]:
    resolve_headers(tab.header_values, required=REQUIRED)
    if job_id is not None:
        hits = [(n, data) for n, data in tab.rows if val(data, "Scout ID") == job_id]
    else:
        hits = [(n, data) for n, data in tab.rows if n == physical_row]
    if len(hits) != 1:
        raise PackageBlocked("job_id_missing_or_duplicate")
    number, row = hits[0]
    if not val(row, "Scout ID") or (job_id is not None and val(row, "Scout ID") != job_id):
        raise PackageBlocked("unstable_job_id")
    return number, row


def prepare(tracker, *, job_id: str | None, physical_row: int | None,
            approved_job_id: str | None, company_url: str | None = None,
            root: Path = ROOT, url_verifier=verify_application_url) -> dict:
    if (job_id is None) == (physical_row is None):
        raise PackageBlocked("select_exactly_one_job")
    if not approved_job_id:
        raise PackageBlocked("preparation_not_approved")
    tabs = tracker.discover_workbook(required=(tracker.config.scout_tab, REJECTED_TAB))
    if tracker.config.scout_tab not in tabs:
        raise PackageBlocked("ledger_missing")
    tab = tracker.tab(tracker.config.scout_tab)
    number, row = select_job(tab, job_id, physical_row)
    stable = val(row, "Scout ID")
    if stable != approved_job_id:
        raise PackageBlocked("approved_job_id_mismatch")
    if physical_row is not None and number != physical_row:
        raise PackageBlocked("approved_row_mismatch")
    same_id = [(n, r) for n, r in tab.rows if val(r, "Scout ID") == stable]
    if len(same_id) != 1:
        raise PackageBlocked("duplicate_job_id")
    source, job_url = val(row, "Source"), val(row, "Job URL")
    if not source or not val(row, "Company") or not val(row, "Job Title"):
        raise PackageBlocked("missing_job_identity")
    status = val(row, INDEED_APPLICATION_HEADER)
    lifecycle = val(row, "Gecko Status") if "Gecko Status" in tab.headers else ""
    if (lifecycle.casefold() in REJECT_STATUSES or val(row, "Apply?").casefold() in REJECT_STATUSES
            or val(row, "Notes").casefold() == "rejected"):
        raise PackageBlocked("job_marked_rejected")
    if tracker.rejected_jobs_index().match(source=source, job_id=extract_indeed_job_key(job_url), url=job_url):
        raise PackageBlocked("permanently_rejected")
    if status.casefold() in EXPIRED or lifecycle.casefold() == "expired":
        raise PackageBlocked("job_expired")
    if status.casefold() in APPLIED or val(row, "Applied").casefold() not in ("", "no", "false") or lifecycle.casefold() in ("applied", "contacted", "interview", "offer"):
        raise PackageBlocked("already_applied")
    if "duplicate" in val(row, "Notes").casefold() or lifecycle.casefold() == "duplicate":
        raise PackageBlocked("duplicate_job")
    canonical = normalize_job_url(job_url)
    jk = extract_indeed_job_key(job_url)
    if any(other_number != number and (
            (canonical and normalize_job_url(val(other, "Job URL")) == canonical)
            or (jk and extract_indeed_job_key(val(other, "Job URL")) == jk))
           for other_number, other in tab.rows):
        raise PackageBlocked("duplicate_job")
    from google_tracker import resume_approval_value
    if resume_approval_value(row.get("Location"), row.get("Work Arrangement"), row.get("Cost")) != "Yes":
        raise PackageBlocked("paid_or_excluded_job")
    if val(row, "Apply?").casefold() != "yes":
        raise PackageBlocked("job_not_eligible")
    if val(row, "Resume Created").casefold() != "x":
        raise PackageBlocked("resume_not_completed")
    resume = resolve_resume(val(row, "Resume Link"), root)
    description, job_number = description_for(stable, row, root)
    if source.casefold() == "indeed":
        jk = extract_indeed_job_key(job_url)
        if not jk or jk.casefold() != job_number.casefold():
            raise PackageBlocked("indeed_job_id_mismatch")
    validate_resume_identity(resume, row, job_number)
    target = company_url or job_url
    if source.casefold() == "indeed" and not company_url:
        raise PackageBlocked("company_application_url_required")
    verified_url = url_verifier(target, val(row, "Company"), val(row, "Job Title"))
    resume_rel = resume.relative_to(root.resolve()).as_posix()
    desc_rel = description.relative_to(root.resolve()).as_posix()
    return {
        "job_id": stable, "company": val(row, "Company"), "job_title": val(row, "Job Title"),
        "company_application_url": verified_url, "source": source,
        "job_description_reference": desc_rel,
        "verified_resume_file_path": str(resume),
        "verified_resume_wsl_path": "/mnt/c/gecko_main/" + resume_rel,
        "application_preparation_approved": True,
        "application_status": status or lifecycle or "Not submitted in tracker",
        "missing_information_or_validation_warnings": [
            "Application form and submission controls were not inspected; OpenClaw must verify them before any later action."
        ],
    }


def save_package(package: dict, *, root: Path = ROOT) -> tuple[Path, Path]:
    job_id = package["job_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job_id):
        raise PackageBlocked("unsafe_job_id_for_path")
    project = root.resolve()
    queue = (root / "openclaw" / "application-queue").resolve()
    if queue != project / "openclaw" / "application-queue":
        raise PackageBlocked("invalid_output_path")
    folder = (queue / job_id).resolve()
    if folder.parent != queue or folder.is_symlink():
        raise PackageBlocked("invalid_output_path")
    folder.mkdir(parents=True, exist_ok=True)
    package_path, audit_path = folder / "application-package.json", folder / "audit.json"
    if package_path.is_symlink() or audit_path.is_symlink():
        raise PackageBlocked("invalid_output_path")
    payload = json.dumps(package, indent=2, ensure_ascii=False) + "\n"
    audit = {"job_id": job_id, "result": "prepared", "checked_at":
             datetime.now(ZoneInfo("America/Denver")).isoformat(timespec="seconds"),
             "checks": ["unique_id", "approval", "eligibility", "rejection", "application_status",
                        "cost", "resume_exists", "resume_identity", "description_identity", "company_url"]}
    package_path.write_text(payload, encoding="utf-8")
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return package_path, audit_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--job-id", help="Unique live ledger ID")
    group.add_argument("--row", type=int, help="Explicitly selected physical ledger row")
    parser.add_argument("--approved-job-id", required=True,
                        help="Explicit application-preparation approval; must match the live row ID")
    parser.add_argument("--company-application-url",
                        help="Verified employer/ATS job URL; required for Indeed")
    args = parser.parse_args()
    try:
        package = prepare(GoogleTracker(), job_id=args.job_id, physical_row=args.row,
                          approved_job_id=args.approved_job_id,
                          company_url=args.company_application_url)
        package_path, audit_path = save_package(package)
    except PackageBlocked as error:
        print(f"Package blocked: {error.code}", file=sys.stderr)
        return 2
    print(f"Package: {package_path}")
    print(f"OpenClaw WSL path: /mnt/c/gecko_main/openclaw/application-queue/{package['job_id']}/application-package.json")
    print(f"Sanitized audit: {audit_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
