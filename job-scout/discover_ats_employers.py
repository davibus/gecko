"""Discover, validate, and maintain Gecko's direct-employer ATS universe.

This is intentionally separate from the daily Job Scout workflow. Discovery uses
Brave's public web index; validation uses the same public ATS endpoints as the
runtime providers. Existing configuration entries are never automatically
removed.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date
import html
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote, unquote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sources.base import ProviderError  # noqa: E402
from sources.http import get_document, get_json_value  # noqa: E402


CONFIG_PATH = ROOT / "preferences" / "job-sources.json"
REPORT_PATH = ROOT / "data" / "ats-employer-discovery.json"
SEED_PATH = ROOT / "preferences" / "ats-employer-seeds.json"
PLATFORMS = ("greenhouse", "lever", "ashby", "workable")
IDENTIFIER_KEYS = {
    "greenhouse": "token", "lever": "site", "ashby": "board", "workable": "account",
}
PLATFORM_CAPS = {"greenhouse": 125, "lever": 85, "ashby": 80, "workable": 80}
DOMAINS = {
    "greenhouse": {"boards.greenhouse.io", "job-boards.greenhouse.io"},
    "lever": {"jobs.lever.co"},
    "ashby": {"jobs.ashbyhq.com"},
    "workable": {"apply.workable.com"},
}
SEARCH_DOMAINS = {
    "greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io"),
    "lever": ("jobs.lever.co",), "ashby": ("jobs.ashbyhq.com",),
    "workable": ("apply.workable.com",),
}
BOARD_URLS = {
    "greenhouse": "https://job-boards.greenhouse.io/{identifier}",
    "lever": "https://jobs.lever.co/{identifier}",
    "ashby": "https://jobs.ashbyhq.com/{identifier}",
    "workable": "https://apply.workable.com/{identifier}/",
}
ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{identifier}?mode=json&limit=200",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{identifier}?includeCompensation=true",
    "workable": "https://www.workable.com/api/accounts/{identifier}?details=true",
}
SEARCH_TERMS = (
    "marketing", '"paid search"', '"paid media"', '"performance marketing"',
    '"growth marketing"', '"digital marketing"', '"demand generation"',
    '"marketing analytics"', '"marketing operations"', '"acquisition marketing"',
    '"lifecycle marketing"', '"ecommerce marketing"', "SEO", "SEM", "CRO",
    '"marketing automation"', '"media buying"', '"digital strategy"',
)
ROLE_TERMS = (
    "marketing", "paid search", "paid media", "performance marketing", "growth marketing",
    "digital marketing", "demand generation", "acquisition", "lifecycle marketing",
    "marketing analytics", "marketing operations", "e-commerce", "ecommerce", "seo",
    "sem", "media buyer", "media buying", "conversion rate", "cro", "attribution",
    "marketing measurement", "marketing intelligence", "marketing technology",
    "marketing automation", "client strategy", "account manager", "digital strategy",
)
US_TERMS = (
    "united states", "usa", "u.s.", "remote - us", "remote, us", "remote us",
    "utah", "salt lake", "lehi", "draper", "provo", "sandy",
)
COMPANY_SIGNALS = (
    "agency", "advertising", "marketing", "commerce", "ecommerce", "e-commerce",
    "software", "saas", "analytics", "data", "media", "marketplace", "technology",
    "platform", "consumer", "retail", "fintech", "martech", "adtech",
)
NON_EMPLOYER_BOARDS = {
    ("lever", "assist-world"), ("lever", "jobgether"),
    ("ashby", "bedrock-talent"), ("ashby", "scale army careers"),
    ("workable", "cesna-group-2"),
}


def board_url(platform: str, identifier: str) -> str:
    return BOARD_URLS[platform].format(identifier=quote(identifier))


@dataclass
class Candidate:
    company: str
    platform: str
    identifier: str
    board_url: str
    discovered_via: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    existing: bool = False
    name_locked: bool = False


def load_local_environment() -> None:
    """Load local dotenv values without overriding the calling environment."""
    for path in (ROOT.parent / ".env.local", ROOT.parent / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", raw)
            if not match or match.group(1) in os.environ:
                continue
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ[match.group(1)] = value


def extract_identifier(url: str, platform: str | None = None) -> tuple[str, str] | None:
    """Return (platform, hosted-board identifier) only for recognized ATS URLs."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").casefold().rstrip(".")
    if parts.scheme not in {"http", "https"} or parts.username or parts.password:
        return None
    matched = next((name for name, domains in DOMAINS.items() if host in domains), None)
    if not matched or (platform and platform != matched):
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if not segments:
        return None
    identifier = unquote(segments[0]).strip()
    allowed = (r"[A-Za-z0-9][A-Za-z0-9._ -]{0,127}" if matched == "ashby"
               else r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
    if (not re.fullmatch(allowed, identifier)
            or identifier.casefold() in {"jobs", "job", "search", "jooble"}):
        return None
    return matched, identifier


def normalized_name(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    value = re.sub(r"\s+", " ", value).strip(" -|:")
    return re.sub(r"\b(?:incorporated|corporation|company|inc|llc|ltd)\.?\b", "", value,
                  flags=re.I).strip(" ,.-").casefold()


def display_name(value: str, fallback: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    value = re.sub(r"\s+", " ", value).strip(" -|:")
    for pattern in (
        r"^job application for .+? at (.+)$",
        r"^.+?\s+@\s+(.+)$",
        r"^jobs at (.+?)(?:\s*[|:-]\s*(?:greenhouse|lever|ashby|workable).*)?$",
        r"^(?:careers|jobs|open positions)\s+(?:at|with)\s+(.+)$",
        r"^(?:careers|jobs|open positions)\s*[-|:]\s*(.+)$",
        r"^(.+?)\s+(?:careers|jobs|job board|open positions)$",
        r"^(.+?)\s*[-|:]\s*(?:careers|jobs|open positions|lever|greenhouse|ashby|workable).*$",
    ):
        match = re.match(pattern, value, re.I)
        if match:
            value = match.group(1).strip()
            break
    if " - " in value:
        prefix, remainder = value.split(" - ", 1)
        if any(term in remainder.casefold() for term in ROLE_TERMS):
            value = prefix.strip()
    if " | " in value:
        suffix = value.rsplit(" | ", 1)[1].strip()
        if suffix.casefold() not in {"greenhouse", "lever", "ashby", "workable", "careers", "jobs"}:
            value = suffix
    value = re.sub(r"\s+(?:careers|jobs|open positions)$", "", value, flags=re.I).strip()
    return value if 1 < len(value) <= 100 else fallback


def _page_title(document) -> str:
    page = document.body.decode("utf-8", errors="replace")[:500_000]
    for pattern in (
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
        r"<title[^>]*>(.*?)</title>",
    ):
        match = re.search(pattern, page, re.I | re.S)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return ""


def _jobs(platform: str, payload) -> list[dict]:
    if platform == "lever":
        if not isinstance(payload, list):
            raise ProviderError("Lever returned an unexpected postings payload")
        items = payload
    else:
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise ProviderError(f"{platform.title()} returned an unexpected jobs payload")
        items = payload["jobs"]
    if not all(isinstance(item, dict) for item in items):
        raise ProviderError(f"{platform.title()} returned malformed job records")
    return items


def _job_text(platform: str, job: dict) -> tuple[str, str, str]:
    title = str(job.get("title") or job.get("text") or "")
    if platform == "lever":
        categories = job.get("categories") or {}
        location = str(categories.get("location") or "") if isinstance(categories, dict) else ""
        description = " ".join(str(job.get(key) or "") for key in
                               ("descriptionPlain", "additionalPlain"))
    elif platform == "workable" and isinstance(job.get("locations"), list):
        locations = []
        for item in job["locations"]:
            if isinstance(item, dict):
                locations.append(", ".join(str(item.get(key) or "") for key in
                                            ("city", "region", "country") if item.get(key)))
        location = "; ".join(filter(None, locations))
        if job.get("telecommuting"):
            location = "Remote; " + location
        description = str(job.get("description") or "")
    else:
        location_value = job.get("location") or ""
        if isinstance(location_value, dict):
            location = str(location_value.get("name") or location_value.get("location_str") or "")
        else:
            location = str(location_value)
        description = str(job.get("content") or job.get("descriptionPlain") or
                          job.get("descriptionHtml") or job.get("description") or "")
    return title, location, re.sub(r"<[^>]+>", " ", html.unescape(description))


def _job_url(platform: str, job: dict) -> str:
    keys = {
        "greenhouse": ("absolute_url",), "lever": ("hostedUrl", "applyUrl"),
        "ashby": ("jobUrl", "applyUrl"),
        "workable": ("url", "shortlink", "application_url"),
    }[platform]
    return next((str(job.get(key)) for key in keys if job.get(key)), "")


def validate_candidate(candidate: Candidate) -> dict:
    platform, identifier = candidate.platform, candidate.identifier
    endpoint = ENDPOINTS[platform].format(identifier=quote(identifier))
    record = {
        **asdict(candidate), "validation_status": "valid", "endpoint": endpoint,
        "discovery_date": date.today().isoformat(), "open_job_count": 0,
        "marketing_job_count": 0, "us_job_count": 0, "remote_job_count": 0,
        "relevant_role_examples": [], "relevance_score": 0, "approved": False,
        "rejection_reason": "", "failure_count": 0,
    }
    try:
        payload = get_json_value(endpoint)
        jobs = _jobs(platform, payload)
        try:
            board_document = get_document(candidate.board_url)
            redirected = extract_identifier(board_document.final_url, platform)
            if redirected and redirected[1].casefold() != identifier.casefold():
                record.update(validation_status="redirected", rejection_reason=(
                    f"board redirects to {redirected[1]}"))
                return record
            authoritative_name = display_name(_page_title(board_document), candidate.company)
            if authoritative_name and not candidate.name_locked:
                record["company"] = authoritative_name
        except (ProviderError, OSError, ValueError):
            # A populated, correctly shaped public provider feed is authoritative.
            # The decorative hosted page may independently block automated clients.
            if not jobs:
                raise
        for job in jobs:
            url = _job_url(platform, job)
            extracted = extract_identifier(url, platform) if url else None
            # Workable's published job URLs are account-agnostic /j/<shortcode> links.
            if (platform != "workable" and url and extracted
                    and extracted[1].casefold() != identifier.casefold()):
                raise ProviderError("job payload points at a different ATS board")
        rows = [_job_text(platform, job) for job in jobs]
        relevant = [title for title, location, description in rows
                    if any(term in title.casefold() for term in ROLE_TERMS)]
        us_jobs = [row for row in rows if any(term in row[1].casefold() for term in US_TERMS)]
        remote_jobs = [row for row in rows if "remote" in row[1].casefold()]
        us_remote_jobs = [row for row in remote_jobs
                          if any(term in row[1].casefold() for term in US_TERMS)]
        context = " ".join(candidate.evidence + candidate.discovered_via + [record["company"]]).casefold()
        if (platform, identifier.casefold()) in NON_EMPLOYER_BOARDS:
            record.update(validation_status="invalid", approved=False,
                          rejection_reason="intermediary board is not a direct employer")
            return record
        if "training environment" in context or "demo board" in context:
            record.update(validation_status="invalid", approved=False,
                          rejection_reason="non-employer demonstration or training board")
            return record
        score = 2 if candidate.discovered_via else 0
        score += min(8, len(relevant) * 2)
        score += 2 if remote_jobs else 0
        score += 2 if us_jobs else 0
        score += min(3, sum(1 for term in COMPANY_SIGNALS if term in context))
        if not jobs:
            score += 1  # a live public board can remain useful between hiring cycles
        approved = score >= 3 or candidate.existing
        record.update(
            open_job_count=len(jobs), marketing_job_count=len(relevant),
            us_job_count=len(us_jobs), remote_job_count=len(remote_jobs),
            us_remote_job_count=len(us_remote_jobs),
            relevant_role_examples=relevant[:5], relevance_score=score, approved=approved,
            rejection_reason="" if approved else "insufficient evidence of target-profile relevance",
        )
    except (ProviderError, ValueError, TypeError, OSError) as error:
        message = str(error)
        temporary = any(term in message.casefold() for term in
                        ("timed out", "timeout", "429", "500", "502", "503", "504", "temporar"))
        record.update(
            validation_status="temporary_failure" if temporary else "invalid",
            rejection_reason=message, approved=False,
        )
    return record


def _existing_candidates(config: dict, selected: set[str]) -> list[Candidate]:
    result = []
    for platform in PLATFORMS:
        if platform not in selected:
            continue
        key = IDENTIFIER_KEYS[platform]
        for company in config["providers"].get(platform, {}).get("companies", []):
            identifier = str(company.get(key) or "").strip()
            if identifier:
                result.append(Candidate(
                    str(company.get("name") or identifier), platform, identifier,
                    board_url(platform, identifier), ["existing configuration"],
                    existing=True, name_locked=True,
                ))
    return result


def _seed_candidates(path: Path, selected: set[str]) -> tuple[list[Candidate], list[dict]]:
    if not path.is_file():
        return [], []
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        raise ValueError("ATS employer seed file must contain a JSON array")
    candidates, errors = [], []
    for row in payload:
        url = str(row.get("url") or "") if isinstance(row, dict) else ""
        extracted = extract_identifier(url)
        if not extracted:
            errors.append({"url": url, "error": "seed is not a recognized ATS board URL"})
            continue
        platform, identifier = extracted
        if platform not in selected:
            continue
        candidates.append(Candidate(
            str(row.get("name") or identifier), platform, identifier,
            board_url(platform, identifier),
            [str(row.get("discovered_via") or "curated public ATS URL")],
            [str(row.get("evidence") or "")], name_locked=True,
        ))
    return candidates, errors


def _prior_candidates(path: Path, selected: set[str]) -> list[Candidate]:
    """Carry a completed dry-run into apply, while revalidating every board."""
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    result = []
    for row in payload.get("candidates", []):
        if (not isinstance(row, dict) or row.get("platform") not in selected
                or not row.get("identifier") or row.get("existing")):
            continue
        platform = row["platform"]
        result.append(Candidate(
            str(row.get("company") or row["identifier"]), platform, str(row["identifier"]),
            board_url(platform, str(row["identifier"])),
            list(row.get("discovered_via") or ["previous discovery report"]),
            list(row.get("evidence") or []),
        ))
    return result


def _brave_search(query: str, api_key: str) -> list[dict]:
    url = "https://api.search.brave.com/res/v1/web/search?" + urlencode({
        "q": query, "count": 20, "country": "US", "search_lang": "en",
    })
    payload = get_json_value(url, {"X-Subscription-Token": api_key})
    results = payload.get("web", {}).get("results", []) if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise ProviderError("Brave returned an unexpected employer-discovery payload")
    return results


def discover(selected: set[str], limit: int | None = None) -> tuple[list[Candidate], list[dict]]:
    api_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        raise ProviderError("ATS employer discovery requires BRAVE_SEARCH_API_KEY")
    candidates: dict[tuple[str, str], Candidate] = {}
    errors = []
    for platform in PLATFORMS:
        if platform not in selected:
            continue
        for domain in SEARCH_DOMAINS[platform]:
          for term in SEARCH_TERMS:
            query = f"site:{domain} {term}"
            try:
                results = _brave_search(query, api_key)
            except ProviderError as error:
                errors.append({"platform": platform, "query": query, "error": str(error)})
                continue
            for result in results:
                url = str(result.get("url") or "")
                extracted = extract_identifier(url, platform)
                if not extracted:
                    continue
                _, identifier = extracted
                lookup = (platform, identifier.casefold())
                evidence = " ".join(str(result.get(key) or "") for key in ("title", "description"))
                item = candidates.get(lookup)
                if item is None:
                    name = display_name(str(result.get("title") or ""), identifier)
                    item = Candidate(name, platform, identifier, board_url(platform, identifier))
                    candidates[lookup] = item
                if query not in item.discovered_via:
                    item.discovered_via.append(query)
                if evidence and evidence not in item.evidence:
                    item.evidence.append(evidence[:500])
            if limit and sum(1 for item in candidates.values() if item.platform == platform) >= limit:
                break
            time.sleep(0.05)
          if limit and sum(1 for item in candidates.values() if item.platform == platform) >= limit:
              break
    ordered = sorted(candidates.values(), key=lambda item: (item.platform, item.identifier.casefold()))
    if limit:
        ordered = [item for platform in PLATFORMS
                   for item in [row for row in ordered if row.platform == platform][:limit]]
    return ordered, errors


def deduplicate_candidates(candidates: list[Candidate]) -> tuple[list[Candidate], list[dict]]:
    unique: dict[tuple[str, str], Candidate] = {}
    name_keys: dict[tuple[str, str], str] = {}
    duplicates = []
    for candidate in candidates:
        key = (candidate.platform, candidate.identifier.casefold())
        name_key = (candidate.platform, normalized_name(candidate.company))
        if key in unique:
            kept = unique[key]
            kept.existing = kept.existing or candidate.existing
            if candidate.name_locked and not kept.name_locked:
                kept.company = candidate.company
            kept.name_locked = kept.name_locked or candidate.name_locked
            kept.discovered_via = sorted(set(kept.discovered_via + candidate.discovered_via))
            kept.evidence = list(dict.fromkeys(kept.evidence + candidate.evidence))
            duplicates.append({"platform": candidate.platform, "identifier": candidate.identifier,
                               "reason": "duplicate identifier"})
            continue
        if name_key[1] and name_key in name_keys and name_keys[name_key] != candidate.identifier.casefold():
            duplicates.append({"platform": candidate.platform, "identifier": candidate.identifier,
                               "reason": "duplicate normalized company name"})
            continue
        unique[key] = candidate
        if name_key[1]:
            name_keys[name_key] = candidate.identifier.casefold()
    return sorted(unique.values(), key=lambda item: (item.platform, item.identifier.casefold())), duplicates


def merge_config(config: dict, records: list[dict], selected: set[str]) -> dict[str, int]:
    added = {platform: 0 for platform in PLATFORMS}
    for platform in PLATFORMS:
        if platform not in selected:
            continue
        settings = config["providers"].setdefault(platform, {"enabled": True, "companies": []})
        companies = settings.setdefault("companies", [])
        key = IDENTIFIER_KEYS[platform]
        known = {str(item.get(key) or "").casefold() for item in companies}
        known_names = {normalized_name(str(item.get("name") or "")) for item in companies}
        for record in records:
            if (record["platform"] != platform
                    or not record.get("selected_for_config", record.get("approved", False))
                    or record["existing"]):
                continue
            identifier = record["identifier"]
            company_name = record["company"]
            if identifier.casefold() in known or normalized_name(company_name) in known_names:
                continue
            companies.append({"name": company_name, key: identifier})
            known.add(identifier.casefold())
            known_names.add(normalized_name(company_name))
            added[platform] += 1
        companies.sort(key=lambda item: (str(item.get("name") or "").casefold(),
                                         str(item.get(key) or "").casefold()))
    return added


def select_for_config(records: list[dict], config: dict, selected: set[str]) -> None:
    """Apply deterministic per-platform quality caps after validation and scoring."""
    for record in records:
        record["selected_for_config"] = bool(record["existing"])
    for platform in PLATFORMS:
        if platform not in selected:
            continue
        key = IDENTIFIER_KEYS[platform]
        existing_count = len(config["providers"].get(platform, {}).get("companies", []))
        available = max(0, PLATFORM_CAPS[platform] - existing_count)
        eligible = [row for row in records if row["platform"] == platform
                    and row["approved"] and not row["existing"]]
        eligible.sort(key=lambda row: (
            -int(row.get("us_remote_job_count", 0) > 0),
            -int(row.get("us_job_count", 0) > 0),
            -int(row.get("remote_job_count", 0) > 0),
            -int(row.get("marketing_job_count", 0) > 0),
            -int(row.get("relevance_score", 0)),
            -int(row.get("us_job_count", 0)), -int(row.get("remote_job_count", 0)),
            -int(row.get("marketing_job_count", 0)), normalized_name(row["company"]),
            str(row.get(key) or row.get("identifier") or "").casefold(),
        ))
        for row in eligible[:available]:
            row["selected_for_config"] = True
        for row in eligible[available:]:
            row["approved"] = False
            row["rejection_reason"] = "below deterministic platform quality cap"


def previous_failures(path: Path) -> dict[tuple[str, str], int]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {(row["platform"], row["identifier"].casefold()): int(row.get("failure_count", 0))
            for row in payload.get("candidates", []) if isinstance(row, dict)
            and row.get("platform") in PLATFORMS and row.get("identifier")}


def write_report(path: Path, records: list[dict], errors: list[dict], duplicates: list[dict],
                 added: dict[str, int], applied: bool) -> None:
    failures = previous_failures(path)
    for record in records:
        key = (record["platform"], record["identifier"].casefold())
        record["failure_count"] = (failures.get(key, 0) + 1
                                   if record["validation_status"] != "valid" else 0)
    summary = {
        "candidate_count": len(records),
        "approved_count": sum(bool(row["approved"]) for row in records),
        "selected_count": sum(bool(row.get("selected_for_config")) for row in records),
        "rejected_count": sum(not row["approved"] and not row["existing"] for row in records),
        "existing_failures": sum(row["existing"] and row["validation_status"] != "valid"
                                 for row in records),
        "marketing_opening_employers": sum(row["marketing_job_count"] > 0 for row in records),
        "remote_opening_employers": sum(row["remote_job_count"] > 0 for row in records),
        "us_remote_opening_employers": sum(row.get("us_remote_job_count", 0) > 0
                                             for row in records),
        "added": added,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "generated_at": date.today().isoformat(), "applied": applied, "summary": summary,
        "search_errors": errors, "duplicates": duplicates, "candidates": records,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Discover/validate without changing config")
    mode.add_argument("--apply", action="store_true", help="Merge newly validated employers into config (the default)")
    parser.add_argument("--refresh", action="store_true",
                        help="Revalidate configured employers and discover newly indexed boards")
    parser.add_argument("--platform", choices=PLATFORMS, action="append",
                        help="Limit to one or more ATS platforms")
    parser.add_argument("--limit", type=int, help="Maximum discovered candidates per platform")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--seeds", type=Path, default=SEED_PATH,
                        help="Curated public ATS URLs used when search indexes or quotas are incomplete")
    return parser


def run(args: argparse.Namespace) -> int:
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be positive")
    load_local_environment()
    selected = set(args.platform or PLATFORMS)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    if config.get("providers", {}).get("jooble", {}).get("enabled"):
        raise ValueError("Jooble cannot be enabled in Gecko Job Scout")
    existing = _existing_candidates(config, selected)
    prior = _prior_candidates(args.report, selected)
    seeded, seed_errors = _seed_candidates(getattr(args, "seeds", SEED_PATH), selected)
    discovered, errors = discover(selected, args.limit)
    errors.extend(seed_errors)
    candidates, duplicates = deduplicate_candidates(existing + prior + seeded + discovered)
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(candidates)))) as executor:
        futures = {executor.submit(validate_candidate, item): item for item in candidates}
        records = [future.result() for future in as_completed(futures)]
    records.sort(key=lambda row: (row["platform"], normalized_name(row["company"]),
                                  row["identifier"].casefold()))
    select_for_config(records, config, selected)
    added = {platform: 0 for platform in PLATFORMS}
    if args.apply:
        added = merge_config(config, records, selected)
        args.config.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    write_report(args.report, records, errors, duplicates, added, args.apply)
    summary = json.loads(args.report.read_text(encoding="utf-8"))["summary"]
    print(json.dumps(summary, indent=2))
    if errors:
        print(f"Discovery queries with errors: {len(errors)}")
    if summary["existing_failures"]:
        print(f"Potentially stale configured boards preserved: {summary['existing_failures']}")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if not args.dry_run:
        args.apply = True
    try:
        return run(args)
    except (ProviderError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"ATS employer discovery failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
