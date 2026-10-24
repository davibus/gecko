import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

results = json.loads(Path('reports/resume-match-pilot/results.json').read_text(encoding='utf-8'))
destination = Path(r'C:\Users\DCALL\Documents\Codex\2026-10-22\the-idea-is\outputs')
destination.mkdir(parents=True, exist_ok=True)
names = {'dept':'DEPT', 'realchemistry':'Real Chemistry', 'dropbox':'Dropbox'}
passed = [r for r in results if r['match']['accepted']]
admitted = [r for r in passed if r['other_filters_pass']]
pending = [r for r in results if r['match']['status']=='pending']
lines = ['# Gecko resume-match pilot', '', datetime.now(ZoneInfo('America/Denver')).strftime('%m-%d-%Y | %I:%M %p %Z').replace('| 0','| '), '',
    f"Tested {len(results)} real postings fetched from official Greenhouse employer boards. "
    f"{len(passed)} passed resume fit, {len(admitted)} also passed the existing deterministic role/location/salary filters, "
    f"and {len(pending)} remain pending.", '',
    'The pilot did not add, remove, or change tracker jobs or generate resumes. These are screening results, not guarantees of eligibility or hiring. Availability was established by live board retrieval at the recorded time; ordinary URL, rejection-history and fee checks still apply before admission.', '',
    '## Scoring', '',
    'Current Word master only: master-resume-v4.docx. Responsibilities 40; required qualifications 30; seniority/scope 15; industry 10; preferred qualifications 5. Each requirement receives 1 (direct), 0.5 (transferable/partial) or 0 (no evidence). Unstated categories are omitted and the remaining weights normalized. Minimum total: 80; minimum responsibilities and required-skills alignment: 70% each. Missing credentials or unusable evidence can still block admission. Full comparison evidence is retained inside Gecko.', '',
    '## Operational status', '',
    'The filter is enabled in Gecko configuration. Focused offline regression checks passed: 62 tests. The real-posting pilot and admission readback ran in the Codex bundled Python runtime. Separately, the configured Gecko runtime cannot currently import SQLite: Windows reports "An Application Control policy has blocked this file." This blocks normal Gecko startup and was not changed by this scoring work.', '',
    '## Results', '', '| Employer / role | Fit score | Resume fit | Other filters |', '|---|---:|---|---|']
for r in results:
    m = r['match']
    label = names.get(r['company'],r['company'])+' — '+r['title']
    other = 'Pass' if r['other_filters_pass'] else r['other_filter_reason']
    verdict = 'Pass' if m['accepted'] else ('Pending' if m['status']=='pending' else 'Below policy')
    lines.append(f"| [{label.replace('|','/')}]({r['url']}) | {m.get('score') if m.get('score') is not None else '—'} | {verdict} | {other} |")
lines += ['', '## Evidence and gaps', '']
for r in results:
    m = r['match']
    lines += ['### '+names.get(r['company'],r['company'])+' — '+r['title'], '',
              '[Original posting]('+r['url']+') · '+r['location'], '', m['reason'], '']
    if m.get('failed_rules'):
        lines += ['Policy outcome: '+'; '.join(m['failed_rules'])+'.', '']
    if m.get('category_percentages'):
        lines += ['Category alignment: '+', '.join(k+' '+str(v)+'%' for k,v in m['category_percentages'].items() if v is not None)+'.', '']
    items = [e for entries in m.get('categories',{}).values() for e in entries]
    strong = next((e for e in items if e['support']==1), None)
    gap = next((e for e in items if e['support']==0), None)
    if strong:
        lines += ['Supported capability: '+strong['reason'], '',
                  'Master evidence: “'+strong['evidence'][0]+'”', '']
    if gap:
        lines += ['Gap: '+gap['reason'], '']
    retrieved = datetime.fromisoformat(r['retrieved_at']).astimezone(ZoneInfo('America/Denver')).strftime('%m-%d-%Y | %I:%M %p %Z').replace('| 0','| ')
    lines += ['Retrieved: '+retrieved+'. Master SHA-256: '+m.get('master_sha256','unavailable')+'.', '']
(destination/'Gecko-match-pilot.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'tested':len(results),'fit_pass':len(passed),'other_filters_pass':len(admitted),'pending':len(pending),
                  'report':str(destination/'Gecko-match-pilot.md')}))
