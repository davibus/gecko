from pathlib import Path
import json,re,sys
from urllib.parse import urlsplit,unquote
R=Path('C:/gecko_main');sys.path.insert(0,str(R/'job-scout'));import resume_naming
s=json.loads((R/'openclaw/application-queue/batch-rows2-100-20261014-snapshot.json').read_text());results=[]
for n,r in s['rows']:
 if not r.get('Resume Link'):continue
 p=Path(unquote(urlsplit(r['Resume Link']).path).lstrip('/'));key=resume_naming.job_number(p);hits=[]
 for f in (R/'input/job-descriptions').glob('*.md'):
  c=f.read_text(encoding='utf-8-sig',errors='replace');m=re.search(r'(?mi)^\s*-\s*\*\*(?:Job Number|Job Key \(Indeed jk\)):\*\*\s*`?([^`\s]+)',c)
  if m and m[1]==key and r['Company'].casefold() in c[:2500].casefold() and r['Job Title'].casefold() in c[:2500].casefold():
   a=re.search(r'(?mi)^- \*\*Authoritative URL:\*\*\s*(https?://[^\s]+)',c);hits.append({'path':str(f),'key':key,'authoritative_url':a[1] if a else None})
 results.append({'id':str(r['Scout ID']),'row':n,'matching_descriptions':hits})
q=R/'openclaw/application-queue';(q/'batch-rows2-100-20261014-archive-map.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps([{'id':x['id'],'matches':len(x['matching_descriptions']),'authoritative_urls':[v['authoritative_url'] for v in x['matching_descriptions'] if v['authoritative_url']]} for x in results]))
