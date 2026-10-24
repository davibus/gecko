"""Bounded one-off retrieval; persistent shared Firecrawl reservations/cache."""
import sys,json
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path('C:/gecko_main');HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8')
import scout
from firecrawl_state import config,History
from sources.firecrawl import FirecrawlClient
scout.load_local_environment()
settings=config();settings.update(enabled=True,daily_soft_credits=30,daily_hard_credits=30)
history=History(settings=settings);client=FirecrawlClient(history=history,settings=settings)
raws=json.loads((HERE/'gecko-raw.json').read_text(encoding='utf-8'))
cutoff=datetime.now(timezone.utc)-timedelta(hours=96)
targets=[]
for r in raws:
    try: posted=datetime.fromisoformat(r['date_posted'].replace('Z','+00:00'))
    except (ValueError,KeyError): continue
    if posted.tzinfo is None:posted=posted.replace(tzinfo=timezone.utc)
    if posted < cutoff:continue
    targets.append((r['source_job_id'],'https://www.adzuna.com/details/'+r['source_job_id']))
targets.append(('6fc9b727-de6b-49aa-8cbc-c3edaae5a0f9','https://jobs.ashbyhq.com/tenex/6fc9b727-de6b-49aa-8cbc-c3edaae5a0f9'))
for key,url in targets:
    path=HERE/('page-'+key+'.json')
    if path.exists():continue
    try:
        data=client.call('scrape',{'url':url,'formats':['rawHtml','markdown'],'onlyMainContent':True,'maxAge':0,'proxy':'basic','timeout':20000,'waitFor':3000,'parsers':[]})
        path.write_text(json.dumps(data,indent=2),encoding='utf-8')
        print(json.dumps({'id':key,'status':data.get('metadata',{}).get('statusCode'),'chars':len(data.get('markdown','')),'usage':history.usage()}),flush=True)
    except Exception as exc:
        print(json.dumps({'id':key,'error':str(exc),'usage':history.usage()}),flush=True)
        # Failed requests and uncertain bills are never retried in this run.
        if client.blocked:break
