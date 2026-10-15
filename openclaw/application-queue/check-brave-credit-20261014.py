import sys,os,json
from pathlib import Path
R=Path('C:/gecko_main');Q=R/'openclaw/application-queue';sys.path.insert(0,str(R/'job-scout'))
from google_tracker import load_environment
from discover_ats_employers import _brave_search
load_environment();key=os.getenv('BRAVE_SEARCH_API_KEY','').strip();assert key,'Brave API key is not configured in the current Gecko environment'
try:
 results=_brave_search('site:veriff.com/careers "Head of Product Marketing"',key)
 report={'search_ok':True,'query':'Veriff Head of Product Marketing employer page','results':[{'title':x.get('title'),'url':x.get('url')} for x in results]}
except Exception as error:report={'search_ok':False,'error_type':type(error).__name__,'error':str(error).replace(key,'[redacted]')[:450]}
(Q/'brave-credit-retry-20261014.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
