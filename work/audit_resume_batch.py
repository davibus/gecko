"""Independent full-tracker completion and preservation readback."""
import sys,json,hashlib,re
from pathlib import Path
from urllib.parse import urlsplit,unquote
from datetime import datetime,timezone
ROOT=Path('C:/gecko_main');sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
from google_tracker import GoogleTracker,Config,load_environment,resume_already_created
from run_gecko import run_lock
from sheet_sync import ensure_frozen_headers
from generate_apply_queue import read_queue,_valid_resume_link
from manage_job_tracker import RESUME_FAILURE_PREFIX
import fitz
load_environment();OUT=ROOT/'reports/resume-batch-20261025'
with run_lock():
    remote=GoogleTracker(config=Config.from_environment());tab=remote.scout()
    current={int(v['Scout ID']):v for _,v in tab.rows if str(v.get('Scout ID','')).isdigit()}
    before=json.loads((OUT/'live-tracker-before.json').read_text(encoding='utf-8'))
    old={int(v['Scout ID']):v for _,v in before['rows'] if str(v.get('Scout ID','')).isdigit()}
    baseline=json.loads((OUT/'preflight.json').read_text(encoding='utf-8'))
    goals={j['id'] for group in ('score_qualified','unscored','below_threshold') for j in baseline[group]}
    completed=[];issues=[]
    for path in OUT.glob('completed-*.json'):
        receipt=json.loads(path.read_text(encoding='utf-8'));ident=receipt['id'];row=current[ident];docx=Path(receipt['resume'])
        assert row['Company']==receipt['company'] and row['Job Title']==receipt['title'],('identity',ident)
        assert resume_already_created(row['Resume Created']) and row['Resume Link']==docx.resolve().as_uri(),('marker/link',ident)
        assert row['Resume Created Date']==receipt['readback']['Resume Created Date'],('completion date',ident)
        assert _valid_resume_link(row['Resume Link']) and hashlib.sha256(docx.read_bytes()).hexdigest()==receipt['sha256'],('linked file',ident)
        assert len(docx.name)<=150 and re.search(r'\+\d{1,5}\.docx$',docx.name),('filename',ident)
        approved=json.loads((OUT/('visual-'+str(ident)+'.json')).read_text(encoding='utf-8'))
        assert approved['approved'] and approved['sha256']==receipt['sha256'],('visual review',ident)
        qa=receipt['qa'];native=json.loads(Path(qa['native_validation']).read_text(encoding='utf-8-sig'))
        assert qa['status']=='pass' and native['status']=='native-valid' and native['word_pages']==native['pdf_pages']==2,('native Word',ident)
        with fitz.open(native['pdf']) as pdf:assert len(pdf)==2 and all(p.get_text().strip() for p in pdf),('PDF',ident)
        completed.append({'id':ident,'company':row['Company'],'title':row['Job Title'],'resume':str(docx),'date':row['Resume Created Date'],'sha256':receipt['sha256'],'word_pages':2,'pdf_pages':2})
    completed_ids={v['id'] for v in completed}
    preserved=0
    allowed={'Resume Created','Resume Link','Resume Created Date','Notes','Apply?','Qualifies to Apply?'}
    changes=[]
    for ident,prior in old.items():
        if ident not in current:issues.append({'id':ident,'issue':'Existing row missing'});continue
        now=current[ident]
        if resume_already_created(prior.get('Resume Created')):
            assert all(now.get(k)==prior.get(k) for k in ('Resume Created','Resume Link','Resume Created Date')),('protected existing resume state',ident)
            preserved+=1
        for key,value in prior.items():
            if key not in allowed and now.get(key)!=value:changes.append({'id':ident,'field':key,'before':value,'after':now.get(key)})
    assert not issues and not changes,('Protected tracker data changed',issues,changes)
    pending=read_queue(remote,auto_approve_geographic=True)
    leftovers=[]
    for ident in sorted(goals-completed_ids):
        row=current[ident];reason=''
        latest_match=OUT/('match-'+str(ident)+'.json')
        if latest_match.exists():
            review=json.loads(latest_match.read_text(encoding='utf-8'))
            if review.get('status')=='reviewed' and not review.get('accepted'):reason='Below current evidence-backed match thresholds'
        notes=str(row.get('Notes',''));failed=[line for line in notes.splitlines() if line.strip().casefold().startswith(RESUME_FAILURE_PREFIX.casefold())]
        if not reason:reason=failed[-1] if failed else notes[-600:]
        proofs=[]
        for prefix in ('firecrawl-posting-','firecrawl-details-'):
            p=OUT/(prefix+str(ident)+'.json')
            if p.exists():
                data=json.loads(p.read_text(encoding='utf-8'))
                proofs.append({'verified':data.get('verified'),'blocker':data.get('blocker'),'http_status':(data.get('data',{}).get('metadata') or {}).get('statusCode')})
        excluded=('Eligibility exclusion' in reason or reason.startswith('Below current') or any(p['http_status'] in (404,410) for p in proofs))
        leftovers.append({'id':ident,'company':row.get('Company'),'classification':'excluded' if excluded else 'blocked','reason':reason,'retrieval_evidence':proofs})
    ensure_frozen_headers(remote)
    frozen={p['title']:p.get('gridProperties',{}).get('frozenRowCount',0) for p in remote._sheet_properties()}
    assert all(n>=1 for n in frozen.values())
    result={'verified_at':datetime.now(timezone.utc).isoformat(),'tracker_rows_inspected':len(tab.rows),'original_pending':len(goals),'completed_verified':len(completed),'already_created_preserved':preserved,'initial_excluded':sum(baseline['counts'][k] for k in ('not_approved','duplicate_excluded','missing_identity','cost_excluded','rejected_excluded')),'additional_excluded':sum(v['classification']=='excluded' for v in leftovers),'blocked':sum(v['classification']=='blocked' for v in leftovers),'completed':sorted(completed,key=lambda x:x['id']),'remaining':leftovers,'frozen_rows':frozen,'protected_field_changes':changes,'master_sha256':hashlib.sha256((ROOT/'input/master-resume/master-resume-v4.docx').read_bytes()).hexdigest(),'applications_submitted':0,'cover_letters_created':0,'drive_uploads':0,'current_pending_ids':[j.scout_id for j in pending.pending]}
    (OUT/'final-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('completed','remaining','current_pending_ids')}))
    print(json.dumps(leftovers,ensure_ascii=False))
