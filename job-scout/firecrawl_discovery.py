"""Once-daily, resumable search-first Firecrawl discovery and Sheet outbox.

Uses Gecko's roles, filters, duplicate/rejection rules, tracker writer and report
writer. Only the Firecrawl client performs paid operations, under its shared ledger.
"""
from dataclasses import asdict
from datetime import datetime, timedelta, time, timezone
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo

from deduplicate import find_duplicate
from description_retrieval import description_is_sufficient
from firecrawl_state import History, DATABASE, config, utcnow, request_key
from firecrawl_search import next_work as next_search_work, extraction_room, coverage
from job_extraction import extract as extract_job_data, salary_display, tracker_notes, sheet_description
from hard_filters import deterministic_filter
from link_validation import BOT, EXPIRED
from models import RawListing, JobListing
from normalize import normalize, canonicalize_url, posting_identity, clean_text
from role_filter import is_relevant_role
from source_policy import is_jooble_candidate
from sources.base import ProviderError
from sources.firecrawl import FirecrawlClient
from sources.firecrawl import target_failure
from firecrawl_postings import reject_result, public_listing
from sources.http import _validate_public_url
from sources.search_discovery import _location
from sources.web import SCRIPT_RE, _job_nodes, _text

ZONE = ZoneInfo("America/Denver")
ATS_HOSTS = {"jobs.lever.co", "job-boards.greenhouse.io", "boards.greenhouse.io",
             "jobs.ashbyhq.com", "apply.workable.com"}
TERMINAL = {"synced", "duplicate", "old", "irrelevant", "review", "blocked"}


def identity(url, employer="", employer_id=""):
    """Preserve ATS requisition IDs, tenants and identity-bearing query strings."""
    parts = urlsplit(canonicalize_url(url))
    host = (parts.hostname or "").casefold().removeprefix("www.")
    pieces = parts.path.strip("/").split("/")
    query = parse_qs(parts.query)
    if query.get("gh_jid"):
        return "greenhouse:" + query["gh_jid"][0]
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and "jobs" in pieces:
        return "greenhouse:" + pieces[pieces.index("jobs") + 1] if pieces.index("jobs") + 1 < len(pieces) else repr(posting_identity(url))
    if host == "jobs.lever.co" and len(pieces) >= 2:
        return "lever:" + "/".join(pieces[:2])
    if host == "jobs.ashbyhq.com" and len(pieces) >= 2:
        return "ashby:" + "/".join(pieces[:2])
    return repr(posting_identity(url))


def employer_identity(company, job_id):
    if company and job_id:
        return "employer:" + clean_text(company).casefold() + ":" + str(job_id).strip().casefold()
    return ""


def remember(history, url, origin, candidate_key="known", company="", job_id=""):
    if not str(url or "").startswith(("http://", "https://")):
        return
    aliases = {identity(url), "url:" + canonicalize_url(url)}
    if company and job_id and not str(job_id).startswith(("http://", "https://")):
        aliases.add(employer_identity(company, job_id))
    with history.connect() as con:
        for alias in aliases:
            con.execute("INSERT OR IGNORE INTO identities VALUES(?,?,?)", (alias, candidate_key, origin))


def known(history, url, *, company="", job_id="", excluding=None):
    aliases = [identity(url), "url:" + canonicalize_url(url)]
    if company and job_id:
        aliases.append(employer_identity(company, job_id))
    with history.connect() as con:
        for alias in aliases:
            row = con.execute("SELECT candidate_key FROM identities WHERE identity=?", (alias,)).fetchone()
            if row and row[0] != excluding:
                return True
    return False


def seed_history(history, store, tracker=None):
    """Retain identities from current AND archived data independently of Sheet rows."""
    aliases = set()
    def seed(url, origin, company='', job_id=''):
        if str(url or '').startswith(('http://', 'https://')):
            aliases.add((identity(url), 'known', origin))
            aliases.add(('url:' + canonicalize_url(url), 'known', origin))
        if company and job_id and not str(job_id).startswith(('http://', 'https://')):
            aliases.add((employer_identity(company, job_id), 'known', origin))
    for job in store.all():
        for url in (job.url, job.canonical_url, job.original_url, job.authoritative_url):
            seed(url, "jobs", company=job.company, job_id=job.source_job_id if job.source in {'lever','ashby','greenhouse','workable'} else '')
        for link in job.source_links:
            seed(link.get("url"), "source_links", company=job.company, job_id=link.get("source_job_id") if link.get('source') in {'lever','ashby','greenhouse','workable'} else '')
    # Imports, applied/manual jobs, rejected jobs and archived Sheet payloads may
    # outlive their current visible rows. Scan their durable JSON/URL fields too.
    def visit(value, origin):
        if isinstance(value, dict):
            company = value.get("Company") or value.get("company") or ""
            job_id = value.get("Job ID") or value.get("source_job_id") or ""
            for key, item in value.items():
                if isinstance(item, str) and item.startswith(('http://', 'https://')):
                    seed(item, origin)
                if isinstance(item, (dict, list)):
                    visit(item, origin)
        elif isinstance(value, list):
            for item in value:
                visit(item, origin)
        elif isinstance(value, str) and value.startswith(('http://', 'https://')):
            seed(value, origin)
    con = store.connection
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("workspace_records", "workspace_archive", "google_tracker_rows", "workspace_manual_jobs", "workspace_manual_resumes"):
        if table not in tables:
            continue
        columns = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        for row in con.execute(f"SELECT * FROM {table}"):
            for name, value in zip(columns, row):
                if isinstance(value, str):
                    if "json" in name:
                        try:
                            visit(json.loads(value), table)
                        except (ValueError, TypeError):
                            pass
                    elif "url" in name:
                        seed(value, table)
    if tracker is not None:
        live_rows = tracker.scout().rows
        live_ids = [int(v.get('Scout ID') or v.get('ID')) for _,v in live_rows
                    if str(v.get('Scout ID') or v.get('ID') or '').isdigit()]
        if live_ids:
            store.observe_scout_id(max(live_ids))
        for _, values in live_rows:
            visit(values, "live_tracker")
        for rejection in tracker.rejected_jobs_index().records:
            seed(rejection.original_url or rejection.normalized_url, "rejection",
                     company=rejection.company, job_id=rejection.job_id)
    with history.connect() as con:
        con.executemany('INSERT OR IGNORE INTO identities VALUES(?,?,?)', sorted(aliases))


def build_queries(preferences):
    """Group configured roles; do not add new role families or reorder synonyms."""
    groups = {}
    families = [r"paid search|ppc|sem|search marketing|google ads", r"paid media", r"performance",
                r"analytics|analyst", r"growth", r"demand", r"e.?commerce", r"digital marketing"]
    for role in preferences.get("target_roles", []):
        normalized = " ".join(sorted(re.findall(r"[a-z0-9]+", role.casefold())))
        family = next((str(i) for i, pattern in enumerate(families) if re.search(pattern, role, re.I)), normalized)
        groups.setdefault(family, {})[normalized] = role
    result = []
    for family, roles in groups.items():
        # Each configured role remains represented; split before the API limit.
        chunks, current = [], []
        for role in roles.values():
            if len(" OR ".join(current + [json.dumps(role)])) > 400 and current:
                chunks.append(current); current = []
            current.append(json.dumps(role))
        if current:
            chunks.append(current)
        for terms in chunks:
            for location in ("Utah", "remote"):
                query = "(" + " OR ".join(terms) + ") job " + location
                result.append({"key": request_key("query", {"query": query}), "query": query,
                               "family": family, "location": location})
    return result


def posting_date(value, now, cutoff):
    """Never infer a timestamp from indexing, modifications or retrieval time."""
    if not isinstance(value, str) or not value.strip():
        return "unknown", None
    value = value.strip()
    try:
        date_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None and not date_only:
            return 'unknown', None  # an employer timestamp has no proven timezone
        if date_only:
            earliest = dt.replace(tzinfo=timezone(timedelta(hours=14)))
            latest = (dt + timedelta(days=1)).replace(tzinfo=timezone(timedelta(hours=-12)))
            if earliest < cutoff < latest:
                return 'unknown', value
            return ('old' if latest <= cutoff else 'recent' if earliest <= now else 'unknown'), value
        if dt > now:
            return "unknown", None
        if date_only and dt < cutoff < dt + timedelta(days=1):
            return "unknown", dt.isoformat()  # cutoff-day time is unproven
        return ("recent" if dt >= cutoff else "old"), dt.isoformat()
    except (ValueError, TypeError, OverflowError):
        return "unknown", None


def extract_listing(data, target):
    """Use public JobPosting JSON-LD without paid AI extraction."""
    page = data.get("rawHtml") or data.get("html") or ""
    nodes = []
    for block in SCRIPT_RE.findall(page):
        try:
            nodes.extend(_job_nodes(json.loads(html.unescape(block))))
        except (ValueError, TypeError):
            continue
    if len(nodes) > 1:
        nodes = [n for n in nodes if n.get("url") and identity(n["url"]) == identity(target)]
    if len(nodes) != 1:
        return None, "", ""
    item = nodes[0]
    employer = _text(item.get("hiringOrganization") or {})
    identifier = item.get('identifier') or ''
    identifier = str(identifier.get('value') or identifier.get('@id') or identifier.get('name') or '') if isinstance(identifier, dict) else str(identifier)
    final_url = (data.get("metadata") or {}).get("url") or (data.get("metadata") or {}).get("sourceURL") or target
    host = (urlsplit(final_url).hostname or "").casefold()
    provider = next((name for name in ("greenhouse", "lever", "ashby", "workable", "indeed") if name in host), host)
    location = _location(item.get("jobLocation") or item.get("applicantLocationRequirements"))
    raw = RawListing(source=provider, source_job_id=identifier or identity(final_url), url=final_url,
                     title=_text(item.get("title")), company=employer, location=location,
                     description=_text(item.get("description")), employment_type=_text(item.get("employmentType")),
                     salary=_text(item.get("baseSalary")), date_posted=str(item.get("datePosted") or ""),
                     remote_type="remote" if item.get("jobLocationType") == "TELECOMMUTE" else "",
                     metadata={**item, "_retrieved_via": "firecrawl", "_discovered_via": "firecrawl-search"})
    evidence = "JobPosting.datePosted: " + raw.date_posted if raw.date_posted else ""
    if raw.date_posted:
        try:
            datetime.fromisoformat(raw.date_posted.replace('Z', '+00:00'))
        except ValueError:
            raw.date_posted = ''; evidence = ''
    # Explicit original dates are accepted only on employer/ATS detail pages.
    organization = item.get('hiringOrganization') or {}
    employer_host = (urlsplit(organization.get('url', '')).hostname or '').casefold() if isinstance(organization, dict) else ''
    if not raw.date_posted and (host in ATS_HOSTS or host == employer_host):
        match = re.search(r"(?im)^\s*(?:original(?:ly)? posted(?: on)?|date posted|posted on)\s*:?\s*(\d{4}-\d{2}-\d{2})(?:\s|$)", data.get("markdown") or "")
        if match:
            raw.date_posted = match[1]; evidence = "Employer listing original date: " + match[0].strip()
    if not raw.date_posted:
        # Schema.org microdata is original posting metadata, unlike a generic
        # document publication/modification or search indexing timestamp.
        for tag in re.findall(r'<(?:meta|time)\b[^>]*>', page, re.I):
            attrs = dict((k.casefold(), v) for k,v in re.findall(r'''([\w:-]+)\s*=\s*["']([^"']*)["']''', tag))
            if attrs.get('itemprop') == 'datePosted' and (attrs.get('content') or attrs.get('datetime')):
                raw.date_posted = attrs.get('content') or attrs['datetime']
                evidence = 'JobPosting original datePosted microdata: ' + raw.date_posted
                break
    return raw, evidence, final_url


def _update(history, key, **values):
    with history.connect() as con:
        con.execute("UPDATE candidates SET " + ",".join(name + "=?" for name in values) + " WHERE key=?", [*values.values(), key])


def _request_credits(history, endpoint, payload):
    with history.connect() as con:
        row = con.execute('SELECT COALESCE(confirmed,reserved) FROM requests WHERE request_key=? ORDER BY rowid DESC LIMIT 1',
                          (request_key(endpoint, payload),)).fetchone()
    return row[0] if row else 0


def _query_order(history, queries):
    with history.connect() as con:
        records = con.execute("SELECT * FROM queries WHERE status='complete' ORDER BY day").fetchall()
    previous, daily = {}, {}
    for record in records:
        stats = json.loads(record["stats_json"])
        root = stats.get('parent_key', record['query_key'])
        totals = daily.setdefault((record['day'], root), [0, 0])
        totals[0] += stats.get('qualified', 0); totals[1] += stats.get('credits', 0)
    for (day, root), (qualified, credits) in sorted(daily.items()):
        previous[root] = (day, qualified / max(1, credits))
    # Never-searched/least-recently-covered groups rotate ahead of repeats;
    # efficiency breaks ties, without deleting poor or untried source coverage.
    return sorted(queries, key=lambda q: (previous.get(q["key"], ("", 0))[0], -previous.get(q["key"], ("", 0))[1], q["key"]))


def run_discovery(store, preferences, *, history=None, client=None, now=None, tracker=None, publish=True, on_saved=None):
    settings = history.settings if history else config()
    if not settings["enabled"] or not settings["daily_enabled"]:
        return {"status": "disabled", "new_job_ids": []}
    history = history or History(settings=settings)
    client = client or FirecrawlClient(history=history)
    now = now or utcnow()
    day = now.astimezone(ZONE).date().isoformat()
    report = {"status": "running", "day": day, "search_queries": 0, "search_results": 0,
              "candidate_urls": 0, "previously_seen": 0, "excluded_age": 0,
              "excluded_irrelevant": 0, "unknown_dates": 0, "pages_scraped": 0,
              "successful_scrapes": 0, "failed_scrapes": 0, "new_qualified": 0,
              "new_job_ids": [], "queries": [], "sources": {}}
    public_cache = {}
    with history.lock():
        with history.connect() as con:
            run = con.execute("SELECT * FROM runs WHERE day=?", (day,)).fetchone()
            if run and run["status"] == "complete":
                report = json.loads(run["report_json"])
                report["status"] = "already_complete"
            else:
                if run:
                    report.update(json.loads(run["report_json"]))
                    report["status"] = "running"
                    cutoff = datetime.fromisoformat(run["cutoff"])
                    report.pop('stop_reason', None)
                else:
                    cutoff = now - timedelta(hours=96)
                    con.execute("INSERT INTO runs(day,started_at,cutoff,status) VALUES(?,?,?,'running')", (day, now.isoformat(), cutoff.isoformat()))
        if report["status"] != "already_complete":
            seed_history(history, store, tracker)
            queries = _query_order(history, build_queries(preferences))
            while True:
                with history.connect() as con:
                    saved_queries = {r['query_key']: dict(r) for r in con.execute("SELECT * FROM queries WHERE day=?", (day,))}
                work = next_search_work(history, queries, day, cutoff, now, ZONE)
                for query in ([work] if work is not None else []):
                    payload = query['payload']
                    try:
                        results = ({'web': json.loads(saved_queries[query['key']]['result_json'])}
                                   if query['key'] in saved_queries else client.call("search", payload))
                    except ProviderError as exc:
                        report["status"] = "paused"; report["stop_reason"] = str(exc)
                        break
                    web = results.get("web", []) if isinstance(results, dict) else results
                    if not isinstance(web, list):
                        report["status"] = "paused"; report["stop_reason"] = "Unexpected Firecrawl web results"
                        break
                    query_cost = _request_credits(history, 'search', payload)
                    query_stats = {'search_credits': query_cost, 'parent_key': query['parent_key'],
                                   'kind': query['kind'], 'depth': query['depth'], 'payload': payload,
                                   'requested_limit': payload['limit'], 'previously_seen': 0, 'new_candidates': 0}
                    with history.connect() as con:
                        con.execute("INSERT OR REPLACE INTO queries(day,query_key,query,status,result_json,stats_json) VALUES(?,?,?,'retrieved',?,?)", (day, query["key"], query["query"], json.dumps(web), json.dumps(query_stats)))
                    saved_queries[query['key']] = {'status': 'retrieved', 'result_json': json.dumps(web)}
                    report["search_queries"] += 1; report["search_results"] += len(web)
                    for result in web:
                        target = result.get("url") or ""
                        if not target:
                            continue
                        report["candidate_urls"] += 1
                        try:
                            _validate_public_url(target)
                        except (ValueError, ProviderError):
                            report["excluded_irrelevant"] += 1; continue
                        if known(history, target):
                            query_stats['previously_seen'] += 1
                            report["previously_seen"] += 1; continue
                        title = result.get("title") or ""
                        if (reject_result(target, title, cutoff) or not is_relevant_role(title)
                                or is_jooble_candidate(source="", urls=(target,), metadata=result)):
                            report["excluded_irrelevant"] += 1
                            remember(history, target, "irrelevant"); continue
                        # Explicit result locations can cheaply reject obvious
                        # non-Utah on-site listings; snippets never prove eligibility.
                        location_hint = result.get('location')
                        if isinstance(location_hint, str) and location_hint.strip():
                            from google_tracker import resume_approval_value
                            if resume_approval_value(location_hint, result.get('workArrangement', ''), '') != 'Yes':
                                report['excluded_irrelevant'] += 1
                                remember(history, target, 'outside configured geography'); continue
                        key = identity(target)
                        original_hint = result.get('jobPosting') or {}
                        hint_state, hint_date = posting_date(original_hint.get('datePosted'), now, cutoff) if isinstance(original_hint, dict) and original_hint.get('@type') == 'JobPosting' else ('unknown', None)
                        # Search snippets/index dates are hints only. No date or remote
                        # claim is trusted until the actual listing is verified.
                        with history.connect() as con:
                            con.execute("INSERT OR IGNORE INTO candidates(key,canonical_url,original_url,title,first_at,last_at,verification_status,query_key,search_json) VALUES(?,?,?,?,?,?,'queued',?,?)",
                                        (key, canonicalize_url(target), target, title, now.isoformat(), now.isoformat(), query["key"], json.dumps(result)))
                            con.execute("UPDATE candidates SET last_at=? WHERE key=?", (now.isoformat(), key))
                        remember(history, target, "search", candidate_key=key)
                        query_stats['new_candidates'] += 1
                        if hint_state == 'old':
                            _update(history, key, verification_status='old', posted_at=hint_date,
                                    date_evidence='Search JobPosting original datePosted hint: ' + str(original_hint.get('datePosted')))
                            report['excluded_age'] += 1
                    with history.connect() as con:
                        con.execute("UPDATE queries SET status='complete',stats_json=? WHERE day=? AND query_key=?", (json.dumps(query_stats), day, query['key']))
                    _checkpoint(history, day, report)
                with history.connect() as con:
                    pending = con.execute("SELECT * FROM candidates WHERE verification_status IN ('queued','extracted','validated') ORDER BY CASE WHEN original_url LIKE '%jobs.lever.co/%' OR original_url LIKE '%greenhouse.io/%' OR original_url LIKE '%jobs.ashbyhq.com/%' THEN 0 ELSE 1 END, first_at,key").fetchall()
                    scraped_today = con.execute("SELECT COUNT(*) FROM requests WHERE day=? AND endpoint='scrape'", (day,)).fetchone()[0]
                    unknown_today = scraped_today
                paid_this_round = 0
                for row in pending:
                    key = row["key"]
                    if row['verification_status'] == 'validated' and row['gecko_id'] and store.get(row['gecko_id']) is not None and store.get_job_document(row['gecko_id']):
                        continue
                    raw = RawListing(**json.loads(row["raw_json"])) if row["raw_json"] else None
                    if raw is None:
                        if known(history, row["original_url"], excluding=key):
                            _update(history, key, verification_status="duplicate")
                            report["previously_seen"] += 1; continue
                        rejection = reject_result(row['original_url'], row['title'] or '', cutoff)
                        if rejection:
                            _update(history, key, verification_status='irrelevant', crawl_result=rejection)
                            report['excluded_irrelevant'] += 1; continue
                        try:
                            public = public_listing(row['original_url'], public_cache)
                        except ProviderError as exc:
                            _update(history, key, verification_status='blocked', crawl_result=str(exc)[:600],
                                    last_attempt_at=now.astimezone(ZONE).isoformat())
                            report['public_page_failures'] = report.get('public_page_failures', 0) + 1
                            continue
                        if public is None:
                            if (scraped_today >= settings["max_scrapes_per_day"]
                                    or unknown_today >= settings["max_unknown_date_verifications_per_day"]
                                    or (work is not None and paid_this_round >= settings.get('paid_scrapes_per_query_round', 2))):
                                continue
                            scrape_reservation = settings['pricing']['basic_scrape'] + settings['reservation_headroom']
                            if extraction_room(history, queries, day) < scrape_reservation:
                                continue  # Preserve admission capacity for uncovered categories.
                        payload = {"url": row["original_url"], "formats": ["rawHtml", "markdown"],
                                   "onlyMainContent": True, "proxy": "basic", "parsers": [], "maxAge": 86400000}
                        _update(history, key, attempts=row["attempts"] + 1, last_attempt_at=now.astimezone(ZONE).isoformat(), crawl_result="retrieving original posting")
                        try:
                            if public is not None:
                                data = public[0]
                                report['public_ats_verified'] = report.get('public_ats_verified', 0) + 1
                            else:
                                report["pages_scraped"] += 1; scraped_today += 1; unknown_today += 1; paid_this_round += 1
                                data = client.call("scrape", payload)
                        except ProviderError as exc:
                            report["failed_scrapes"] += 1
                            report["stop_reason"] = str(exc)
                            # The client checkpoint blocks uncertain repeats; budget
                            # denials before sending can resume safely on another day.
                            report["status"] = "paused"
                            with history.connect() as con:
                                prior = con.execute('SELECT status FROM requests WHERE request_key=? ORDER BY rowid DESC LIMIT 1', (request_key('scrape', payload),)).fetchone()
                            if prior and prior['status'] in {'reserved', 'unknown', 'failed'}:
                                _update(history, key, verification_status='review', crawl_result='Request billing/result unresolved; no automatic retry')
                            _update(history, key, credits=_request_credits(history, 'scrape', payload))
                            _checkpoint(history, day, report)
                            if target_failure(exc, 'scrape'):
                                report['status'] = 'running'
                                report.pop('stop_reason', None)
                                _update(history, key, verification_status='blocked', crawl_result=str(exc)[:600])
                                continue  # Do not retry or bypass this target; other groups can run.
                            break
                        meta = data.get("metadata") or {}
                        _update(history, key, credits=_request_credits(history, 'scrape', payload))
                        final_url = meta.get("url") or meta.get("sourceURL") or row["original_url"]
                        try:
                            _validate_public_url(final_url)
                        except (ValueError, ProviderError):
                            _update(history, key, verification_status='blocked', crawl_result='Unsafe redirect')
                            report['failed_scrapes'] += 1; continue
                        markdown = data.get("markdown") or clean_text(data.get("rawHtml") or data.get("html"))
                        fingerprint = hashlib.sha256(markdown.encode()).hexdigest()
                        _update(history, key, successful_crawl_at=now.isoformat(), crawl_result=str(meta.get("statusCode", 200)),
                                fingerprint=fingerprint, cache_until=(now + timedelta(hours=settings["cache_hours"])).isoformat(),
                                redirects_json=json.dumps([row["original_url"], final_url]))
                        if meta.get("statusCode", 200) != 200 or BOT.search(markdown) or EXPIRED.search(markdown):
                            _update(history, key, verification_status="blocked")
                            report["failed_scrapes"] += 1; continue
                        report["successful_scrapes"] += 1
                        raw, evidence, final_url = public[1:] if public is not None else extract_listing(data, row["original_url"])
                        if raw is None:
                            _update(history, key, verification_status="review", date_evidence="No unique public JobPosting; original date unverified")
                            report["unknown_dates"] += 1; continue
                        document = extract_job_data(data, raw, evidence)
                        raw.metadata['_extraction'] = document
                        raw.description = document['full_description_markdown']
                        raw.employment_type = '; '.join(document['fields']['employment_types'])
                        from salary_format import extract_salary
                        raw.salary = extract_salary(
                            salary_display(document['fields']['salary']), raw.description, raw.metadata)
                        raw.remote_type = document['fields']['work_arrangement'] or ''
                        _update(history, key, raw_json=json.dumps(asdict(raw)), date_evidence=evidence,
                                employer=raw.company, employer_job_id=raw.source_job_id, ats=raw.source,
                                title=raw.title, location=raw.location, verification_status="extracted")
                        if known(history, final_url, company=raw.company, job_id=raw.source_job_id, excluding=key):
                            _update(history, key, verification_status="duplicate")
                            report["previously_seen"] += 1; continue
                        remember(history, final_url, "extraction", candidate_key=key, company=raw.company, job_id=raw.source_job_id)
                    document = raw.metadata.get('_extraction')
                    if document and document['status'] != 'complete':
                        _update(history, key, verification_status='review', crawl_result='; '.join(document['issues']))
                        continue
                    freshness, posted = posting_date(raw.date_posted, now, cutoff)
                    _update(history, key, posted_at=posted)
                    if freshness != "recent":
                        _update(history, key, verification_status="old" if freshness == "old" else "review")
                        report["excluded_age" if freshness == "old" else "unknown_dates"] += 1; continue
                    with history.connect() as con:
                        query_row = con.execute('SELECT query FROM queries WHERE query_key=? ORDER BY day LIMIT 1', (row['query_key'],)).fetchone()
                    if query_row:
                        raw.metadata['_query_used_to_find'] = query_row['query']
                        from query_provenance import remember as remember_query
                        remember_query([raw])
                    job = normalize(raw, discovered=now.astimezone(ZONE).date().isoformat())
                    job.found_using = "Firecrawl"
                    if document:
                        job.description = document['full_description_markdown']
                        job.details = document
                        job.work_arrangement = document['fields']['work_arrangement'] or 'unknown'
                    from google_tracker import resume_approval_value
                    if tracker is not None and tracker.rejected_jobs_index().matches_job(job) is not None:
                        _update(history, key, verification_status='duplicate')
                        report['previously_seen'] += 1; continue
                    accepted, reason = deterministic_filter(job, preferences)
                    if not accepted or resume_approval_value(job.location, job.work_arrangement, "") != "Yes" or not description_is_sufficient(job.description):
                        _update(history, key, verification_status="irrelevant", crawl_result=reason if not accepted else "Eligibility/content needs review")
                        report["excluded_irrelevant"] += 1; continue
                    from service import _same_source_identity_conflicts
                    existing = find_duplicate(job, [j for j in store.all() if not _same_source_identity_conflicts(job, j)])
                    if existing and existing.id != row["gecko_id"]:
                        _update(history, key, verification_status="duplicate", gecko_id=existing.id)
                        report["previously_seen"] += 1; continue
                    from resume_match import check as check_resume_match, explanation as match_explanation
                    match = check_resume_match(job)
                    if not match['accepted']:
                        _update(history, key, verification_status='review' if match['status'] == 'pending' else 'irrelevant',
                                crawl_result=match_explanation(match))
                        report['excluded_irrelevant'] += 1
                        continue
                    # Reserve the Gecko ID durably BEFORE inserting across databases.
                    # An interrupted insert can recover its exact identity without
                    # interpreting a missing tracker row as a newly discovered job.
                    job.id = row["gecko_id"] or store.highest_scout_id() + 1
                    store.observe_scout_id(job.id)
                    fee_required = bool(document and document['fields']['application_fee_required'] is True)
                    _update(history, key, gecko_id=job.id, verification_status="validated", qualified_at=None if fee_required else row['qualified_at'] or now.astimezone(ZONE).isoformat())
                    if store.get(job.id) is None:
                        store.save(job, job_id=job.id)
                    if document:
                        store.save_job_document(job.id, document)
                    if not fee_required and job.id not in report["new_job_ids"]:
                        report["new_job_ids"].append(job.id); report["new_qualified"] += 1
                        if on_saved is not None:
                            on_saved(job.id)
                    source = raw.source
                    report["sources"][source] = report["sources"].get(source, 0) + 1
                    _checkpoint(history, day, report)
                if work is None or report["status"] == "paused":
                    break
            report['queries'] = []
            report['query_coverage'] = coverage(history, queries, day)
            report['pagination'] = {'supported': False, 'mode': 'adaptive_expansion',
                                    'expansion_requests': report['query_coverage']['expansion_requests']}
            with history.connect() as con:
                for query in con.execute("SELECT * FROM queries WHERE day=?", (day,)).fetchall():
                    qualified = con.execute("SELECT COUNT(*) FROM candidates WHERE query_key=? AND first_at>=? AND qualified_at IS NOT NULL AND verification_status IN ('validated','synced')", (query["query_key"], day)).fetchone()[0]
                    duplicate_count = con.execute("SELECT COUNT(*) FROM candidates WHERE query_key=? AND first_at>=? AND verification_status='duplicate'", (query["query_key"], day)).fetchone()[0]
                    prior_stats = json.loads(query['stats_json'])
                    duplicate_count += prior_stats.get('previously_seen', 0)
                    extraction_cost = con.execute('SELECT COALESCE(SUM(credits),0) FROM candidates WHERE query_key=? AND first_at>=?', (query['query_key'], day)).fetchone()[0]
                    stats = {**prior_stats, "work_key": query['query_key'], "query": query["query"], "results": len(json.loads(query["result_json"] or "[]")),
                             "qualified": qualified, "duplicates": duplicate_count,
                             "search_credits": prior_stats.get('search_credits', 0),
                             "credits": prior_stats.get('search_credits', 0) + extraction_cost,
                             "duplicate_rate": duplicate_count / max(1, len(json.loads(query['result_json'] or '[]')))}
                    con.execute("UPDATE queries SET stats_json=? WHERE day=? AND query_key=?", (json.dumps(stats), day, query["query_key"]))
                    report["queries"].append(stats)
                # Derive completed counters from durable rows, including recovery
                # after a crash between inserting the Gecko job and checkpointing.
                todays_queries = con.execute('SELECT result_json FROM queries WHERE day=?', (day,)).fetchall()
                qualified_ids = [r[0] for r in con.execute("SELECT gecko_id FROM candidates WHERE qualified_at LIKE ? AND verification_status IN ('validated','synced')", (day + '%',))]
                report['search_queries'] = len(todays_queries)
                report['search_results'] = sum(len(json.loads(r[0] or '[]')) for r in todays_queries)
                report['new_job_ids'] = qualified_ids
                report['new_qualified'] = len(qualified_ids)
                report['unknown_dates'] = con.execute("SELECT COUNT(*) FROM candidates WHERE posted_at IS NULL AND verification_status IN ('queued','review') AND (first_at>=? OR last_attempt_at LIKE ?)", (day, day + '%')).fetchone()[0]
                report['duplicate_rate'] = min(1, sum(q['duplicates'] for q in report['queries']) / max(1, report['search_results']))
                source_stats = {}
                for candidate in con.execute('SELECT * FROM candidates WHERE last_attempt_at LIKE ? OR qualified_at LIKE ?', (day + '%', day + '%')):
                    source = candidate['ats'] or urlsplit(candidate['original_url']).hostname or 'unknown'
                    entry = source_stats.setdefault(source, {'new_qualified': 0, 'pages_checked': 0, 'extraction_credits_accounted': 0})
                    entry['new_qualified'] += int(candidate['qualified_at'] is not None and candidate['qualified_at'].startswith(day))
                    entry['pages_checked'] += 1
                    entry['extraction_credits_accounted'] += candidate['credits']
                report['source_efficiency'] = source_stats
                report['top_queries'] = sorted([q for q in report['queries'] if q['qualified']],
                    key=lambda q: q['qualified'] / max(1, q['credits']), reverse=True)[:5]
            if report['status'] == 'running':
                report['status'] = 'complete' if not report['query_coverage']['uncovered_queries'] else 'budget_limited'
            _checkpoint(history, day, report)
    if publish:
        try:
            import sheet_sync
            sheet_sync.sync()
            report["publication"] = "verified"
        except Exception as exc:
            report["publication"] = "pending: " + type(exc).__name__
    report.update(history.usage(day))
    report["credits_per_new_qualified_job"] = report["total_credits_accounted"] / report["new_qualified"] if report["new_qualified"] else None
    report["next_day_opportunity"] = "Reuse pending/cache entries; rotate least-covered configured roles before repeating searches."
    _checkpoint(history, day, report)
    return report


def _checkpoint(history, day, report):
    with history.connect() as con:
        con.execute("UPDATE runs SET status=?,report_json=? WHERE day=?", ('complete' if report['status'] == 'already_complete' else report["status"], json.dumps(report), day))


def queue_report(fields):
    """Existing Daily Run writer produces these fields; this is a delivery outbox."""
    history = History()
    with history.connect() as con:
        con.execute("INSERT OR IGNORE INTO report_outbox(run_id,fields_json) VALUES(?,?)", (fields["Run ID"], json.dumps(fields)))


def flush_pending(*, history=None, remote=None, store=None):
    """Retry publication only. This function never creates a Firecrawl client."""
    if history is None and not DATABASE.exists():
        return {"jobs": 0, "reports": 0}
    history = history or History()
    with history.connect() as con:
        pending = con.execute("SELECT * FROM candidates WHERE verification_status='validated'").fetchall()
        reports = con.execute("SELECT * FROM report_outbox WHERE status='pending'").fetchall()
    if not pending and not reports:
        return {"jobs": 0, "reports": 0}
    from google_tracker import GoogleTracker, Config, load_environment
    from sheet_sync import ensure_frozen_headers
    from storage import JobStore
    load_environment()
    remote = remote or GoogleTracker(config=Config.from_environment())
    owned_store = store is None
    store = store or JobStore()
    result = {"jobs": 0, "reports": 0}
    try:
        with history.lock():
            ensure_frozen_headers(remote)
            for row in pending:
                tab = remote.scout()
                from description_columns import description_column
                target_description = description_column(tab.headers, 'Firecrawl')
                required = {"Found Using", target_description}
                if not required.issubset(tab.headers):
                    raise RuntimeError("Firecrawl publication requires Found Using and the Firecrawl description column")
                job = store.get(row["gecko_id"])
                if job is None:
                    raise RuntimeError("Pending Firecrawl job is missing from durable Gecko storage")
                matches = [(number, values) for number, values in tab.rows if values.get("Job URL") and identity(values["Job URL"]) == identity(job.url)]
                if len(matches) > 1:
                    raise RuntimeError("Pending Firecrawl posting has multiple live tracker matches")
                if matches:
                    number, values = matches[0]
                    # Preserve first-source/manual cells on an existing posting.
                    _update(history, row["key"], verification_status="synced", tracker_record=str(values.get("Scout ID") or values.get("ID")))
                    result["jobs"] += 1
                    continue
                if remote.rejected_jobs_index().matches_job(job) is not None:
                    _update(history, row["key"], verification_status="duplicate")
                    continue
                if any(str(v.get("Scout ID") or v.get("ID")) == str(job.id) for _, v in tab.rows):
                    raise RuntimeError("Pending Firecrawl ID conflicts with another live posting")
                note = tracker_notes(job.details)
                if not sheet_description(job.description):
                    note += '\nFull original description exceeds the Sheet cell limit; retained in Gecko job_documents, job ID ' + str(job.id)
                written = remote.upsert_scout([job], append_only=True, discovery_notes={
                    job.id: row["first_at"] + " | Firecrawl | Original posting date verified: " + str(row["date_evidence"]) + ('\n' + note if note else '')
                })
                if written.get('match_excluded'):
                    exclusion = written['match_excluded'][0]
                    if exclusion['status'] != 'pending':
                        _update(history, row['key'], verification_status='irrelevant', crawl_result=exclusion['reason'])
                    continue
                after = [(n, v) for n, v in remote.scout().rows if str(v.get("Scout ID") or v.get("ID")) == str(job.id)]
                if (len(after) != 1 or identity(after[0][1].get("Job URL", "")) != identity(job.url)
                        or after[0][1].get("Found Using") != "Firecrawl"
                        or after[0][1].get(target_description, '') != sheet_description(job.description)
                        or not written.get("readback_verified")):
                    raise RuntimeError("Firecrawl tracker publication failed verified readback")
                _update(history, row["key"], verification_status="synced", tracker_record=str(job.id))
                result["jobs"] += 1
            if reports:
                import sys
                sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
                from daily_run_history import write_history
                for report in reports:
                    write_history(remote, json.loads(report["fields_json"]))
                    with history.connect() as con:
                        con.execute("UPDATE report_outbox SET status='synced' WHERE run_id=?", (report["run_id"],))
                    result["reports"] += 1
    finally:
        if owned_store:
            store.close()
    return result
