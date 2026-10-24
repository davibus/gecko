import json,re,sys,html
from pathlib import Path
sys.path.insert(0,'job-scout')
from sources.web import SCRIPT_RE,_job_nodes
P=Path(__file__).resolve().parent
records=[]
for f in [P/'indeed-full-0.json',P/'indeed-full-1.json',P/'indeed-batch-2.json']:
    records += [x['data'] for x in json.loads(f.read_text(encoding='utf-8')).get('data',{}).get('alexandria',[]) if x.get('data')]
(P/'all-indeed-details.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
for j in records:
    key=j['job_key']; f=P/('employer-'+key+'.json')
    page=json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
    body=j.get('description_text') or ''; full=page.get('markdown') or ''
    nodes=[]
    for block in SCRIPT_RE.findall(page.get('rawHtml') or ''):
        try:nodes.extend(_job_nodes(json.loads(html.unescape(block))))
        except ValueError:pass
    hints=[x.strip()[:650] for x in (body+'\n'+full).splitlines() if re.search(r'must (?:reside|be|live)|states|Utah|location:|remote|hybrid|on.site|annually|salary range|base pay|base salary|posted|application.*(?:closed|open)',x,re.I)]
    print(json.dumps({'key':key,'company':j['employer']['name'],'title':j['title'],'posted':j.get('posted_at'),'external_status':page.get('metadata',{}).get('statusCode'),'nodes':[{'title':x.get('title'),'date':x.get('datePosted'),'salary':x.get('baseSalary'),'remote':x.get('jobLocationType'),'restrictions':x.get('applicantLocationRequirements')} for x in nodes],'hints':hints[:9]},ensure_ascii=True))
