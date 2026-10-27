"""Read-only final artifact and fresh visual-decision binding audit."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import fitz

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from resume_visual_review import check_decision
requests={}
for path in (ROOT/'scratch').glob('*/visual-review-request.json'):
    request=json.loads(path.read_text(encoding='utf-8'))
    requests.setdefault(str(Path(request['resume']).resolve()).casefold(),[]).append((path,request))
audited=[]
for directory in [ROOT/'reports/resume-connected-2985-2991',ROOT/'reports/resume-connected-from-2993']:
    for path in directory.glob('result-*.json'):
        result=json.loads(path.read_text(encoding='utf-8'))
        if result.get('status')!='complete':continue
        resume=Path(result['resume'])
        digest=hashlib.sha256(resume.read_bytes()).hexdigest()
        hits=[(p,r) for p,r in requests.get(str(resume.resolve()).casefold(),[]) if r['sha256']==digest]
        assert hits,f"{result['id']}: no current matching review request"
        request_path,request=hits[-1]
        decision=json.loads(Path(request['decision_path']).read_text(encoding='utf-8'))
        check_decision(request,decision,resume,request['pdf'])
        assert len(request['images'])==2 and all(Path(p).is_file() for p in request['images'])
        with fitz.open(request['pdf']) as pdf:assert len(pdf)==2
        native=json.loads((request_path.parent/'validation-status.json').read_text(encoding='utf-8-sig'))
        qa=json.loads((request_path.parent/'v2-qa.json').read_text(encoding='utf-8'))
        assert native['word_pages']==native['pdf_pages']==2
        assert qa['status']=='pass' and not qa.get('issues')
        assert qa.get('page_two_bottom_gap_pt',999)<=36 or qa.get('content_exhaustion_reason')
        audited.append({'id':result['id'],'sha256':digest,'word_pages':2,'pdf_pages':2,'page_two_bottom_gap_pt':qa.get('page_two_bottom_gap_pt'),'visual_request_id':request['request_id'],'decision':request['decision_path']})
report={'checked_at':datetime.now(timezone.utc).isoformat(),'count':len(audited),'resumes':audited}
(ROOT/'reports/resume-connected-from-2993/completed-layout-audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(f'Audited {len(audited)} final DOCX/PDF pairs: exact visual approval hashes, both images, native Word/PDF page counts and density gates pass.')
