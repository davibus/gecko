"""Conservative, cached company homepage lookup; never guess a domain."""
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

from google_tracker import load_environment
from sources.firecrawl import FirecrawlClient
from sources.http import _validate_public_url

DIRECTORY=Path(__file__).resolve().parents[1]/'scratch/dashboard/company-websites'
LOCK=threading.Lock()
CLIENT=None

def validate(value):
    value=str(value or '').strip()
    if not value: return ''
    parts=urlsplit(value)
    if len(value)>2000 or parts.scheme!='https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('Use a public HTTPS company website, or leave it blank.')
    try: _validate_public_url(value)
    except Exception as exc: raise ValueError('Use a public HTTPS company website.') from exc
    return value

def brand(value):
    value=re.sub(r'\b(incorporated|inc|llc|ltd|limited|corporation|corp)\b','',value.casefold())
    return re.sub('[^a-z0-9]','',value)

def lookup(company):
    global CLIENT
    company=str(company).strip()[:200]
    key=hashlib.sha256(company.casefold().encode()).hexdigest()
    path=DIRECTORY/(key+'.json')
    with LOCK:
        try:
            cached=json.loads(path.read_text(encoding='utf-8'))
            if time.time()-cached['checked_at']<86400: return cached
        except (OSError,ValueError,KeyError): pass
        load_environment()
        if CLIENT is None: CLIENT=FirecrawlClient()
        if not CLIENT.configured():
            return {'website':'','message':'Website lookup is unavailable. You can enter the company website below.'}
        try:
            data=CLIENT.call('search',{'query':json.dumps(company)+' official company website','limit':3,'sources':['web'],'timeout':15000})
            hits=data.get('web',[]) if isinstance(data,dict) else data
            name=brand(company)
            candidates={}
            if len(name)>=6:
                for hit in hits:
                    try:
                        url=validate(hit.get('url'))
                        parts=urlsplit(url);host=parts.hostname.lower().removeprefix('www.')
                        # A company name must match the actual domain and page branding.
                        if brand(host.split('.')[0])!=name or name not in brand(hit.get('title','')): continue
                        candidates[host]='https://'+parts.netloc+'/'
                    except (ValueError,AttributeError): continue
            result={'website':'','message':'No clear company website match was found. You can enter it below.'}
            if len(candidates)==1:
                host,url=next(iter(candidates.items()))
                page=CLIENT.call('scrape',{'url':url,'formats':['markdown'],'onlyMainContent':False,'timeout':15000,'maxAge':86400000})
                metadata=page.get('metadata',{})
                final=validate(metadata.get('url') or metadata.get('sourceURL') or url)
                final_host=urlsplit(final).hostname.lower().removeprefix('www.')
                if metadata.get('statusCode',200)==200 and final_host==host and name in brand(metadata.get('title','')):
                    result={'website':url,'source_url':final,'message':'Company website found. Review it before saving.'}
            result['checked_at']=time.time()
            DIRECTORY.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(result),encoding='utf-8')
            return result
        except Exception:
            # Do not expose credential-bearing provider responses to the browser.
            return {'website':'','message':'Website lookup could not finish. You can enter the company website below.'}
