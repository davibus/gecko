"""Durable daily admission before retrieval. Broad search and maintenance are opt-in.

The shared History OS lock covers ingestion, retrieval and publication. SQLite
checkpoints precede external effects; a dispatched paid request is never retried
automatically, even if its caller crashes before recording the response.
"""
from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from description_retrieval import description_is_sufficient
from firecrawl_state import History
from models import RawListing, JobListing
from normalize import normalize, posting_identity, posting_aliases, canonicalize_url
from sources.http import safe_error

ROOT = Path(__file__).resolve().parents[1]
ZONE = ZoneInfo('America/Denver')
# These implementations use public feeds or authorized APIs, never Firecrawl.
FREE_SOURCES = ('greenhouse', 'lever', 'ashby', 'workable', 'remotive', 'jobicy',
                'remoteok', 'usajobs', 'weworkremotely', 'workingnomads', 'themuse', 'adzuna')
RETRY_DAYS = 7


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def aliases(job):
    result = {'url:' + repr(v) for v in posting_aliases(job)}
    from firecrawl_discovery import identity
    result.update('ats:' + identity(url) for url in [job.url, job.canonical_url, job.authoritative_url,
                  *(v.get('url', '') for v in job.source_links)] if url)
    # Source IDs are source-qualified. ATS IDs are additionally tenant-qualified
    # where their provider supplies tenant-local IDs.
    for link in [dict(source=job.source, source_job_id=job.source_job_id, url=job.url), *job.source_links]:
        source, key = str(link.get('source') or '').casefold(), str(link.get('source_job_id') or '')
        if source and key:
            result.add('source:' + source + ':' + key)
        if link.get('source_requisition_id'):
            result.add('requisition:'+str(link['source_requisition_id']))
    return result


def complete(raw):
    return (raw.source.casefold() != 'adzuna'
            and not any(raw.metadata.get(k) for k in ('truncated', '_snippet', '_incomplete'))
            and description_is_sufficient(raw.description)
            and not re.search(r'(?:read more|show more|view full description|sign in to view)\s*[.!]*$', raw.description, re.I))


def free_retrieve(raw):
    """Exact public ATS API, then permitted ordinary HTML; no search or AI."""
    from firecrawl_postings import public_listing
    from description_retrieval import retrieve_full_description
    from sources.base import ProviderError
    try:
        found = public_listing(raw.url)
    except (ProviderError, OSError, ValueError) as exc:
        # Explicit restrictions/access failures must not be bypassed with a proxy.
        if re.search(r'401|402|403|429|robots|not allowed|not supported', str(exc), re.I):
            raise
        found = None
    if found:
        data, extracted, evidence, final = found
        return exact_result(raw, data, extracted, evidence, final)
    outcome = retrieve_full_description(normalize(raw))
    if outcome.status == 'succeeded' and posting_identity(outcome.source_url or raw.url) == posting_identity(raw.url):
        return {'description': outcome.description, 'url': outcome.source_url or raw.url}
    return None


def exact_result(raw, data, extracted, evidence, final):
    from job_extraction import extract
    if extracted is None:
        return None
    # Redirects cannot silently substitute another requisition or employer.
    if (extracted.title.casefold() != raw.title.casefold()
            or extracted.company.casefold() != raw.company.casefold()):
        raise ValueError('Retrieved posting title/company differs; exact identity needs review')
    if (str(extracted.source).casefold() == str(raw.source).casefold()
            and extracted.source_job_id and raw.source_job_id
            and str(extracted.source_job_id) != str(raw.source_job_id)):
        raise ValueError('Retrieved source requisition ID differs; exact identity needs review')
    declared = extracted.metadata.get('url')
    if declared and posting_identity(declared) != posting_identity(final):
        raise ValueError('JobPosting URL does not match retrieved posting')
    document = extract(data, extracted, evidence)
    if document['status'] != 'complete':
        return None
    return {'description': document['full_description_markdown'], 'url': final,
            'document': document, 'raw': asdict(extracted)}


def saved_transport(history, target):
    """Immutable discovery evidence is reusable beyond the maintenance cache TTL."""
    with history.connect() as con:
        rows = con.execute("SELECT status,response_json FROM requests WHERE endpoint='scrape' ORDER BY started_at DESC").fetchall()
    for row in rows:
        response = json.loads(row['response_json'] or '{}')
        saved = response.get('data') or {}
        url = (saved.get('metadata') or {}).get('sourceURL') or (saved.get('metadata') or {}).get('url')
        if url and posting_identity(url) == posting_identity(target) and row['status'] == 'succeeded':
            return saved
    return None


def paid_retrieve(raw, history):
    """Reuse ledger evidence without its short maintenance TTL before any call."""
    from sources.firecrawl import FirecrawlClient
    from sources.http import _validate_public_url
    _validate_public_url(raw.url)
    data = saved_transport(history, raw.url)
    if data is None:
        with history.connect() as con:
            unresolved = con.execute("""SELECT r.id FROM requests r LEFT JOIN request_targets t ON t.request_id=r.id
                WHERE r.endpoint='scrape' AND r.status IN ('reserved','unknown','failed')
                  AND (t.url=? OR t.request_id IS NULL) LIMIT 1""", (canonicalize_url(raw.url),)).fetchone()
        if unresolved:
            raise RuntimeError('Unresolved prior billing for posting or legacy request without target; manual evidence review required')
        data = FirecrawlClient(history=history).call('scrape', {
            'url': canonicalize_url(raw.url), 'formats': ['rawHtml', 'markdown'],
            'onlyMainContent': False, 'maxAge': 86400000, 'proxy': 'basic',
            'timeout': 20000, 'waitFor': 3000, 'parsers': []})
    # Persist the transport response BEFORE parsing, including incomplete pages.
    return data


class Engine:
    def __init__(self, history, store, preferences, *, review=None, free=None, paid=None,
                 publish=None, now=None, progress=None, max_new_candidates=0, source_limits=None):
        self.history, self.store, self.preferences = history, store, preferences
        from resume_match import check, settings, MASTER, POLICY, WEIGHTS
        from codex_runner import MODEL, EFFORT
        self.review = review or check
        self.free = free or free_retrieve
        self.paid = paid or paid_retrieve
        self.publish = publish
        self.now = now or datetime.now(timezone.utc)
        self.progress = progress or (lambda report: None)
        self.max_new_candidates = max_new_candidates
        self.new_attempts = 0
        self.source_limits = source_limits or {}
        self.source_attempts = {}
        self.policy = digest([preferences, settings(), POLICY, WEIGHTS, MODEL, EFFORT,
                              hashlib.sha256(MASTER.read_bytes()).hexdigest() if MASTER.exists() else 'missing'])
        self.report = dict(candidates_discovered=0, known_jobs_skipped_before_retrieval=0,
                           new_jobs_added=0, free_retrievals=0, paid_requests=0,
                           paid_requests_avoided=0, pending=0, new_job_ids=[],
                           published_job_ids=[], warnings=[], status='running')
        with history.connect() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS daily_candidates (
                  key TEXT PRIMARY KEY, state TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
                  raw_json TEXT NOT NULL, fingerprint TEXT NOT NULL, policy TEXT NOT NULL DEFAULT '',
                  first_at TEXT NOT NULL, last_at TEXT NOT NULL, retry_at TEXT,
                  paid_state TEXT NOT NULL DEFAULT '', response_json TEXT, content_json TEXT,
                  review_json TEXT, job_json TEXT, gecko_id INTEGER, published INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS daily_aliases (alias TEXT PRIMARY KEY, candidate TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS daily_events (
                  id INTEGER PRIMARY KEY, candidate TEXT, at TEXT, state TEXT, reason TEXT);
            ''')
            if 'retry_mode' not in {r[1] for r in con.execute('PRAGMA table_info(daily_candidates)')}:
                con.execute("ALTER TABLE daily_candidates ADD COLUMN retry_mode TEXT NOT NULL DEFAULT 'auto'")

    def update(self, key, **values):
        with self.history.connect() as con:
            con.execute('UPDATE daily_candidates SET ' + ','.join(k+'=?' for k in values) + ' WHERE key=?', [*values.values(), key])
            if 'state' in values or 'reason' in values:
                con.execute('INSERT INTO daily_events(candidate,at,state,reason) VALUES(?,?,?,?)',
                            (key, self.now.isoformat(), values.get('state'), values.get('reason')))

    def seed(self, tracker, rejections):
        """Only actual retained postings/rejections seed terminal identities."""
        known = {}
        for job in self.store.all():
            for alias in aliases(job):
                known[alias] = ('accepted', job.id)
        # Archived/manual workspace rows remain known even without a visible row.
        tables = {r[0] for r in self.store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('workspace_records', 'workspace_archive', 'google_tracker_rows', 'workspace_manual_jobs'):
            if table not in tables:
                continue
            for record in self.store.connection.execute('SELECT * FROM ' + table):
                for value in record:
                    if not isinstance(value, str) or not value.startswith('{'):
                        continue
                    try:
                        saved = json.loads(value)
                    except ValueError:
                        continue
                    url = saved.get('Job URL') if isinstance(saved, dict) else None
                    if url:
                        known['url:' + repr(posting_identity(url))] = ('accepted', None)
        for _, row in tracker.scout().rows:
            url = row.get('Job URL')
            key = row.get('Scout ID', row.get('ID'))
            if key and str(key).isdigit():
                self.store.observe_scout_id(int(key))
            if url:
                known['url:' + repr(posting_identity(url))] = ('accepted', int(key) if str(key).isdigit() else None)
                from firecrawl_discovery import identity
                known['ats:' + identity(url)] = ('accepted', int(key) if str(key).isdigit() else None)
        for rejected in rejections.records:
            if rejected.source and rejected.job_id:
                known['source:' + rejected.source + ':' + rejected.job_id] = ('rejected', None)
            for url in (rejected.original_url, rejected.normalized_url):
                if url:
                    known['url:' + repr(posting_identity(url))] = ('rejected', None)
        # Retain legacy verified identities even after a visible row was removed.
        with self.history.connect() as con:
            retained = con.execute("SELECT original_url,redirects_json FROM candidates WHERE verification_status IN ('validated','synced','duplicate')").fetchall()
        for row in retained:
            for url in [row['original_url'], *json.loads(row['redirects_json'] or '[]')]:
                if url:
                    known.setdefault('url:' + repr(posting_identity(url)), ('accepted', None))
        return known

    def ingest(self, listings, known, rejections):
        listings=list(listings)
        from hard_filters import deterministic_filter
        def source_rank(raw):
            try:
                job=normalize(raw)
                return (deterministic_filter(job,self.preferences)[0],bool(re.search(r'\b(?:United States|USA|US|Utah)\b',job.location)))
            except (ValueError,TypeError):return (False,False)
        # Fuller eligible variants win within a verified requisition group.
        # No retrieval or inference occurs while selecting source evidence.
        listings.sort(key=source_rank)
        known=dict(known)
        # A retained public posting establishes the employer's internal
        # requisition alias for all variants in this free feed, regardless of
        # feed order. Titles and employer names never establish this alias.
        for raw in listings:
            try:candidate_names=aliases(normalize(raw))
            except (ValueError,TypeError):continue
            retained=next((known[n] for n in candidate_names if n in known),None)
            if retained:
                reqs={n for n in candidate_names if n.startswith('requisition:')}
                incompatible=False
                if reqs:
                    with self.history.connect() as con:
                        for name in candidate_names-reqs:
                            prior=con.execute('SELECT c.raw_json FROM daily_aliases a JOIN daily_candidates c ON c.key=a.candidate WHERE a.alias=?',(name,)).fetchone()
                            if prior:
                                old_reqs={n for n in aliases(normalize(RawListing(**json.loads(prior[0])))) if n.startswith('requisition:')}
                                if old_reqs and not old_reqs&reqs:incompatible=True;break
                if incompatible:continue
                for name in candidate_names:
                    if name.startswith('requisition:'):known[name]=retained
        keys = set()
        # One transaction admits all sources before retrieval. A later, fuller
        # alias can replace a snippet before any paid operation begins.
        with self.history.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            for raw in listings:
                self.report['candidates_discovered'] += 1
                try:
                    job = normalize(raw)
                except (ValueError, TypeError) as exc:
                    self.report['warnings'].append('Malformed source candidate: ' + safe_error(exc))
                    continue
                names = aliases(job)
                if not names:
                    continue
                source_names = {n for n in names if n.startswith(('source:','requisition:'))}
                req_names={n for n in names if n.startswith('requisition:')}
                req_owners={r[0] for name in req_names for r in con.execute('SELECT candidate FROM daily_aliases WHERE alias=?',(name,))}
                source_owners = req_owners or {r[0] for name in source_names for r in con.execute('SELECT candidate FROM daily_aliases WHERE alias=?', (name,))}
                owners = source_owners or {r[0] for name in names for r in con.execute('SELECT candidate FROM daily_aliases WHERE alias=?', (name,))}
                # A reused employer URL with a distinct stable source requisition
                # must not permanently hide the new requisition.
                verified_req=set()
                changed_req=False
                for owner in list(owners):
                    prior = con.execute('SELECT raw_json FROM daily_candidates WHERE key=?', (owner,)).fetchone()
                    old = RawListing(**json.loads(prior[0]))
                    old_names=aliases(normalize(old))
                    old_reqs={n for n in old_names if n.startswith('requisition:')}
                    verified_req=req_names & old_reqs
                    if req_names and old_reqs and not verified_req:
                        owners.remove(owner);names=req_names;changed_req=True;continue
                    if raw.source == old.source and raw.source_job_id and old.source_job_id and str(raw.source_job_id) != str(old.source_job_id) and not verified_req:
                        owners.remove(owner)
                        names = source_names
                if len(owners) > 1:
                    self.report['warnings'].append('Conflicting verified aliases need review: ' + raw.url)
                    continue
                key = next(iter(owners), digest(sorted(names)))
                row = con.execute('SELECT * FROM daily_candidates WHERE key=?', (key,)).fetchone()
                known_state = next((known[n] for n in names if n in known), None)
                if changed_req:known_state=None
                retained_req=any(n.startswith('requisition:') and known.get(n)==known_state for n in names)
                if known_state and known_state[1]:
                    prior = self.store.get(known_state[1])
                    if prior and prior.source == job.source and prior.source_job_id and job.source_job_id and prior.source_job_id != job.source_job_id and not retained_req:
                        known_state = None
                if known_state and known_state[0] == 'rejected' and not retained_req:
                    from rejected_jobs import normalize_job_url
                    if any(r.source == job.source and r.job_id and job.source_job_id
                           and r.job_id != job.source_job_id
                           and normalize_job_url(r.original_url or r.normalized_url) == normalize_job_url(job.url)
                           for r in rejections.records):
                        known_state = None
                if rejections.matches_job(job):
                    known_state = ('rejected', None)
                fp = digest([job.title, job.company, job.location, job.work_arrangement,
                             job.employment_type, job.salary, job.description])
                if row is None:
                    state, job_id = known_state or ('seen', None)
                    con.execute('''INSERT INTO daily_candidates
                      (key,state,raw_json,fingerprint,first_at,last_at,gecko_id,published,reason)
                      VALUES(?,?,?,?,?,?,?,?,?)''', (key, state, json.dumps(asdict(raw)), fp,
                        self.now.isoformat(), self.now.isoformat(), job_id, int(bool(known_state)),
                        'Retained tracker/history identity' if known_state else 'New source identity'))
                else:
                    con.execute('UPDATE daily_candidates SET last_at=? WHERE key=?', (self.now.isoformat(), key))
                    old = RawListing(**json.loads(row['raw_json']))
                    eligibility_changed=any(raw.metadata.get(name)!=old.metadata.get(name) for name in
                        ('applicantLocationRequirements','address','country','country_code','workplaceType','locations','secondaryLocations','isRemote','isListed','jobLocation'))
                    variant_evidence=(verified_req and raw.source_job_id!=old.source_job_id
                        and (row['state']=='seen' or (row['state']=='pending' and 'identity reconciliation' in row['reason'])))
                    if complete(raw) and (not complete(old) or fp != row['fingerprint'] or variant_evidence or eligibility_changed):
                        con.execute("UPDATE daily_candidates SET raw_json=?,fingerprint=?,retry_at=NULL,retry_mode='auto',content_json=NULL,review_json=NULL WHERE key=?",
                                    (json.dumps(asdict(raw)), fp, key))
                        if (verified_req and raw.source_job_id!=old.source_job_id and not known_state
                                and row['state']=='rejected' and row['policy']
                                and row['reason'] in ('non-remote role outside preferred locations','remote role restricted outside United States')
                                and deterministic_filter(job,self.preferences)[0]):
                            con.execute("UPDATE daily_candidates SET state='seen',policy='',reason='New verified requisition variant supplies changed eligibility evidence' WHERE key=?",(key,))
                    elif (row['state'] in ('seen','pending','expired') and (fp != row['fingerprint'] or eligibility_changed)
                          and raw.source == old.source and str(raw.source_job_id) == str(old.source_job_id)
                          and not complete(old)):
                        # Missing-title/location/snippet candidates can improve in
                        # a later free feed without becoming a new paid identity.
                        con.execute("UPDATE daily_candidates SET raw_json=?,fingerprint=?,retry_at=NULL,retry_mode='auto' WHERE key=?",
                                    (json.dumps(asdict(raw)), fp, key))
                    if known_state and not row['job_json']:
                        con.execute('UPDATE daily_candidates SET state=?,published=1,gecko_id=? WHERE key=?', (*known_state, key))
                for name in names:
                    con.execute('INSERT OR IGNORE INTO daily_aliases VALUES(?,?)', (name, key))
                keys.add(key)
        return keys

    def process(self, key, rejections):
        with self.history.connect() as con:
            row = con.execute('SELECT * FROM daily_candidates WHERE key=?', (key,)).fetchone()
        raw = RawListing(**json.loads(row['raw_json']))
        job = normalize(raw, discovered=self.now.astimezone(ZONE).date().isoformat())
        terminal = row['state'] in ('accepted', 'rejected', 'expired', 'duplicate')
        # Reevaluate a match/filter rejection only when policy changes. Permanent
        # tracker rejections and completed jobs never reopen from policy changes.
        recheck = (row['state'] == 'rejected' and row['policy'] and row['policy'] != self.policy)
        if terminal and not recheck and not (row['job_json'] and not row['published']):
            self.report['known_jobs_skipped_before_retrieval'] += 1
            self.report['paid_requests_avoided'] += 1
            return
        from link_validation import EXPIRED
        from location_evidence import source_location_blocker,location_blocker
        source_blocker=source_location_blocker(raw)
        if source_blocker:return self.pending(key,source_blocker,retry=False)
        if raw.metadata.get('isListed') is False or EXPIRED.search(raw.description[:3000]):
            self.update(key, state='expired', reason='Source explicitly reports posting closed')
            return
        if not recheck and (row['retry_mode']=='manual' or (row['retry_at'] and row['retry_at'] > self.now.isoformat())):
            self.report['known_jobs_skipped_before_retrieval'] += 1
            self.report['paid_requests_avoided'] += 1
            return
        if not raw.url or not raw.title or not raw.company:
            return self.pending(key, 'Source identity/title/company incomplete; retrieval needs source evidence')
        from hard_filters import deterministic_filter
        from source_policy import is_jooble_candidate
        allowed, reason = deterministic_filter(job, self.preferences)
        if rejections.matches_job(job) or is_jooble_candidate(source=raw.source, urls=(raw.url,), metadata=raw.metadata):
            self.update(key, state='rejected', reason='Permanent rejection or disabled provenance', policy='')
            return
        if not allowed:
            self.update(key, state='rejected', reason=reason, policy=self.policy)
            self.report['paid_requests_avoided'] += 1
            return
        if row['job_json']:
            return self.save_and_publish(key, JobListing.from_dict(json.loads(row['job_json'])), row['gecko_id'])
        limit = self.source_limits.get(raw.source, 0)
        if limit and self.source_attempts.get(raw.source, 0) >= limit:
            self.report['paid_requests_avoided'] += 1
            return self.pending(key, 'Configured source admission limit; retained for next run', retry=False,deferred=True)
        if self.max_new_candidates and self.new_attempts >= self.max_new_candidates:
            self.report['paid_requests_avoided'] += 1
            return self.pending(key, 'Controlled run admission limit; retained for next incremental run', retry=False,deferred=True)
        self.new_attempts += 1
        self.source_attempts[raw.source] = self.source_attempts.get(raw.source, 0) + 1
        content = json.loads(row['content_json']) if row['content_json'] else None
        if not content and complete(raw):
            from dataclasses import replace
            from job_extraction import extract, markdown
            source = replace(raw, metadata={**raw.metadata, 'description': raw.description})
            document = extract({'markdown': markdown(raw.description)}, source, '')
            document['fields']['discovery_source'] = 'Gecko / ' + raw.source
            if document['status'] != 'complete':
                return self.pending(key, '; '.join(document['issues']))
            content = {'description': document['full_description_markdown'], 'url': raw.url, 'document': document}
            self.report['paid_requests_avoided'] += 1
        if not content and not row['response_json'] and not row['paid_state']:
            saved = saved_transport(self.history, raw.url)
            if saved:
                self.update(key, response_json=json.dumps(saved), paid_state='response_saved')
                self.report['paid_requests_avoided'] += 1
                with self.history.connect() as con:
                    row = con.execute('SELECT * FROM daily_candidates WHERE key=?', (key,)).fetchone()
        if not content and row['paid_state'] == 'dispatched' and not complete(raw):
            # Crash after provider response was settled but before candidate
            # checkpoint: recover saved transport evidence without calling client.
            with self.history.connect() as con:
                saved = con.execute("""SELECT r.response_json FROM requests r JOIN request_targets t ON t.request_id=r.id
                    WHERE t.url=? AND r.status='succeeded' AND r.response_json IS NOT NULL
                    ORDER BY r.started_at DESC LIMIT 1""", (canonicalize_url(raw.url),)).fetchone()
            if saved:
                data = json.loads(saved[0]).get('data') or {}
                self.update(key, response_json=json.dumps(data), paid_state='response_saved')
                # Refresh the checkpoint so the normal parser below sees it.
                with self.history.connect() as con:
                    row = con.execute('SELECT * FROM daily_candidates WHERE key=?', (key,)).fetchone()
            else:
                self.report['paid_requests_avoided'] += 1
                return self.pending(key, 'Prior dispatch unresolved; explicit billing review required', retry=False)
        if not content and not row['response_json']:
            self.report['free_retrievals'] += 1
            try:
                content = self.free(raw)
            except Exception as exc:
                return self.pending(key, 'Free retrieval failed: ' + safe_error(exc))
            if content and description_is_sufficient(content.get('description', '')):
                self.report['paid_requests_avoided'] += 1
            else:
                content = None
        if not content:
            if row['response_json']:
                data = json.loads(row['response_json'])
            elif row['paid_state']:
                self.report['paid_requests_avoided'] += 1
                return self.pending(key, 'Prior paid attempt retained; explicit billing/content review required', retry=False)
            else:
                with self.history.connect() as con:
                    day = self.now.astimezone(ZONE).date().isoformat()
                    scrapes = con.execute("SELECT COUNT(*) FROM requests WHERE day=? AND endpoint='scrape'", (day,)).fetchone()[0]
                limit = self.history.settings['max_scrapes_per_day']
                if not raw.date_posted:
                    limit = min(limit, self.history.settings['max_unknown_date_verifications_per_day'])
                if not self.history.settings['daily_enabled'] or scrapes >= limit:
                    return self.pending(key, 'Daily paid retrieval disabled or configured extraction limit reached')
                self.update(key, state='pending', paid_state='dispatched', reason='Paid dispatch checkpoint; never auto-repeat')
                try:
                    before = self.request_count()
                    data = self.paid(raw, self.history)
                    self.report['paid_requests'] += self.request_count() - before
                    self.update(key, response_json=json.dumps(data), paid_state='response_saved')
                except Exception as exc:
                    requests = self.request_count() - before
                    self.report['paid_requests'] += requests
                    if not requests and re.search(r'budget|balance|disabled|requires FIRECRAWL_API_KEY', str(exc), re.I):
                        self.update(key, paid_state='')
                        return self.pending(key, 'No paid request sent: ' + safe_error(exc))
                    return self.pending(key, 'Paid attempt unresolved: ' + safe_error(exc), retry=False)
            from firecrawl_discovery import extract_listing
            try:
                extracted, evidence, final = extract_listing(data, raw.url)
                content = exact_result(raw, data, extracted, evidence, final)
            except Exception as exc:
                return self.pending(key, 'Exact posting review: ' + safe_error(exc), retry=False)
        if not content or not description_is_sufficient(content.get('description', '')):
            return self.pending(key, 'Incomplete description; no snippet scoring', retry=not row['paid_state'])
        self.update(key, content_json=json.dumps(content))
        if content.get('raw'):
            detailed = normalize(RawListing(**content['raw']))
            job.location = detailed.location or job.location
            job.work_arrangement = detailed.work_arrangement if detailed.work_arrangement != 'unknown' else job.work_arrangement
            job.salary = detailed.salary or job.salary
            job.employment_type = detailed.employment_type or job.employment_type
        job.description = content['description']
        if content.get('url'):
            job.authoritative_url = content['url']
            job.url_verification_status = 'verified'
        job.details = content.get('document') or {}
        location_issue=location_blocker(job)
        if location_issue:return self.pending(key,location_issue,retry=False)
        # A successful exact retrieval can verify a redirect alias. Resolve it
        # against retained/current candidates before inference or publication.
        names = aliases(job)
        with self.history.connect() as con:
            owners = {r[0] for name in names for r in con.execute('SELECT candidate FROM daily_aliases WHERE alias=?', (name,))} - {key}
            if owners and not all(n.startswith('source:') for n in names):
                self.update(key, state='pending', reason='Verified redirect joins another candidate; identity reconciliation required', retry_at=(self.now + timedelta(days=RETRY_DAYS)).isoformat())
                return
            con.executemany('INSERT OR IGNORE INTO daily_aliases VALUES(?,?)', [(name, key) for name in names])
        from google_tracker import resume_approval_value
        allowed, reason = deterministic_filter(job, self.preferences)
        fee = job.details.get('fields', {}).get('application_fee_required') is True
        if not allowed or fee:
            self.update(key, state='rejected', reason='Mandatory application fee' if fee else reason, policy=self.policy)
            return
        if resume_approval_value(job.location, job.work_arrangement, '') != 'Yes':
            return self.pending(key, 'Location/remote eligibility unknown or unsupported')
        review = self.review(job)  # Existing evidence cache recalculates thresholds.
        self.update(key, review_json=json.dumps(review), policy=self.policy)
        if not review['accepted']:
            if review['status'] == 'pending':
                return self.pending(key, review.get('reason', 'Match review pending'))
            self.update(key, state='rejected', reason=review.get('reason', 'Below match policy'))
            return
        # Reserve the stable ID before crossing into the jobs database.
        job_id = row['gecko_id'] or self.store.highest_scout_id() + 1
        self.store.observe_scout_id(job_id)
        job.id = job_id
        self.update(key, state='accepted', reason='Match accepted; publication pending', gecko_id=job_id, job_json=json.dumps(job.to_dict()), retry_at=None)
        self.save_and_publish(key, job, job_id)

    def request_count(self):
        with self.history.connect() as con:
            return con.execute('SELECT COUNT(*) FROM requests').fetchone()[0]

    def pending(self, key, reason, retry=True,deferred=False):
        self.update(key, state='pending', reason=reason,
                    retry_mode='auto' if deferred else ('cooldown' if retry else 'manual'),
                    retry_at=(self.now + timedelta(days=RETRY_DAYS)).isoformat() if retry else None)

    def save_and_publish(self, key, job, job_id):
        existing = self.store.get(job_id)
        if existing is None:
            self.store.save(job, job_id=job_id)
        elif not (aliases(existing) & aliases(job)):
            raise RuntimeError('Reserved Gecko ID belongs to a different posting')
        if job.details:
            self.store.save_job_document(job_id, job.details)
        if job_id not in self.report['new_job_ids']:
            self.report['new_job_ids'].append(job_id)
        self.report['new_local_jobs_saved'] = len(self.report['new_job_ids'])
        try:
            if self.publish is None:
                raise RuntimeError('Canonical publisher unavailable')
            self.publish(job)
            self.update(key, state='accepted', published=1, reason='Canonical tracker independently verified')
            self.report['published_job_ids'].append(job_id)
            self.report['new_jobs_added'] = len(self.report['published_job_ids'])
        except Exception as exc:
            self.report['warnings'].append('Publication pending for ' + str(job_id) + ': ' + safe_error(exc))

    def run(self, listings, *, tracker, rejections, publish_only=False, retry_candidates=()):
        # Shared with legacy broad discovery; no lease expiry can launch a second
        # worker while the first is still running.
        with self.history.lock():
            for key in retry_candidates:
                with self.history.connect() as con:
                    found = con.execute('SELECT state FROM daily_candidates WHERE key=?', (key,)).fetchone()
                if not found or found['state'] in ('accepted','duplicate'):
                    raise ValueError('Retry requires an existing pending, expired or reviewed candidate key')
                self.update(key, state='pending', retry_mode='auto',retry_at=None, reason='Explicit retry requested; paid dispatch remains protected')
            known = self.seed(tracker, rejections)
            keys = self.ingest(listings, known, rejections) if not publish_only else set()
            # Recover interrupted/publication work even if absent from today's feed.
            with self.history.connect() as con:
                if publish_only:
                    keys.update(r[0] for r in con.execute('SELECT key FROM daily_candidates WHERE job_json IS NOT NULL AND published=0'))
                else:
                    keys.update(r[0] for r in con.execute("SELECT key FROM daily_candidates WHERE state IN ('seen','pending') OR (job_json IS NOT NULL AND published=0) OR (state='rejected' AND policy<>'' AND policy<>?)", (self.policy,)))
            for key in sorted(keys):
                try:
                    self.process(key, rejections)
                except Exception as exc:
                    self.pending(key, 'Processing failed: ' + safe_error(exc))
                    self.report['warnings'].append(safe_error(exc))
                self.progress(self.report)
            with self.history.connect() as con:
                self.report['pending'] = con.execute("SELECT COUNT(*) FROM daily_candidates WHERE state='pending' OR (job_json IS NOT NULL AND published=0)").fetchone()[0]
            self.report['status'] = 'complete'
            self.progress(self.report)
        return self.report


def publish_verified(tracker, job):
    """Canonical managed writer followed by a separate primary-tracker read."""
    from job_extraction import tracker_notes
    from sheet_sync import ensure_frozen_headers
    from query_provenance import query_for_job
    expected = query_for_job(job)
    if expected and 'Query Used to Find' not in tracker.scout().headers:
        raise RuntimeError('Primary tracker is missing Query Used to Find; no publication attempted')
    result = tracker.upsert_scout([job], append_only=True, fill_blanks_only=True,
        discovery_notes={job.id: tracker_notes(job.details) + '\nGecko incremental discovery ' + datetime.now(ZONE).isoformat()})
    if not result.get('readback_verified') or result.get('skipped') or result.get('match_excluded'):
        raise RuntimeError('Canonical writer did not verify acceptance/write')
    rows = [v for _,v in tracker.scout().rows if str(v.get('Scout ID', v.get('ID'))) == str(job.id)]
    if len(rows) != 1 or 'url:' + repr(posting_identity(rows[0].get('Job URL', ''))) not in aliases(job):
        raise RuntimeError('Independent tracker ID/URL readback failed')
    if str(rows[0].get('Apply?',rows[0].get('Qualifies to Apply?',''))).strip().casefold()!='yes':
        raise RuntimeError('Primary tracker does not confirm qualification; publication remains pending')
    if expected and rows[0].get('Query Used to Find') != expected:
        raise RuntimeError('Discovery query readback differs')
    ensure_frozen_headers(tracker)


def run(args, store, preferences):
    """Canonical CLI/daily adapter. Caller owns the outer daily run lock."""
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    from sources.acquisition import acquire
    from sources.base import SearchRequest
    from google_tracker import GoogleTracker, Config
    from sources.config import load_source_config
    import scout
    sys.path.append(str(ROOT / 'scripts'))
    from run_gecko import run_lock
    if getattr(args, 'max_new_candidates', 0) < 0:
        raise ValueError('--max-new-candidates must be nonnegative')
    with (nullcontext() if getattr(args, 'daily_mode', False) else run_lock()):
        tracker = GoogleTracker(config=Config.from_environment())
        # Fail closed before retrieval if live identity/rejection reads fail.
        tracker.scout()
        rejections = tracker.rejected_jobs_index()
        history = History()
        run_id = 'incremental-' + datetime.now(ZONE).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8]
        path = ROOT / 'reports/discovery/incremental' / (run_id + '.json')
        counts, health = {}, {}
        before = history.usage()
        last_progress = [0.0]
        def progress(report):
            if report['status'] == 'running' and time.monotonic() - last_progress[0] < 1:
                return
            last_progress[0] = time.monotonic()
            with history.connect() as con:
                report['pending'] = con.execute("SELECT COUNT(*) FROM daily_candidates WHERE state='pending' OR (job_json IS NOT NULL AND published=0)").fetchone()[0]
            value = {**report, 'run_id': run_id, 'mode': 'incremental',
                     'source_counts': counts, 'source_health': health,
                     'resumes_generated': 0, 'applications_submitted': 0,
                     'checked_at': datetime.now(timezone.utc).isoformat(),
                     'activity': f"Incremental discovery: {report['candidates_discovered']} candidates; {len(report['published_job_ids'])} new jobs verified",
                     'published_jobs_verified': len(report['published_job_ids'])}
            for target in (path, ROOT / 'reports/discovery/live-status.json'):
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_suffix('.' + uuid4().hex + '.tmp')
                temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
                temp.replace(target)
        def publish(job):
            publish_verified(tracker, job)
        engine = Engine(history, store, preferences, publish=publish, progress=progress,
                        max_new_candidates=getattr(args, 'max_new_candidates', 0))
        progress(engine.report)
        available = scout.providers(getattr(args, 'sources_config', None))
        source_settings = load_source_config(getattr(args, 'sources_config', None))
        engine.source_limits = {name:int(source_settings['providers'].get(name, {}).get('max_results_per_run',
                                     source_settings.get('max_results_per_source', 0))) for name in FREE_SOURCES}
        requested = getattr(args, 'source', 'all')
        selected = list(FREE_SOURCES) if requested in ('all', 'core') else [requested]
        if getattr(args, 'sync_only', False):
            selected = []
        unknown = set(selected) - set(FREE_SOURCES)
        if unknown:
            raise ValueError('Source requires explicit --broad-discovery: ' + ', '.join(sorted(unknown)))
        engine.report['deferred_broad_sources'] = sorted(set(available) - set(FREE_SOURCES))
        for name in selected:
            if name not in available or not available[name].configured():
                health[name] = {'status':'not configured', 'found':0}
        requests = [SearchRequest(q, loc, 1, getattr(args, 'results', 20))
                    for q in (getattr(args, 'query', None) or preferences['target_roles'])
                    for loc in (getattr(args, 'location', None) or preferences.get('preferred_locations') or ['Utah','Remote'])]
        listings = []
        # Acquire all free identities before ANY detail/AI/paid work.
        with ThreadPoolExecutor(max_workers=source_settings['max_workers']) as pool:
            futures = {pool.submit(acquire, available[name], requests): name
                       for name in selected if name in available and available[name].configured()}
            remaining = set(futures)
            while remaining:
                done, remaining = wait(remaining, timeout=1, return_when=FIRST_COMPLETED)
                for future in done:
                    name = futures[future]
                    try:
                        rows, errors = future.result()
                        limit = int(source_settings['providers'].get(name, {}).get('max_results_per_run',
                                    source_settings.get('max_results_per_source', 0)))
                        if name == 'greenhouse':
                            for raw in rows:
                                raw.date_posted = str(raw.metadata.get('first_published') or '')
                        counts[name] = len(rows)
                        health[name] = {'status': 'partial failure' if errors else 'success', 'found': len(rows), 'errors': errors,
                                        'candidate_admission_limit':limit}
                        listings.extend(rows)
                    except Exception as exc:
                        health[name] = {'status': 'failed', 'found': 0, 'error': safe_error(exc)}
                engine.report['candidates_discovered'] = len(listings)
                progress(engine.report)
        engine.report['candidates_discovered'] = 0
        try:
            result = engine.run(listings, tracker=tracker, rejections=rejections, publish_only=getattr(args, 'sync_only', False),
                                retry_candidates=getattr(args, 'retry_candidate', ()))
        except BaseException as exc:
            engine.report.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed')
            engine.report['warnings'].append(safe_error(exc))
            progress(engine.report)
            raise
        after = history.usage()
        result['firecrawl'] = {k: after[k] - before[k] for k in
            ('provider_confirmed_credits', 'estimated_or_reserved_credits', 'total_credits_accounted')}
        result['firecrawl']['usage_scope'] = 'ledger delta during controlled run; account-wide usage is not attributed'
        result['firecrawl']['ledger_usage_after'] = after
        result['firecrawl']['new_qualified'] = len(result['published_job_ids'])
        result['firecrawl']['day'] = datetime.now(ZONE).date().isoformat()
        result.update(fetched=result['candidates_discovered'], newly_discovered=result['new_jobs_added'],
                      existing_job_ids=[], changed_job_ids=[], sources_searched=len(health), source_health=health,
                      source_errors={n:h for n,h in health.items() if h['status'] != 'success'})
        if not getattr(args, 'sync_only', False) and not any(h.get('found') or h['status'] == 'success' for h in health.values()):
            result['status'] = 'failed'
        progress(result)
        args.run_result = result
        args.tracker_summary = {'added': len(result['published_job_ids']), 'updated': 0}
        print('Incremental discovery: ' + json.dumps(result), flush=True)
        return 0 if result['status'] == 'complete' else 1
