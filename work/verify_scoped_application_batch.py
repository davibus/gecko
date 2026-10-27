"""Read-only final verification of the authorized 2954-2969 application batch."""
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from playwright_tracker import PrimaryTracker
from application_runtime import save

base = ROOT/'reports/playwright-pilot/sequential-2954-2969-20261026'
client = PrimaryTracker()
tab = client.sheet(formulas=True)
values_tab = client.sheet()
assert tab.header_values == values_tab.header_values, 'Headers moved during verification'
client.frozen(tab)
ready, captcha = client.application_columns(tab)
selected = {int(p['id']): p for p in json.loads((base/'selected.json').read_text(encoding='utf-8'))}
result = []
for ident in range(2954, 2970):
    _, row = client.find(tab, ident)
    _, values_row = client.find(values_tab, ident)
    state = json.loads((base/str(ident)/'state.json').read_text(encoding='utf-8'))
    pending = json.loads((base/str(ident)/'outcome-pending.json').read_text(encoding='utf-8'))
    assert state['outcome_tracker']['verified'] is True, ident
    assert pending['note'] in row['Notes'], (ident, 'Notes missing')
    assert not str(row['Applied']).strip(), (ident, 'Unexpected Applied marker')
    for field in ('Company', 'Job Title', 'Job URL', 'Applied Date', 'Previous Applied Date', ready):
        assert values_row.get(field, '') == selected[ident]['row'].get(field, ''), (ident, field)
    if state['category'] == 'captcha':
        assert str(row[captcha]).strip().upper() == 'X', ident
    if ident == 2968:
        assert 'Employer page states: This position is no longer available.' in row['Notes']
    result.append(dict(id=ident, company=row['Company'], outcome=state['status'],
                       elapsed_seconds=state['elapsed_seconds'], blocker=state.get('blocker'),
                       verified=True, captcha=row.get(captcha, ''),
                       missing_questions=[x.get('question') for x in state.get('missing_required', [])]))
receipt = dict(verified_at=datetime.now(timezone.utc).isoformat(),
               spreadsheet_id=client.cfg.spreadsheet_id, frozen_header_verified=True, jobs=result)
save(base/'final-sheet-verification.json', receipt)
print(json.dumps(receipt))
