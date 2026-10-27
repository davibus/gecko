"""Read-only audit of this authorized connected resume batch and live completion cells."""
import hashlib,json,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('C:/gecko_main');sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'job-scout')]
from google_tracker import GoogleTracker,Config,load_environment,_col
load_environment()
remote=GoogleTracker(config=Config.from_environment());tab=remote.scout()
audited=[]
for name in ('resume-connected-2985-2991','resume-connected-from-2993'):
    directory=ROOT/'reports'/name
    for result_path in directory.glob('result-*.json'):
        result=json.loads(result_path.read_text(encoding='utf-8'))
        if result.get('status')!='complete':continue
        ident=result['id'];receipt=json.loads((directory/f'drive-receipt-{ident}.json').read_text(encoding='utf-8'))
        path=Path(result['resume']);digest=hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest==receipt['download']['sha256'],f'{ident}: local bytes changed'
        assert receipt['metadata']['shared'] is False
        assert receipt['metadata']['permissions'] and all(p['type']=='user' and p['role']=='owner' for p in receipt['metadata']['permissions'])
        hits=[(row,data) for row,data in tab.rows if str(data.get('Scout ID'))==str(ident)]
        assert len(hits)==1,f'{ident}: live identity ambiguous'
        row,data=hits[0]
        assert data['Company']==result['company'] and data['Resume Created']=='X'
        assert data['Resume Created Date']==result['readback']['Resume Created Date']
        assert data['Resume Link']==result['link']
        audited.append({'id':ident,'company':data['Company'],'sha256':digest,'link':result['link'],
                        'range':f"'{tab.title}'!{_col(tab.headers['Resume Link'])}{row}"})
ranges=[r['range'] for r in audited]
cells=remote.api.get(spreadsheetId=remote.config.spreadsheet_id,ranges=ranges,includeGridData=True,
    fields='sheets(properties(title,gridProperties(frozenRowCount)),data(startRow,startColumn,rowData(values(hyperlink))))').execute()
targets={g.get('startRow',0)+1:c.get('hyperlink') for s in cells.get('sheets',[]) for g in s.get('data',[]) for row in g.get('rowData',[]) for c in row.get('values',[])}
assert all(targets.get(int(r['range'].rsplit('!',1)[1].lstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ')))==r['link'] for r in audited),'Live hyperlink targets differ by job row'
assert all(s['properties']['gridProperties'].get('frozenRowCount',0)>=1 for s in cells['sheets'])
report={'checked_at':datetime.now(timezone.utc).isoformat(),'count':len(audited),'live_hyperlinks_verified':True,'frozen_header_verified':True,'resumes':audited}
(ROOT/'reports/resume-connected-from-2993/completed-delivery-audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(f'Audited {len(audited)} completed resumes: exact local/Drive receipt bytes, private permissions, live marker/date/link/hyperlink and frozen row 1 verified.')
