"""Canonical Firecrawl retrieval for exact older queue URLs; cache-only writes."""
import sys,json,re
from pathlib import Path
ROOT=Path('C:/gecko_main');sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
from google_tracker import load_environment
from sources.firecrawl import FirecrawlClient
from firecrawl_state import History
from datetime import datetime
from zoneinfo import ZoneInfo
def today():return datetime.now(ZoneInfo('America/Denver')).date().isoformat()
from firecrawl_discovery import extract_listing,identity
from job_extraction import extract
from link_validation import BOT,EXPIRED
import generate_apply_queue as q
load_environment()
OUT=ROOT/'reports/resume-batch-20261025'
pref=json.loads((OUT/'preflight.json').read_text(encoding='utf-8'))
history=History();client=FirecrawlClient(history=history)
(OUT/'firecrawl-usage-before.json').write_text(json.dumps(history.usage(today()),indent=2),encoding='utf-8')
for item in pref['unscored']:
    ident=item['id'];url=item['fields']['Job URL'];record={'id':ident,'url':url,'verified':False}
    path=OUT/('firecrawl-posting-'+str(ident)+'.json')
    details_mode='--details' in sys.argv
    if details_mode:
        if not path.exists():continue
        previous=json.loads(path.read_text(encoding='utf-8'))
        found=re.search(r'adzuna\.com/land/ad/(\d+)',url)
        if previous.get('verified') or previous.get('retrieval_skipped') or not found:continue
        path=OUT/('firecrawl-details-'+str(ident)+'.json')
        url='https://www.adzuna.com/details/'+found[1]
        record.update(url=url,original_url=item['fields']['Job URL'],source_posting_id=found[1])
    if path.exists():continue
    try:
        data=client.call('scrape',{'url':url,'formats':['rawHtml','markdown'],'onlyMainContent':True,'proxy':'basic','parsers':[],'maxAge':86400000})
        record['data']=data
        raw,evidence,final=extract_listing(data,url)
        text=data.get('markdown') or ''
        if (data.get('metadata') or {}).get('statusCode',200)!=200 or BOT.search(text[:3000]) or EXPIRED.search(text):raise ValueError('Posting unavailable or access challenge; no full-description acceptance')
        if raw is None:raise ValueError('No unique employer JobPosting metadata; manual identity review required')
        if q._identity_text(raw.title)!=q._identity_text(item['title']) or q._identity_text(raw.company)!=q._identity_text(item['company']):raise ValueError('Retrieved title/employer differs from exact tracker job')
        if identity(final)!=identity(url):raise ValueError('Retrieved URL differs from original stable posting identity')
        document=extract(data,raw,evidence)
        if document['status']!='complete':raise ValueError('Incomplete description: '+str(document['issues']))
        record.update(verified=True,document=document,company=raw.company,title=raw.title,final_url=final)
    except Exception as exc:record['blocker']=str(exc)
    path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k not in ('data','document')}),flush=True)
    (OUT/'firecrawl-usage-current.json').write_text(json.dumps(history.usage(today()),indent=2),encoding='utf-8')
    if client.blocked:break
