import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'job-scout'))
from resume_match import assess, MASTER, POLICY

path = Path('reports/resume-match-pilot/results.json')
rows = json.loads(path.read_text(encoding='utf-8'))
for row in rows:
    if row['match']['status'] == 'pending':
        print('Retrying', row['id'], row['title'], flush=True)
        row['match'] = assess([row])[row['id']]
        path.write_text(json.dumps(rows, indent=2), encoding='utf-8')
        print(row['id'], row['match'].get('score'), row['match']['status'], row['match']['reason'], flush=True)
digest = hashlib.sha256(MASTER.read_bytes()).hexdigest()
assert all(r['match'].get('master_sha256') == digest and r['match'].get('policy') == POLICY
           for r in rows if r['match']['status'] == 'reviewed')
print('Current master and policy verified for all completed reviews.', flush=True)
