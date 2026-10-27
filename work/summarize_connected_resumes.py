"""Read-only report of the two authorized connected resume batches."""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
original = ROOT/'reports/resume-connected-2985-2991'
expanded = ROOT/'reports/resume-connected-from-2993'
preflight = json.loads((expanded/'preflight.json').read_text(encoding='utf-8'))
results = []
missing = []
for directory, ids in [(original, range(2985,2992)), (expanded, preflight['pending_ids'])]:
    for ident in ids:
        path = directory/f'result-{ident}.json'
        if path.exists():
            results.append(json.loads(path.read_text(encoding='utf-8')))
        else:
            missing.append(ident)
phases = Counter()
counts = Counter()
for result in results:
    phases.update(result.get('timings',{}).get('phases_seconds',{}))
    counts.update(result.get('timings',{}).get('counts',{}))
now = datetime.now(timezone.utc)
clocks = {}
for name,directory in [('original',original),('expanded',expanded)]:
    started = json.loads((directory/'batch-clock.json').read_text(encoding='utf-8'))['started_at']
    completed = [datetime.fromisoformat(r['completed_at']) for r in results if r.get('status')=='complete' and ((r['id']<2993)==(name=='original'))]
    end = max(completed) if completed else now
    clocks[name] = {'started_at':started,'completed_at':end.isoformat(),'elapsed_seconds':(end-datetime.fromisoformat(started)).total_seconds()}
benchmark = []
for case in ['before','after','before-underfill','after-underfill']:
    r=json.loads((ROOT/'scratch/resume-performance-20261026'/case/'result.json').read_text(encoding='utf-8'))
    benchmark.append({'case':case,'elapsed_seconds':r['seconds'],'validation_attempts':len(r['attempts']),'qa':r['qa']['status'],'word_pages':r['qa']['word_pages'],'pdf_pages':r['qa']['pdf_pages'],'bottom_gap_pt':r['qa'].get('page_two_bottom_gap_pt')})
report={'checked_at':now.isoformat(),'counts':dict(Counter(r['status'] for r in results)),'missing':missing,'skipped_ids':[i for i in preflight['ids_in_scope'] if i not in preflight['pending_ids']],'batch_clocks':clocks,'latest_attempt_phase_seconds':dict(phases),'latest_attempt_counts':dict(counts),'isolated_benchmarks':benchmark,'resumes':results,'timing_note':'Per-resume elapsed preserves the first start across recovery. Phase totals cover recorded latest successful attempts; prior attempts remain in prior-result files. Agent-authored preparation before each generation is outside per-resume timer; batch wall clock includes it.'}
(expanded/'final-summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
lines=['| Job ID | Company | Resume | Elapsed |','|---|---|---|---|']
for r in results:
    seconds=int(r['elapsed_seconds']); link=f"[DOCX]({r['link']})" if r.get('status')=='complete' else r['status']
    lines.append(f"| {r['id']} | {r['company']} | {link} | {seconds//60}:{seconds%60:02d} |")
(expanded/'resume-results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='resumes'},indent=2))
