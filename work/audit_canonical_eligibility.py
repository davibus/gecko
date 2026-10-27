from recover_gecko_pending import *
from location_evidence import source_location_blocker,location_blocker
ids={r['id'] for r in json.loads((OUT/'verified-jobs.json').read_text())}
findings=[]
with History().connect() as con:
    for row in con.execute('SELECT gecko_id,raw_json,job_json FROM daily_candidates WHERE gecko_id IS NOT NULL'):
        if row['gecko_id'] not in ids:continue
        raw=RawListing(**json.loads(row['raw_json']))
        from models import JobListing
        job=JobListing.from_dict(json.loads(row['job_json']))
        issue=source_location_blocker(raw) or location_blocker(job)
        if issue:findings.append({'id':row['gecko_id'],'company':raw.company,'issue':issue})
save('canonical-eligibility-audit.json',findings);print(json.dumps(findings,indent=2))
