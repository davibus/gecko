from pathlib import Path
import json
q=Path(__file__).resolve().parent
p=q/'pending-user-1294-1310.json';rows=json.loads(p.read_text(encoding='utf-8'))
rows=[r for r in rows if json.loads((q/r['job_id']/'submission-result.json').read_text(encoding='utf-8'))['outcome']!='submitted']
p.write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
md=['# Applications awaiting Dave\n','Matching tailored resumes are uploaded. Drafts are partially completed. Finish known fields and recheck current submission state before submitting.\n']
for r in rows:
 md.append('## '+r['job_id']+' - '+r['company']+' - '+r['title']+'\n');md.append(r['application_url']+'\n');md.extend('- '+x for x in r['questions']);md.append('')
(q/'pending-user-1294-1310.md').write_text('\n'.join(md),encoding='utf-8')
print(str(len(rows))+' jobs still awaiting answers.')
