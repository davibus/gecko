import sys, json, os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path('C:/gecko_main')
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
from google_tracker import GoogleTracker,Config,load_environment
from storage import JobStore,DEFAULT_DB
from firecrawl_state import History
from firecrawl_discovery import seed_history,known
from sources.firecrawl import FirecrawlClient
from watch_gecko_search import LABELS,prepare_panel
from sheet_sync import ensure_frozen_headers
load_environment()
DAY=datetime.now(ZoneInfo('America/Denver')).date().isoformat()
os.environ['GECKO_UNLIMITED_USAGE']=DAY
OUT=ROOT/'work/codex-focused-search'
OUT.mkdir(parents=True,exist_ok=True)
remote=GoogleTracker(config=Config.from_environment())
def panel(activity,status='RUNNING - Codex directed'):
    rows=remote.scout().rows
    saved=json.loads((OUT/'published.json').read_text()) if (OUT/'published.json').exists() else [2953,2954]
    hits=[v for _,v in rows if str(v.get('ID',v.get('Scout ID',''))) in set(map(str,saved))]
    now=datetime.now(ZoneInfo('America/Denver')).strftime('%m-%d-%Y | %I:%M %p %Z')
    cells=[LABELS,[status,f'{len(hits)} / 20',activity,now,now]]
    remote.api.values().update(spreadsheetId=remote.config.spreadsheet_id,range="'Daily Run'!H1:L2",valueInputOption='RAW',body={'values':cells}).execute()
    assert remote.api.values().get(spreadsheetId=remote.config.spreadsheet_id,range="'Daily Run'!H1:L2").execute()['values']==cells
    return hits
if sys.argv[1]=='baseline':
    prepare_panel(remote);ensure_frozen_headers(remote)
    hits=panel('Selecting new employer postings; prior run stopped')
    print(json.dumps([{k:v.get(k) for k in ['ID','Scout ID','Company','Job Title','Job URL','Match Score','Query Used to Find']} for v in hits]))
    with JobStore(DEFAULT_DB) as store: seed_history(History(),store,remote)
elif sys.argv[1]=='search':
    query=sys.argv[2];panel('Firecrawl search: '+query[:180])
    result=FirecrawlClient().call('search',{'query':query,'limit':30,'sources':['web']})
    web=result.get('web',[]) if isinstance(result,dict) else result
    history=History()
    candidates=[{**r,'actual_query':query} for r in web if not known(history,r.get('url',''))]
    name=OUT/(datetime.now().strftime('%H%M%S')+'-search.json')
    name.write_text(json.dumps(candidates,indent=2),encoding='utf-8')
    print(json.dumps({'file':str(name),'results':len(web),'new_candidates':candidates}))
elif sys.argv[1]=='usage':print(json.dumps(History().usage(DAY)))
