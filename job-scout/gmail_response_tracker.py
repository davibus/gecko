"""Read-only Gmail response detection for Gecko's canonical Job Scout sheet."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
DEFAULT_CLIENT_FILE = ROOT / ".secrets" / "gmail-oauth-client.json"
DEFAULT_TOKEN_FILE = ROOT / ".secrets" / "gmail-oauth-token.json"
DEFAULT_STATE_FILE = ROOT / "job-scout" / "data" / "gmail-response-state.json"
DEFAULT_LOG_FILE = ROOT / "output" / "gmail-response-tracking.log"
STATE_VERSION = 1

GENERIC_SENDER_DOMAINS = {
    "indeed.com", "linkedin.com", "ziprecruiter.com", "glassdoor.com",
    "monster.com", "careerbuilder.com", "simplyhired.com", "jooble.org",
}
GENERIC_SUBJECT_RE = re.compile(
    r"\b(job alert|recommended jobs?|jobs? you may|new jobs? for you|daily job|weekly job|"
    r"career newsletter|job recommendations?|similar jobs?)\b",
    re.I,
)
CONFIRMATION_RE = re.compile(
    r"\b(thank you for applying|application (?:was )?received|we(?:'ve| have) received "
    r"your application|application confirmation|successfully submitted)\b",
    re.I,
)
STAGE_PATTERNS = (
    ("offer", re.compile(r"\b(offer of employment|employment offer|pleased to offer|job offer)\b", re.I)),
    ("rejection", re.compile(
        r"\b(unfortunately|not moving forward|move forward with other candidates|"
        r"pursue other candidates|will not be moving forward|position has been filled|"
        r"not selected|unable to offer you)\b", re.I,
    )),
    ("interview", re.compile(
        r"\b(interview invitation|invite you to interview|schedule (?:an |a )?interview|"
        r"phone screen|screening call|schedule (?:a )?call|meet with (?:the|our) team)\b", re.I,
    )),
    ("assessment", re.compile(
        r"\b(complete (?:an?|the) assessment|skills assessment|take-home (?:test|exercise)|"
        r"coding assessment|assessment link)\b", re.I,
    )),
    ("next_step", re.compile(
        r"\b(next steps?|your availability|available times?|salary expectations?|"
        r"additional information|provide (?:us )?with|complete the following)\b", re.I,
    )),
    ("recruiter_outreach", re.compile(
        r"\b(recruiter|talent acquisition|reaching out (?:about|regarding)|"
        r"would like to discuss|interested in speaking|regarding your application)\b", re.I,
    )),
    ("status_update", re.compile(
        r"\b(update (?:on|regarding) your application|application status|status update)\b", re.I,
    )),
)
STAGE_RANK = {
    "status_update": 10,
    "recruiter_outreach": 20,
    "next_step": 30,
    "assessment": 40,
    "interview": 50,
    "rejection": 100,
    "offer": 110,
}
STAGE_LABELS = {
    "status_update": "Status update",
    "recruiter_outreach": "Recruiter outreach",
    "next_step": "Next step",
    "assessment": "Assessment",
    "interview": "Interview request",
    "rejection": "Rejected",
    "offer": "Offer",
}
TOKEN_STOPWORDS = {
    "and", "the", "for", "with", "from", "this", "that", "senior", "manager",
    "director", "associate", "specialist", "remote", "marketing", "digital", "of",
    "a", "an", "to", "in", "at", "us", "usa",
}
COMPANY_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "company",
    "co", "group", "holdings", "partners", "management",
}


@dataclass(frozen=True)
class GmailConfig:
    client_file: Path
    token_file: Path
    state_file: Path
    max_results_per_job: int = 25

    @classmethod
    def from_environment(cls) -> "GmailConfig":
        def path_value(name: str, default: Path) -> Path:
            raw = os.getenv(name, "").strip()
            return Path(os.path.expandvars(raw)).expanduser() if raw else default

        return cls(
            path_value("GECKO_GMAIL_CLIENT_SECRET_FILE", DEFAULT_CLIENT_FILE),
            path_value("GECKO_GMAIL_TOKEN_FILE", DEFAULT_TOKEN_FILE),
            path_value("GECKO_GMAIL_STATE_FILE", DEFAULT_STATE_FILE),
            max(1, int(os.getenv("GECKO_GMAIL_MAX_RESULTS_PER_JOB", "25"))),
        )


@dataclass(frozen=True)
class JobCandidate:
    row: int
    company: str
    title: str
    job_url: str = ""
    job_number: str = ""
    resume_link: str = ""
    relevant_date: date | None = None
    existing_response: str = ""

    @property
    def state_key(self) -> str:
        return str(self.row)


@dataclass(frozen=True)
class EmailMessage:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    received_at: datetime
    text: str


@dataclass(frozen=True)
class ResponseMatch:
    job: JobCandidate
    message: EmailMessage
    stage: str
    score: int
    summary: str


@dataclass
class RunSummary:
    emails_checked: int = 0
    emails_matched: int = 0
    tracker_rows_updated: int = 0
    updated_rows: list[int] | None = None
    skipped_processed: int = 0

    def __post_init__(self) -> None:
        if self.updated_rows is None:
            self.updated_rows = []


class GmailSetupError(RuntimeError):
    pass


def append_log(message: str, path: Path = DEFAULT_LOG_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _load_project_environment() -> None:
    for name in (".env.local", ".env.google-sheets.local"):
        path = ROOT / name
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.removeprefix("export ").split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def build_gmail_service(config: GmailConfig, *, interactive: bool = False):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as error:
        raise GmailSetupError(
            "Gmail dependencies are missing; install job-scout/requirements.txt"
        ) from error

    credentials = None
    if config.token_file.is_file():
        credentials = Credentials.from_authorized_user_file(
            str(config.token_file), [GMAIL_READONLY_SCOPE]
        )
        granted = set(credentials.scopes or ())
        if GMAIL_READONLY_SCOPE not in granted or granted - {GMAIL_READONLY_SCOPE}:
            raise GmailSetupError(
                "The saved Gmail token does not contain exactly gmail.readonly. "
                f"Delete {config.token_file} and authorize again."
            )

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _atomic_json(config.token_file, json.loads(credentials.to_json()))
    elif not credentials or not credentials.valid:
        if not interactive:
            raise GmailSetupError(
                "Gmail OAuth is not authorized. Run: "
                "python job-scout/gmail_response_tracker.py authorize"
            )
        if not config.client_file.is_file():
            raise GmailSetupError(
                f"Gmail OAuth desktop client file is unavailable: {config.client_file}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.client_file), [GMAIL_READONLY_SCOPE]
        )
        credentials = flow.run_local_server(port=0)
        _atomic_json(config.token_file, json.loads(credentials.to_json()))

    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _decode(data: str) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")
    except (ValueError, UnicodeError):
        return ""


def _payload_text(payload: dict[str, Any]) -> str:
    plain = []
    rich = []

    def visit(part: dict[str, Any]) -> None:
        mime = str(part.get("mimeType") or "").casefold()
        data = _decode(str(part.get("body", {}).get("data") or ""))
        if data and mime == "text/plain":
            plain.append(data)
        elif data and mime == "text/html":
            rich.append(re.sub(r"<[^>]+>", " ", html.unescape(data)))
        for child in part.get("parts", ()) or ():
            visit(child)

    visit(payload or {})
    return "\n".join(plain or rich)


def message_from_api(raw: dict[str, Any]) -> EmailMessage:
    headers = {
        str(item.get("name") or "").casefold(): str(item.get("value") or "")
        for item in raw.get("payload", {}).get("headers", ())
    }
    timestamp = int(raw.get("internalDate") or 0) / 1000
    received = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    body = _payload_text(raw.get("payload", {}))
    snippet = html.unescape(str(raw.get("snippet") or ""))
    text = re.sub(r"\s+", " ", f"{snippet}\n{body}").strip()[:30_000]
    return EmailMessage(
        str(raw.get("id") or ""), str(raw.get("threadId") or ""),
        headers.get("from", ""), headers.get("subject", ""), received, text,
    )


class GmailReader:
    def __init__(self, service):
        self.messages = service.users().messages()

    def search_ids(self, query: str, limit: int) -> list[str]:
        ids = []
        token = None
        while len(ids) < limit:
            response = self.messages.list(
                userId="me", q=query, maxResults=min(100, limit - len(ids)), pageToken=token,
            ).execute()
            ids.extend(item["id"] for item in response.get("messages", ()))
            token = response.get("nextPageToken")
            if not token:
                break
        return ids[:limit]

    def get_message(self, message_id: str) -> EmailMessage:
        raw = self.messages.get(userId="me", id=message_id, format="full").execute()
        return message_from_api(raw)


def _normalize(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold())
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: str, *, company: bool = False) -> set[str]:
    omitted = TOKEN_STOPWORDS | (COMPANY_SUFFIXES if company else set())
    return {token for token in _normalize(value).split() if len(token) >= 2 and token not in omitted}


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and value > 1:
        return date(1899, 12, 30) + timedelta(days=int(value))
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    return None


def _job_number(*values: str) -> str:
    for raw in values:
        value = unquote(str(raw or ""))
        if not value:
            continue
        query = parse_qs(urlsplit(value).query)
        for key in ("jk", "jobId", "job_id", "gh_jid"):
            if query.get(key):
                return str(query[key][0])
        filename = urlsplit(value).path.rsplit("/", 1)[-1].removesuffix(".docx")
        suffix = filename.rsplit("+", 1)[-1]
        if re.fullmatch(r"[A-Za-z0-9_-]{6,}", suffix):
            return suffix
    return ""


def candidates_from_rows(rows: Iterable[dict[str, Any]]) -> list[JobCandidate]:
    result = []
    for row in rows:
        dates = [_parse_date(row.get(name)) for name in ("Date Created", "Date Found")]
        relevant = max((item for item in dates if item), default=None)
        result.append(JobCandidate(
            row=int(row["_row"]),
            company=str(row.get("Company") or "").strip(),
            title=str(row.get("Job Title") or "").strip(),
            job_url=str(row.get("Job URL") or row.get("Job Link") or "").strip(),
            job_number=str(row.get("Job Number") or "").strip() or _job_number(
                str(row.get("Job URL") or ""), str(row.get("Resume Link") or "")
            ),
            resume_link=str(row.get("Resume Link") or "").strip(),
            relevant_date=relevant,
            existing_response=str(row.get("Response") or "").strip(),
        ))
    return [job for job in result if job.company and job.title]


def gmail_query(job: JobCandidate, today: date) -> str:
    start = (job.relevant_date or (today - timedelta(days=120))) - timedelta(days=1)
    terms = [job.company, job.title, job.job_number]
    quoted = " ".join(f'"{term.replace(chr(34), "")}"' for term in terms if term)
    return (
        f"after:{start:%Y/%m/%d} -in:sent -category:promotions "
        f"-category:social {{{quoted}}}"
    )


def _sender_domain(sender: str) -> str:
    address = parseaddr(sender)[1].casefold()
    return address.rsplit("@", 1)[-1] if "@" in address else ""


def _generic_message(message: EmailMessage) -> bool:
    domain = _sender_domain(message.sender)
    generic_domain = any(domain == item or domain.endswith("." + item) for item in GENERIC_SENDER_DOMAINS)
    return bool(GENERIC_SUBJECT_RE.search(message.subject)) or (
        generic_domain and bool(GENERIC_SUBJECT_RE.search(message.subject + " " + message.text[:500]))
    )


def _stage(message: EmailMessage) -> str | None:
    text = f"{message.subject}\n{message.text[:12_000]}"
    for name, pattern in STAGE_PATTERNS:
        if pattern.search(text):
            return name
    return None


def _summary(stage: str, message: EmailMessage) -> str:
    text = f"{message.subject} {message.text[:4000]}".casefold()
    if stage == "interview":
        detail = ("recruiter asked to schedule a phone screen."
                  if "phone screen" in text or "screening call" in text
                  else "employer asked to schedule an interview.")
    elif stage == "next_step":
        if "salary expectation" in text:
            detail = "employer requested availability or salary expectations."
        elif "availability" in text or "available time" in text:
            detail = "employer requested availability."
        elif "additional information" in text:
            detail = "employer requested additional information."
        else:
            detail = "employer provided next-step instructions."
    elif stage == "assessment":
        detail = "employer requested completion of an assessment."
    elif stage == "rejection":
        detail = "employer decided to move forward with other candidates."
    elif stage == "offer":
        detail = "employer sent an employment offer."
    elif stage == "recruiter_outreach":
        detail = "recruiter contacted you about the application."
    else:
        detail = "employer sent an application-status update."
    received = message.received_at.astimezone().strftime("%-m/%-d/%y") if os.name != "nt" else message.received_at.astimezone().strftime("%#m/%#d/%y")
    return f"{STAGE_LABELS[stage]} - {detail} Received {received}."


def score_message(message: EmailMessage, job: JobCandidate) -> tuple[int, bool]:
    haystack = _normalize(f"{message.sender} {message.subject} {message.text}")
    sender_domain = _normalize(_sender_domain(message.sender))
    company = _normalize(job.company)
    title = _normalize(job.title)
    company_tokens = _tokens(job.company, company=True)
    title_tokens = _tokens(job.title)
    words = set(haystack.split())
    score = 0
    job_specific = False
    if company and re.search(rf"\b{re.escape(company)}\b", haystack):
        score += 4
    elif company_tokens and company_tokens <= words:
        score += 3
    if company_tokens & set(sender_domain.split()):
        score += 3
    if title and re.search(rf"\b{re.escape(title)}\b", haystack):
        score += 4
        job_specific = True
    else:
        overlap = len(title_tokens & words)
        if overlap >= min(2, len(title_tokens)) and overlap:
            score += 2
            job_specific = True
    if job.job_number and _normalize(job.job_number) in haystack:
        score += 6
        job_specific = True
    if re.search(r"\b(your application|you applied|candidate|position|role)\b", haystack):
        score += 1
    return score, job_specific


def match_message(message: EmailMessage, jobs: Iterable[JobCandidate]) -> ResponseMatch | None:
    if _generic_message(message):
        return None
    stage = _stage(message)
    if not stage:
        return None
    combined = f"{message.subject} {message.text[:12_000]}"
    if CONFIRMATION_RE.search(combined) and stage in {"status_update", "recruiter_outreach"}:
        return None

    scored = []
    for job in jobs:
        score, job_specific = score_message(message, job)
        if score >= 7:
            scored.append((score, job_specific, job))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_score, best_specific, best_job = scored[0]
    if len(scored) > 1:
        runner_up = scored[1]
        same_company = _normalize(best_job.company) == _normalize(runner_up[2].company)
        if best_score - runner_up[0] < 2 or (same_company and not best_specific):
            return None
    return ResponseMatch(
        best_job, message, stage, best_score, _summary(stage, message)
    )


RECEIVED_RE = re.compile(r"Received\s+(\d{1,2}/\d{1,2}/\d{2,4})\.?$", re.I)


def _existing_stage(text: str) -> str | None:
    normalized = _normalize(text)
    for stage, label in STAGE_LABELS.items():
        if normalized.startswith(_normalize(label)):
            return stage
    return None


def should_replace(existing: str, match: ResponseMatch, prior: dict[str, Any] | None) -> bool:
    if not existing.strip():
        return True
    if prior:
        previous_date = _parse_date(prior.get("received_date"))
        previous_stage = str(prior.get("stage") or "")
    else:
        found = RECEIVED_RE.search(existing.strip())
        previous_date = _parse_date(found.group(1)) if found else None
        previous_stage = _existing_stage(existing) or ""
    incoming_date = match.message.received_at.date()
    if previous_date and incoming_date <= previous_date:
        return False
    if not previous_date or not previous_stage:
        return False
    return STAGE_RANK[match.stage] >= STAGE_RANK.get(previous_stage, 999)


def _candidate_signature(jobs: Iterable[JobCandidate]) -> str:
    payload = [{
        "row": job.row, "company": job.company, "title": job.title,
        "job_url": job.job_url, "job_number": job.job_number,
        "relevant_date": job.relevant_date.isoformat() if job.relevant_date else None,
    } for job in jobs]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": STATE_VERSION, "processed": {}, "rows": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Cannot read Gmail response state {path}: {error}") from error
    if state.get("version") != STATE_VERSION:
        raise RuntimeError(f"Unsupported Gmail response state version in {path}")
    state.setdefault("processed", {})
    state.setdefault("rows", {})
    return state


def run_response_check(tracker, gmail: GmailReader, config: GmailConfig, *, today: date | None = None) -> RunSummary:
    jobs = candidates_from_rows(tracker.applied_response_rows())
    summary = RunSummary()
    if not jobs:
        return summary
    today = today or date.today()
    state = _load_state(config.state_file)
    signature = _candidate_signature(jobs)
    prior_signature = state.get("candidate_signature")
    processed = state["processed"]

    candidate_ids: dict[str, set[int]] = {}
    by_row = {job.row: job for job in jobs}
    for job in jobs:
        for message_id in gmail.search_ids(gmail_query(job, today), config.max_results_per_job):
            candidate_ids.setdefault(message_id, set()).add(job.row)

    row_matches: dict[int, ResponseMatch] = {}
    pending_state: dict[str, dict[str, Any]] = {}
    for message_id, rows in candidate_ids.items():
        prior_message = processed.get(message_id, {})
        if prior_message.get("status") == "matched" or (
            prior_message and prior_signature == signature
        ):
            summary.skipped_processed += 1
            continue
        message = gmail.get_message(message_id)
        summary.emails_checked += 1
        match = match_message(message, [by_row[row] for row in rows])
        if match:
            summary.emails_matched += 1
            current = row_matches.get(match.job.row)
            if current is None or (
                STAGE_RANK[match.stage], match.message.received_at
            ) > (STAGE_RANK[current.stage], current.message.received_at):
                row_matches[match.job.row] = match
            pending_state[message_id] = {
                "status": "matched", "row": match.job.row, "stage": match.stage,
                "received_date": match.message.received_at.date().isoformat(),
            }
        else:
            pending_state[message_id] = {"status": "ignored"}

    updates = {}
    for row, match in row_matches.items():
        prior_row = state["rows"].get(str(row))
        if should_replace(match.job.existing_response, match, prior_row):
            updates[row] = match.summary

    changed = tracker.update_response_rows(updates)
    summary.updated_rows = changed
    summary.tracker_rows_updated = len(changed)
    processed.update(pending_state)
    for row in changed:
        match = row_matches[row]
        state["rows"][str(row)] = {
            "message_id": match.message.message_id,
            "stage": match.stage,
            "received_date": match.message.received_at.date().isoformat(),
            "summary": match.summary,
        }
    state["candidate_signature"] = signature
    state["last_checked_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(config.state_file, state)
    return summary


def run_live_check(*, interactive: bool = False) -> RunSummary:
    _load_project_environment()
    from google_tracker import GoogleTracker

    config = GmailConfig.from_environment()
    gmail = GmailReader(build_gmail_service(config, interactive=interactive))
    return run_response_check(GoogleTracker(), gmail, config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("authorize", help="Authorize Gecko with Gmail read-only access")
    subparsers.add_parser("check", help="Check Gmail and update the canonical Response column")
    args = parser.parse_args(argv)
    try:
        if args.command == "authorize":
            _load_project_environment()
            config = GmailConfig.from_environment()
            build_gmail_service(config, interactive=True)
            print(f"Gmail read-only authorization saved to {config.token_file}")
            return 0
        result = run_live_check()
        print(json.dumps(asdict(result), indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
