"""Manual intake: one atomic canonical job and tracker record, never an application submission."""
import hashlib
import json
import os
from datetime import date
from urllib.parse import urlsplit
from normalize import canonicalize_url, posting_identity

FIELDS = ['Company', 'Job Title', 'Source', 'Location', 'Salary', 'Work Arrangement', 'Employment Type', 'Personal priority', 'Notes', 'Date Posted']

def validate_url(value):
    value = str(value or '').strip()
    p = urlsplit(value)
    if len(value)>4000 or p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ValueError('Enter a public HTTPS job posting link without login credentials.')
    from sources.http import _validate_public_url
    _validate_public_url(value)
    return value

def manual_ids(tracker):
    with tracker.connection() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_manual_jobs'").fetchone():
            return []
        return [str(r[0]) for r in con.execute('SELECT job_id FROM workspace_manual_jobs')]

def save(tracker, payload, stamp):
    if getattr(tracker, 'backend', '') != 'sqlite' or os.environ.get('GECKO_ALLOWED_JOB_IDS'):
        raise ValueError('Manual intake requires an unrestricted SQLite workspace.')
    url = validate_url(payload.get('url'))
    fields = {k: str(payload.get(k) or '').strip() for k in FIELDS}
    if any(len(v)>30000 for v in fields.values()) or not fields['Company'] or not fields['Job Title']:
        raise ValueError('Company and job title are required; keep each field under 30,000 characters.')
    applied = payload.get('applied') is True
    applied_date = str(payload.get('applied_date') or '')
    if applied and (date.fromisoformat(applied_date)>date.fromisoformat(stamp[:10])):
        raise ValueError('The application date cannot be in the future.')
    identity = posting_identity(url)
    canonical = canonicalize_url(url)
    with tracker.connection() as con, con:
        con.execute('BEGIN IMMEDIATE')
        for row in con.execute("SELECT dataset,archived,values_json FROM workspace_records WHERE dataset IN ('Job List','Rejected Jobs','Deleted Jobs')"):
            data = json.loads(row['values_json'])
            other = data.get('Job URL') or data.get('Original Job URL')
            if other and posting_identity(other)==identity:
                raise ValueError('This posting is already saved (job ID '+str(data.get('ID') or data.get('Job ID') or '')+'). Open its existing record to update it; no duplicate was created.')
        for row in con.execute('SELECT id,url FROM jobs'):
            if row['url'] and posting_identity(row['url'])==identity:
                raise ValueError('This posting already exists as job ID '+str(row['id'])+'. Review that record before adding it again.')
        top = con.execute("SELECT MAX(CAST(json_extract(values_json,'$.ID') AS INTEGER)) FROM workspace_records WHERE dataset='Job List'").fetchone()[0] or 0
        high = con.execute("SELECT value FROM scout_state WHERE key='id_high_water'").fetchone()
        job_id = max(top, con.execute('SELECT COALESCE(MAX(id),0) FROM jobs').fetchone()[0], int(high[0]) if high else 0)+1
        source = fields['Source'] or urlsplit(url).hostname
        fields.update({'ID':job_id,'Source':source,'Job URL':url,'Date Found':stamp[:10], 'Applied':'X' if applied else '', 'Applied Date':applied_date if applied else ''})
        if applied:
            fields['Notes'] += '\n[Gecko dashboard] '+json.dumps({'action':'applied','at':stamp,'stage':'Applied','applied_at':applied_date})
        con.execute('INSERT INTO jobs(id,company,title,location,work_arrangement,employment_type,salary,source,source_job_id,url,canonical_url,date_posted,date_discovered,last_seen,description) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (job_id,fields['Company'],fields['Job Title'],fields['Location'],fields['Work Arrangement'],fields['Employment Type'],fields['Salary'],source,'manual-'+hashlib.sha256(canonical.encode()).hexdigest(),url,canonical,fields['Date Posted'],stamp,stamp,str(payload.get('description') or '')[:30000]))
        slot = con.execute("SELECT COALESCE(MAX(slot),1)+1 FROM workspace_records WHERE dataset='Job List'").fetchone()[0]
        raw = json.dumps(fields)
        con.execute("INSERT INTO workspace_records(dataset,slot,values_json) VALUES('Job List',?,?)",(slot,raw))
        con.execute("INSERT INTO scout_state(key,value) VALUES('id_high_water',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(job_id,))
        con.execute('CREATE TABLE IF NOT EXISTS workspace_manual_jobs(job_id INTEGER PRIMARY KEY REFERENCES jobs(id),added_at TEXT NOT NULL)')
        con.execute('INSERT INTO workspace_manual_jobs VALUES(?,?)',(job_id,stamp))
        con.execute("INSERT INTO workspace_events(at,dataset,slot,action,after_json) VALUES(?,'Job List',?,'manual-intake',?)",(stamp,slot,raw))
        assert json.loads(con.execute("SELECT values_json FROM workspace_records WHERE dataset='Job List' AND slot=?",(slot,)).fetchone()[0])==fields
    return {'id':str(job_id),'applied':applied}
