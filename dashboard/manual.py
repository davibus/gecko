"""Manual intake: one atomic canonical job and tracker record, never an application submission."""
import hashlib
import json
import os
import re
from pathlib import Path
from datetime import date
from urllib.parse import urlsplit
from normalize import canonicalize_url, posting_identity
from tracker_schema import resolve_headers

FIELDS = ['Company', 'Job Title', 'Source', 'Location', 'Salary', 'Work Arrangement', 'Employment Type', 'Personal priority', 'Notes', 'Date Posted']


def publish_upload_copy(source, fields, job_id, root):
    """Keep the canonical validated resume intact and publish an upload copy."""
    source = Path(source).resolve()
    if source.parent != (Path(root) / 'output/resumes').resolve() or source.suffix.lower() != '.docx' or not source.is_file():
        raise ValueError('A verified canonical resume is required before publishing an upload copy.')
    def safe(value):
        return re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', str(value)).strip(' .')
    if not str(job_id).isdigit():
        raise ValueError('A stable Gecko job ID is required.')
    company = safe(fields['Company'])[:45].rstrip(' .')
    title = safe(fields['Job Title'])[:65].rstrip(' .')
    filename = f'Dave Call - {company} - {title} - ID{job_id}.docx'
    folder = Path(root) / 'output/resumes/Manual Applications/Ready to Upload'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    content = source.read_bytes()
    if not content:
        raise ValueError('The validated resume is empty.')
    try:
        with target.open('xb') as output:
            output.write(content)
    except FileExistsError:
        if target.read_bytes() != content:
            raise ValueError('An upload copy already exists with different contents; it was preserved.')
    if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(content).digest():
        raise RuntimeError('Upload copy verification failed.')
    return target

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
    if payload.get('create_resume') is True:
        from description_retrieval import description_is_sufficient
        from google_tracker import resume_approval_value
        description = str(payload.get('description') or '').strip()
        if len(description) > 30000 or not description_is_sufficient(description):
            raise ValueError('Paste the complete job description (600–30,000 characters).')
        if applied or payload.get('resume_token'):
            raise ValueError('Create a resume for an unsubmitted job without an existing attachment.')
        if resume_approval_value(fields['Location'], fields['Work Arrangement'], '') != 'Yes':
            raise ValueError('Enter Utah eligibility or explicit remote work before creating the resume.')
        fields['Apply?'] = 'Yes'
    applied_date = str(payload.get('applied_date') or '')
    if applied and (date.fromisoformat(applied_date)>date.fromisoformat(stamp[:10])):
        raise ValueError('The application date cannot be in the future.')
    identity = posting_identity(url)
    canonical = canonicalize_url(url)
    attachment = None
    if payload.get('resume_token'):
        from dashboard import attachments
        attachment, _ = attachments.read(payload['resume_token'])
    if payload.get('id') is not None:
        return update(tracker, payload, stamp, url, fields, attachment)
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
        headers=json.loads(con.execute("SELECT headers_json FROM workspace_datasets WHERE name='Job List'").fetchone()[0])
        resolved=resolve_headers(headers)
        fields={headers[resolved[k]-1] if k in resolved else k:v for k,v in fields.items()}
        raw = json.dumps(fields)
        con.execute("INSERT INTO workspace_records(dataset,slot,values_json) VALUES('Job List',?,?)",(slot,raw))
        con.execute("INSERT INTO scout_state(key,value) VALUES('id_high_water',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(job_id,))
        con.execute('CREATE TABLE IF NOT EXISTS workspace_manual_jobs(job_id INTEGER PRIMARY KEY REFERENCES jobs(id),added_at TEXT NOT NULL)')
        con.execute('INSERT INTO workspace_manual_jobs VALUES(?,?)',(job_id,stamp))
        if attachment:
            con.execute('CREATE TABLE IF NOT EXISTS workspace_manual_resumes(job_id INTEGER PRIMARY KEY REFERENCES jobs(id),token TEXT NOT NULL UNIQUE,filename TEXT NOT NULL)')
            con.execute('INSERT INTO workspace_manual_resumes VALUES(?,?,?)',(job_id,attachment['token'],attachment['name']))
        con.execute("INSERT INTO workspace_events(at,dataset,slot,action,after_json) VALUES(?,'Job List',?,'manual-intake',?)",(stamp,slot,raw))
        assert json.loads(con.execute("SELECT values_json FROM workspace_records WHERE dataset='Job List' AND slot=?",(slot,)).fetchone()[0])==fields
    return {'id':str(job_id),'applied':applied}


def attachment_rebase(tracker, slot, payload, original, fields):
    """Recover the exact old form from audit history; merge only nonconflicting edits."""
    from dashboard import server as s
    from tracker_schema import resolve_headers
    with tracker.connection() as con:
        headers=json.loads(con.execute("SELECT headers_json FROM workspace_datasets WHERE name='Job List'").fetchone()[0])
        events=con.execute("SELECT before_json,after_json FROM workspace_events WHERE dataset='Job List' AND slot=? ORDER BY id DESC",(slot,)).fetchall()
        description=con.execute('SELECT description FROM jobs WHERE id=?',(str(original['Scout ID']),)).fetchone()
    base=None
    for event in events:
        for raw in event:
            if not raw:continue
            try:
                candidate=json.loads(raw)
                if not isinstance(candidate,dict):continue
                for alias,col in resolve_headers(headers).items():candidate[alias]=candidate.get(headers[col-1],'')
                if s.version(candidate)==payload.get('version'):
                    base=candidate;break
            except (ValueError,TypeError):continue
        if base is not None:break
    if base is None or base.get('Job URL')!=original.get('Job URL'):
        raise ValueError('This job changed. Your uploaded resume is kept; reopen the job before saving.')
    changes={}
    for key,value in fields.items():
        if key not in payload:continue
        before=str(base.get(key) or '')
        current=str(original.get(key) or '')
        if key=='Notes':before=s.notes_parts(before)[0];current=s.notes_parts(current)[0]
        if value==before.strip():continue
        if current!=before and value!=current.strip():
            raise ValueError(key+' was edited elsewhere. Your uploaded resume is kept; review that field before saving.')
        changes[key]=value
    if 'description' in payload and str(payload.get('description') or '')!=str(description[0] or '' if description else ''):
        raise ValueError('The job description needs review after a background change. Your uploaded resume is kept.')
    return changes


def update(tracker, payload, stamp, url, fields, attachment=None):
    """Edit a manual record atomically; retain its identity and managed state."""
    from dashboard import server as s
    from tracker_schema import resolve_headers
    from google_tracker import marked
    job_id=str(payload['id'])
    slot, original=s.find_job(tracker.scout(),job_id)
    current_version=s.version(original)
    stale=payload.get('version') != current_version
    if stale and not attachment:
        raise ValueError('This job changed. Refresh and reopen it before saving.')
    if posting_identity(url) != posting_identity(original['Job URL']):
        raise ValueError('Keep the original posting link when editing this job.')
    if stale:
        fields=attachment_rebase(tracker,slot,payload,original,fields)
    changes={k:v for k,v in fields.items() if k in payload and k!='Notes'}
    text,meta,history=s.notes_parts(original.get('Notes'))
    if 'Notes' in fields and 'Notes' in payload:
        text=fields['Notes']
        if s.PREFIX in text:
            raise ValueError('Notes must be plain text without reserved dashboard markers.')
    notes=text
    for event in history: notes=s.append_event(notes,event)
    event={'action':'manual-edit','at':stamp}
    applied=marked(original.get('Applied')) or payload.get('applied') is True
    if applied and not marked(original.get('Applied')):
        applied_date=str(payload.get('applied_date') or '')
        date.fromisoformat(applied_date)
        changes.update({'Applied':'X','Applied Date':applied_date})
        event.update(action='applied',stage='Applied',applied_at=applied_date)
    changes['Notes']=s.append_event(notes,event)
    if len(changes['Notes'])>48000:raise ValueError('Notes history is too long. Preserve it before adding more.')
    if str(original.get('Apply?','')).strip().lower()=='yes' and not s.eligible({**original,**changes}):
        changes['Apply?']='No'
    with tracker.connection() as con,con:
        con.execute('BEGIN IMMEDIATE')
        if not con.execute('SELECT 1 FROM workspace_manual_jobs WHERE job_id=?',(job_id,)).fetchone():
            raise ValueError('Only individually added jobs can be edited in this form.')
        stored=con.execute("SELECT * FROM workspace_records WHERE dataset='Job List' AND slot=? AND archived=0",(slot,)).fetchone()
        if not stored:raise ValueError('This job is no longer active.')
        raw=json.loads(stored['values_json'])
        headers=json.loads(con.execute("SELECT headers_json FROM workspace_datasets WHERE name='Job List'").fetchone()[0])
        normalized=dict(raw)
        for alias,col in resolve_headers(headers).items():normalized[alias]=raw.get(headers[col-1],'')
        if s.version(normalized)!=current_version:
            raise ValueError('This job changed before saving. Refresh and reopen it.')
        resolved=resolve_headers(headers)
        changes={headers[resolved[k]-1] if k in resolved else k:v for k,v in changes.items()}
        formulas=json.loads(stored['formulas_json'])
        if any(raw.get(k,'')!=v and str(formulas.get(k,'')).lstrip().startswith('=') for k,v in changes.items()):
            raise ValueError('A changed field is formula-protected. Nothing was saved.')
        after={**raw,**changes}
        con.execute("UPDATE workspace_records SET values_json=?,revision=revision+1 WHERE dataset='Job List' AND slot=?",(json.dumps(after),slot))
        columns={'Company':'company','Job Title':'title','Source':'source','Location':'location','Salary':'salary','Work Arrangement':'work_arrangement','Employment Type':'employment_type','Date Posted':'date_posted'}
        updates={columns[k]:v for k,v in changes.items() if k in columns}
        if 'description' in payload and not stale:updates['description']=str(payload['description'] or '')[:30000]
        if updates:
            con.execute('UPDATE jobs SET '+','.join(k+'=?' for k in updates)+' WHERE id=?',(*updates.values(),job_id))
        if attachment:
            con.execute('CREATE TABLE IF NOT EXISTS workspace_manual_resumes(job_id INTEGER PRIMARY KEY REFERENCES jobs(id),token TEXT NOT NULL UNIQUE,filename TEXT NOT NULL)')
            con.execute('INSERT INTO workspace_manual_resumes VALUES(?,?,?) ON CONFLICT(job_id) DO UPDATE SET token=excluded.token,filename=excluded.filename',(job_id,attachment['token'],attachment['name']))
        con.execute("INSERT INTO workspace_events(at,dataset,slot,action,before_json,after_json) VALUES(?,'Job List',?,'manual-edit',?,?)",(stamp,slot,stored['values_json'],json.dumps(after)))
    _,verified=s.find_job(tracker.scout(),job_id)
    if any(verified.get(k,'')!=v for k,v in changes.items()):
        raise RuntimeError('Saved job readback did not match. Check it before retrying.')
    return {'id':job_id,'applied':applied,'updated':True}
