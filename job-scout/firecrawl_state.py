"""Shared durable Firecrawl reservations, response cache and discovery outbox.

No network access or database creation occurs on import or configuration reads.
Unknown bills stay reserved permanently until explicitly reconciled with evidence.
"""
from contextlib import contextmanager, closing
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

from sources.base import ProviderError

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "job-scout/preferences/firecrawl.json"
DATABASE = ROOT / "job-scout/data/firecrawl_discovery.sqlite"
SEARCH_MAX_RESULTS = 100  # Documented v2 /search limit; no page/offset parameter.


def utcnow():
    return datetime.now(timezone.utc)


def config():
    settings = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for key in ('enabled', 'daily_enabled', 'require_balance', 'allow_priority_requests'):
        if type(settings.get(key)) is not bool:
            raise ValueError(f'Firecrawl {key} must be true or false')
    if settings.get("timezone") != "America/Denver":
        raise ValueError("Firecrawl budgets require America/Denver")
    for key in ("allocation_credits", "daily_soft_credits", "daily_hard_credits",
                "reservation_headroom", "cache_hours", "results_per_query",
                "max_queries_per_day", "max_scrapes_per_day",
                "max_unknown_date_verifications_per_day", "balance_max_age_seconds"):
        if type(settings[key]) is not int or settings[key] < 0:
            raise ValueError(f"Invalid Firecrawl {key}")
    if not 1 <= settings['results_per_query'] <= SEARCH_MAX_RESULTS:
        raise ValueError('Firecrawl results_per_query must be between 1 and 100')
    headroom = settings.get('search_verification_headroom_credits', 20)
    if type(headroom) is not int or headroom < 0:
        raise ValueError('Firecrawl search verification headroom must be nonnegative')
    if not 0 < settings["daily_soft_credits"] <= settings["daily_hard_credits"] <= 2000:
        raise ValueError("Firecrawl daily budgets must satisfy 0 < soft <= hard <= 2000")
    if not 0 < settings["allocation_credits"] <= 5000:
        raise ValueError("Firecrawl allocation cannot exceed the authorized 5000 credits")
    if settings["posting_window_hours"] != 96:
        raise ValueError("Firecrawl posting window must remain 96 hours")
    if type(settings.get('paid_scrapes_per_query_round', 2)) is not int or not 1 <= settings.get('paid_scrapes_per_query_round', 2) <= 10:
        raise ValueError('Firecrawl per-round verification limit must be between 1 and 10')
    for value in (settings["pricing"]["search_per_10_results"], settings["pricing"]["basic_scrape"]):
        if type(value) is not int or value <= 0:
            raise ValueError("Firecrawl pricing must use positive integer credits")
    # Explicit, per-run authorization. The environment value is a Denver date,
    # so it cannot silently enable unlimited usage on later days.
    if os.environ.get('GECKO_UNLIMITED_USAGE') == utcnow().astimezone(ZoneInfo('America/Denver')).date().isoformat():
        settings['usage_unlimited'] = True
        for key in ('allocation_credits', 'daily_soft_credits', 'daily_hard_credits',
                    'max_queries_per_day', 'max_scrapes_per_day',
                    'max_unknown_date_verifications_per_day'):
            settings[key] = 2**31 - 1
    return settings


def request_key(endpoint, payload):
    return hashlib.sha256(json.dumps([endpoint, payload], sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def confirmed_cost(response, endpoint):
    if not isinstance(response, dict):
        return None
    cost = response.get('creditsUsed')
    if cost is None and endpoint == 'scrape':
        data = response.get('data')
        if isinstance(data, dict):
            cost = (data.get('metadata') or {}).get('creditsUsed')
    return cost if type(cost) is int and cost >= 0 else None


def estimated_cost(endpoint, payload, settings):
    """Allow only bounded basic operations; reject unknown/costly options."""
    if endpoint == "search":
        allowed = {"query", "limit", "sources", "tbs", "location", "country", "timeout", "highlights", "domainTools", "excludeDomains"}
        if set(payload) - allowed or payload.get("sources") != ["web"]:
            raise ProviderError("Firecrawl search requires plain web results without scrapeOptions")
        limit = payload.get("limit", 10)
        if type(limit) is not int or not 1 <= limit <= SEARCH_MAX_RESULTS:
            raise ProviderError("Firecrawl search limit must be bounded")
        if 'excludeDomains' in payload:
            from urllib.parse import urlsplit
            domains = payload['excludeDomains']
            if (not isinstance(domains, list) or not domains
                    or any(not isinstance(d, str) or urlsplit('https://' + d).hostname != d
                           or '/' in d or ':' in d for d in domains)):
                raise ProviderError('Firecrawl domain filters must contain hostnames only')
        return math.ceil(limit / 10) * settings["pricing"]["search_per_10_results"]
    if endpoint == "scrape":
        allowed = {"url", "formats", "onlyMainContent", "maxAge", "proxy", "timeout", "waitFor", "parsers"}
        if (set(payload) - allowed or payload.get("proxy") != "basic"
                or payload.get("parsers") != []
                or not payload.get("formats")
                or any(not isinstance(f, str) or f not in {"markdown", "html", "rawHtml"} for f in payload["formats"])):
            raise ProviderError("Only basic HTML/markdown Firecrawl scraping is permitted")
        if Path(str(payload.get("url", "")).split("?", 1)[0]).suffix.lower() in {".pdf", ".docx", ".xlsx", ".pptx"}:
            raise ProviderError("Paid document parsing is disabled")
        return settings["pricing"]["basic_scrape"]
    raise ProviderError("Firecrawl endpoint is not permitted by Gecko's credit policy")


class History:
    def __init__(self, path=None, settings=None):
        self.path = Path(path or DATABASE)
        self.settings = settings or config()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS requests (
                  id TEXT PRIMARY KEY, request_key TEXT NOT NULL, endpoint TEXT NOT NULL,
                  day TEXT NOT NULL, started_at TEXT NOT NULL, status TEXT NOT NULL,
                  estimate INTEGER NOT NULL, reserved INTEGER NOT NULL, confirmed INTEGER,
                  provider_id TEXT, response_json TEXT, cache_until TEXT, error TEXT,
                  pricing_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS requests_key ON requests(request_key, started_at);
                CREATE TABLE IF NOT EXISTS request_targets (
                  request_id TEXT PRIMARY KEY, url TEXT NOT NULL, payload_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS request_targets_url ON request_targets(url);
                CREATE TABLE IF NOT EXISTS balances (
                  id INTEGER PRIMARY KEY, at TEXT NOT NULL, remaining INTEGER NOT NULL,
                  settled_before INTEGER NOT NULL, raw_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                  day TEXT PRIMARY KEY, started_at TEXT NOT NULL, cutoff TEXT NOT NULL,
                  status TEXT NOT NULL, report_json TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS queries (
                  day TEXT NOT NULL, query_key TEXT NOT NULL, query TEXT NOT NULL,
                  status TEXT NOT NULL, result_json TEXT, stats_json TEXT NOT NULL DEFAULT '{}',
                  PRIMARY KEY(day,query_key));
                CREATE TABLE IF NOT EXISTS identities (
                  identity TEXT PRIMARY KEY, candidate_key TEXT NOT NULL, origin TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS candidates (
                  key TEXT PRIMARY KEY, canonical_url TEXT NOT NULL, original_url TEXT NOT NULL,
                  redirects_json TEXT NOT NULL DEFAULT '[]', employer TEXT, employer_job_id TEXT,
                  ats TEXT, title TEXT, location TEXT, first_at TEXT NOT NULL, last_at TEXT NOT NULL,
                  posted_at TEXT, date_evidence TEXT, discovery_source TEXT NOT NULL DEFAULT 'Firecrawl',
                  successful_crawl_at TEXT, crawl_result TEXT, fingerprint TEXT, cache_until TEXT,
                  retry_at TEXT, verification_status TEXT NOT NULL, credits INTEGER NOT NULL DEFAULT 0,
                  gecko_id INTEGER, tracker_record TEXT, query_key TEXT NOT NULL,
                  raw_json TEXT, search_json TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                  last_attempt_at TEXT, qualified_at TEXT);
                CREATE TABLE IF NOT EXISTS report_outbox (
                  run_id TEXT PRIMARY KEY, fields_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
            """)

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=30)) as con:
            con.row_factory = sqlite3.Row
            with con:
                yield con

    @contextmanager
    def lock(self):
        """OS lock releases on crash; durable rows keep the resumable checkpoint."""
        import msvcrt
        path = self.path.with_suffix(".lock")
        with path.open("a+b") as stream:
            stream.seek(0, 2)
            if not stream.tell():
                stream.write(b"0"); stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ProviderError("Firecrawl discovery or publication is already active") from exc
            try:
                yield
            finally:
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def cached(self, key, now):
        with self.connect() as con:
            row = con.execute("SELECT * FROM requests WHERE request_key=? ORDER BY rowid DESC LIMIT 1", (key,)).fetchone()
        if row and row["response_json"] and row["status"] == "succeeded" and row["cache_until"] >= now.isoformat():
            return json.loads(row["response_json"])
        if row and row["status"] in {"reserved", "unknown", "failed"}:
            raise ProviderError("Prior Firecrawl request has unresolved billing or failed; automatic retry blocked")
        return None

    def remaining_budget(self, day):
        """Planning snapshot only; reserve() remains the transactional authority."""
        usage = self.usage(day)
        with self.connect() as con:
            total = con.execute('SELECT COALESCE(SUM(COALESCE(confirmed,reserved)),0) FROM requests').fetchone()[0]
        available = min(self.settings['daily_soft_credits'] - usage['total_credits_accounted'],
                        self.settings['daily_hard_credits'] - usage['total_credits_accounted'],
                        self.settings['allocation_credits'] - total)
        if usage['estimated_account_balance'] is not None:
            available = min(available, usage['estimated_account_balance'])
        return max(0, available)

    def record_balance(self, data, *, now=None, settled_before=None):
        remaining = data.get("remainingCredits")
        if type(remaining) is not int or remaining < 0:
            raise ProviderError("Firecrawl remaining-credit balance is unavailable; paid requests stopped")
        with self.connect() as con:
            if settled_before is None:
                settled_before = con.execute("SELECT COALESCE(SUM(confirmed),0) FROM requests").fetchone()[0]
            con.execute("INSERT INTO balances(at,remaining,settled_before,raw_json) VALUES(?,?,?,?)",
                        ((now or utcnow()).isoformat(), remaining, settled_before, json.dumps(data)))

    def reserve(self, endpoint, payload, *, now=None, priority_reason=""):
        now = now or utcnow()
        key = request_key(endpoint, payload)
        estimate = estimated_cost(endpoint, payload, self.settings)
        reserved = estimate + self.settings["reservation_headroom"]
        day = now.astimezone(ZoneInfo(self.settings["timezone"])).date().isoformat()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM requests WHERE confirmed > reserved LIMIT 1").fetchone():
                raise ProviderError("Firecrawl provider cost exceeded a reservation; pricing needs review")
            if con.execute("SELECT 1 FROM requests WHERE error='Unexpected provider routing cost; review required' LIMIT 1").fetchone():
                raise ProviderError("Firecrawl provider routing cost needs review")
            prior = con.execute("SELECT * FROM requests WHERE request_key=? ORDER BY rowid DESC LIMIT 1", (key,)).fetchone()
            if prior and (prior["status"] != "succeeded" or prior["cache_until"] >= now.isoformat()):
                raise ProviderError("Firecrawl request already cached, in flight, failed or unresolved; reuse its checkpoint")
            total, today = con.execute("SELECT COALESCE(SUM(COALESCE(confirmed,reserved)),0), COALESCE(SUM(CASE WHEN day=? THEN COALESCE(confirmed,reserved) ELSE 0 END),0) FROM requests", (day,)).fetchone()
            if today + reserved > self.settings["daily_hard_credits"]:
                raise ProviderError("Firecrawl hard daily budget reached, including in-flight headroom")
            if today + reserved > self.settings["daily_soft_credits"] and not (
                    self.settings["allow_priority_requests"] and priority_reason.strip()):
                raise ProviderError("Firecrawl daily soft target reached; paid requests stopped")
            if total + reserved > self.settings["allocation_credits"]:
                raise ProviderError("Firecrawl allocation budget reached")
            balance = con.execute("SELECT * FROM balances ORDER BY id DESC LIMIT 1").fetchone()
            if self.settings["require_balance"] and (balance is None or
                    (now - datetime.fromisoformat(balance["at"])).total_seconds() > self.settings["balance_max_age_seconds"]):
                raise ProviderError("Firecrawl account balance needs reconciliation before paid requests")
            if balance and max(0, total - balance["settled_before"]) + reserved > balance["remaining"]:
                raise ProviderError("Firecrawl reconciled account balance cannot cover the reservation")
            ident = uuid4().hex
            con.execute("INSERT INTO requests(id,request_key,endpoint,day,started_at,status,estimate,reserved,pricing_json) VALUES(?,?,?,?,?,'reserved',?,?,?)",
                        (ident, key, endpoint, day, now.isoformat(), estimate, reserved, json.dumps(self.settings["pricing"])))
            from normalize import canonicalize_url
            con.execute('INSERT INTO request_targets VALUES(?,?,?)',
                        (ident, canonicalize_url(payload.get('url', '')), json.dumps(payload)))
            return ident

    def settle(self, ident, response=None, error=None, *, now=None):
        now = now or utcnow()
        # Only an explicit total is provider-confirmed. Provider-routing subtotals
        # and account-wide balance differences cannot establish a request's bill.
        with self.connect() as con:
            row = con.execute("SELECT * FROM requests WHERE id=?", (ident,)).fetchone()
            if row is None or row["status"] != "reserved":
                raise ValueError("Firecrawl reservation cannot be settled twice")
            cost = confirmed_cost(response, row['endpoint'])
            successful = isinstance(response, dict) and response.get("success") is True and error is None
            metadata = ((response or {}).get('data') or {}).get('metadata', {}) if isinstance((response or {}).get('data'), dict) else {}
            routed_cost = (metadata.get('provider') or {}).get('creditsCost')
            if type(routed_cost) is int and routed_cost > row['reserved']:
                error = 'Unexpected provider routing cost; review required'
                con.execute('UPDATE requests SET reserved=? WHERE id=?', (routed_cost + row['estimate'], ident))
            status = "succeeded" if successful else "unknown"
            con.execute("UPDATE requests SET status=?,confirmed=?,provider_id=?,response_json=?,cache_until=?,error=? WHERE id=?",
                        (status, cost, str((response or {}).get("id", "")), json.dumps(response) if successful else None,
                         (now + timedelta(hours=self.settings["cache_hours"])).isoformat(),
                         str(error or "")[:300], ident))
            if cost is not None and cost > row["reserved"]:
                # A provider price surprise requires review; never launch more calls.
                con.execute("INSERT INTO balances(at,remaining,settled_before,raw_json) VALUES(?,0,0,?)",
                            (now.isoformat(), json.dumps({"blocked": "Provider cost exceeded reserved headroom"})))

    def usage(self, day=None):
        day = day or utcnow().astimezone(ZoneInfo(self.settings["timezone"])).date().isoformat()
        with self.connect() as con:
            rows = con.execute("SELECT * FROM requests WHERE day=?", (day,)).fetchall()
            total = con.execute("SELECT COALESCE(SUM(COALESCE(confirmed,reserved)),0) FROM requests").fetchone()[0]
            balance = con.execute("SELECT * FROM balances ORDER BY id DESC LIMIT 1").fetchone()
        return {"search_credits": sum(r["confirmed"] if r["confirmed"] is not None else r["reserved"] for r in rows if r["endpoint"] == "search"),
                "extraction_credits": sum(r["confirmed"] if r["confirmed"] is not None else r["reserved"] for r in rows if r["endpoint"] == "scrape"),
                "provider_confirmed_credits": sum(r["confirmed"] or 0 for r in rows),
                "estimated_or_reserved_credits": sum(r["reserved"] for r in rows if r["confirmed"] is None),
                "total_credits_accounted": sum(r["confirmed"] if r["confirmed"] is not None else r["reserved"] for r in rows),
                "estimated_account_balance": max(0, balance["remaining"] - max(0, total - balance["settled_before"])) if balance else None,
                "balance_observed_at": balance["at"] if balance else None,
                "billing_complete": all(r["confirmed"] is not None for r in rows),
                "hard_ceiling_exact": False}
