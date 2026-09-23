"""Conservative, redirect-aware job availability checks for the daily run."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html import unescape
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener

from models import JobListing
from sources.http import USER_AGENT, _PublicRedirectHandler, _validate_public_url
from url_resolution import classify_url


EXPIRED = re.compile(
    r"\b(?:this|the|that|requested)?\s*(?:job|position|posting|vacancy|opportunity)\s+"
    r"(?:is|has been|was)?\s*(?:no longer available|no longer open|no longer exists|closed|expired|removed|filled)\b"
    r"|\bno longer accepting applications\b"
    r"|\bapplications? (?:are|is) (?:now )?closed\b",
    re.I,
)
BOT = re.compile(r"cloudflare|checking your browser|verify you are human|captcha|access denied|bot protection", re.I)
TAG = re.compile(r"<[^>]+>")
SCRIPT = re.compile(r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>", re.I | re.S)


@dataclass(frozen=True)
class LinkResult:
    status: str  # valid, dead, temporary_failure
    url: str
    final_url: str = ""
    reason: str = ""
    http_status: int | None = None


def _request(url: str, *, timeout: int = 12) -> LinkResult:
    try:
        _validate_public_url(url)
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json"})
        with build_opener(_PublicRedirectHandler()).open(request, timeout=timeout) as response:
            final_url = response.geturl()
            _validate_public_url(final_url)
            status = response.status
            body = response.read(750_000).decode("utf-8", errors="replace")
            if status in (404, 410):
                return LinkResult("dead", url, final_url, f"HTTP {status} at final URL", status)
            if status != 200:
                return LinkResult("temporary_failure", url, final_url, f"HTTP {status}", status)
            visible = unescape(TAG.sub(" ", SCRIPT.sub(" ", body)))
            visible = re.sub(r"\s+", " ", visible)
            if BOT.search(visible[:3000]):
                return LinkResult("temporary_failure", url, final_url, "Bot protection or access challenge", status)
            if EXPIRED.search(visible):
                return LinkResult("dead", url, final_url, "Page explicitly says the job is closed or unavailable", status)
            return LinkResult("valid", url, final_url, "Listing loaded", status)
    except HTTPError as error:
        final_url = error.geturl() or url
        status = error.code
        if status in (404, 410):
            return LinkResult("dead", url, final_url, f"HTTP {status} at final URL", status)
        return LinkResult("temporary_failure", url, final_url, f"HTTP {status}", status)
    except (URLError, TimeoutError, OSError, ValueError) as error:
        return LinkResult("temporary_failure", url, "", f"Request failed: {type(error).__name__}")


def official_api_url(url: str) -> str:
    """Known public, job-specific ATS endpoints; absence is authoritative."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = [item for item in parts.path.strip("/").split("/") if item]
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and len(path) >= 3 and path[1] == "jobs":
        return f"https://boards-api.greenhouse.io/v1/boards/{quote(path[0])}/jobs/{quote(path[2])}"
    if host == "jobs.lever.co" and len(path) >= 2:
        return f"https://api.lever.co/v0/postings/{quote(path[0])}/{quote(path[1])}"
    return ""


def validate_url(url: str) -> LinkResult:
    if not url or not urlsplit(url).scheme:
        return LinkResult("temporary_failure", url, reason="Missing or invalid job URL")
    api = official_api_url(url)
    if api:
        api_result = _request(api)
        if api_result.status == "dead":
            page = _request(url)
            if page.status == "valid":
                return page
            return LinkResult("dead", url, api_result.final_url, "Official ATS API confirms posting absent", api_result.http_status)
    page = _request(url)
    return page


def candidate_urls(job: JobListing) -> list[str]:
    urls = []
    def add(value: str):
        if value and value not in urls:
            urls.append(value)
    if job.authoritative_url:
        add(job.authoritative_url)
    for link in job.source_links:
        url = link.get("url", "")
        if classify_url(url) == "official_ats":
            add(url)
    if job.original_url:
        add(job.original_url)
    add(job.canonical_url)
    add(job.url)
    for link in job.source_links:
        add(link.get("url", ""))
    return urls[:4]


def validate_job(job: JobListing) -> LinkResult:
    urls = candidate_urls(job)
    if not urls:
        return LinkResult("temporary_failure", "", reason="No job URL available")
    failures = []
    dead = []
    for url in urls:
        result = validate_url(url)
        if result.status == "valid":
            return result
        if result.status == "dead":
            dead.append(result)
            if result.reason.startswith("Official ATS API"):
                return result
        else:
            failures.append(result)
    if failures:
        return failures[0]
    return dead[0]


class DailyLinkValidator:
    def __init__(self):
        self._lock = Lock()
        self.results: dict[str, LinkResult] = {}
        self.checked = 0
        self.valid = 0
        self.removed_dead = 0
        self.temporary_failure = 0
        self.removed: list[dict] = []
        self.protected_dead = 0

    def check(self, job: JobListing) -> LinkResult:
        try:
            key = "|".join(candidate_urls(job))
        except Exception:
            key = f"unresolved:{job.id or job.source_job_id or job.url}"
        with self._lock:
            result = self.results.get(key)
        if result is None:
            try:
                result = validate_job(job)
            except Exception as error:
                result = LinkResult("temporary_failure", job.url,
                                    reason=f"Validation error: {type(error).__name__}")
        with self._lock:
            self.results[key] = result
            self.checked += 1
            if result.status == "valid":
                self.valid += 1
            elif result.status == "temporary_failure":
                self.temporary_failure += 1
        return result

    def check_existing(self, jobs: list[JobListing], *, workers: int = 8) -> list[tuple[JobListing, LinkResult]]:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.check, job): job for job in jobs}
            return [(futures[future], future.result()) for future in as_completed(futures)]

    def record_removed(self, job: JobListing, result: LinkResult) -> None:
        self.removed_dead += 1
        self.removed.append({"company": job.company, "job_title": job.title,
                             "url": result.final_url or result.url, "reason_removed": result.reason,
                             "http_status": result.http_status})

    def report(self) -> dict:
        return {"checked": self.checked, "valid": self.valid,
                "removed_dead": self.removed_dead, "temporary_failure": self.temporary_failure,
                "protected_dead": self.protected_dead, "removed": self.removed}
