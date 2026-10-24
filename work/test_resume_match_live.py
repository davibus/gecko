import json
import sys
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'job-scout'))
from sources.ats import GreenhouseProvider
from normalize import normalize
from resume_match import assess, record
from hard_filters import deterministic_filter
from preferences import load_preferences

destination = Path('reports/resume-match-pilot')
destination.mkdir(parents=True, exist_ok=True)
sample_path = destination / 'sample.json'
if sample_path.exists():
    sample = json.loads(sample_path.read_text(encoding='utf-8'))
else:
    pool = []
    for token in ('realchemistry', 'dept', 'dropbox'):
        rows = GreenhouseProvider().fetch_company({'token': token, 'name': token})
        print(token, len(rows), flush=True)
        pool.extend(normalize(r) for r in rows)
    selected = []
    groups = [(12, ('paid search', 'paid media', 'performance marketing', 'digital marketing', 'sem ', 'seo ')),
              (4, ('product manager', 'product marketing', 'marketing manager', 'account director')),
              (4, ('engineer', 'scientist', 'accountant'))]
    for count, terms in groups:
        candidates = [j for j in pool if any(t in j.title.lower() for t in terms) and j not in selected]
        candidates.sort(key=lambda j: (not ('united states' in j.location.lower() or 'remote' in j.location.lower()), j.company, j.title))
        selected.extend(candidates[:count])
    sample = []
    for i, job in enumerate(selected):
        allowed, why = deterministic_filter(job, load_preferences())
        sample.append({**record(job, str(i+1)), 'location': job.location,
                       'other_filters_pass': allowed, 'other_filter_reason': why,
                       'retrieved_at': datetime.now(timezone.utc).isoformat()})
    sample_path.write_text(json.dumps(sample, indent=2), encoding='utf-8')
results = []
# Review a core-role example, adjacent roles and negative controls first.
priority = ['4', '17', '13', '12', '1', '3', '18', '19', '20', '16']
sample.sort(key=lambda r: priority.index(r['id']) if r['id'] in priority else 100+int(r['id']))
for start in range(0, len(sample), 1):
    batch = sample[start:start+1]
    print('Scoring job', start+1, 'of', len(sample), flush=True)
    scores = assess(batch)
    for item in batch:
        value = {**item, 'match': scores[item['id']]}
        results.append(value)
        print(item['id'], item['company'], item['title'], value['match'].get('score'), value['match']['status'], value['match']['reason'], flush=True)
    (destination / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
