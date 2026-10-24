import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'job-scout'))
import resume_match as m
rows = json.loads((m.ROOT / 'reports/resume-match-pilot/results.json').read_text(encoding='utf-8'))
master = m.read_master_text(m.MASTER)
digest = hashlib.sha256(m.MASTER.read_bytes()).hexdigest()
checked = []
for row in rows:
    review = row['match']
    if review.get('status') != 'reviewed':
        continue
    assert review['master_sha256'] == digest
    assert review['policy'] == m.POLICY
    result = m.validate(review, row, master)
    assert m.spreadsheet_scores(result) == m.spreadsheet_scores(review)
    checked.append(row['url'])
print(json.dumps({'validated': len(checked), 'urls': checked}))
