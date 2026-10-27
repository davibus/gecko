"""Read-only final Sheet audit for the authorized 106-ID application run."""
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from playwright_tracker import PrimaryTracker
from application_runtime import save

base = ROOT/'reports/playwright-pilot/sequential-2954-3060-except-2995-20261026'
preflight = json.loads((base/'scope-preflight.json').read_text(encoding='utf-8'))
selected = json.loads((base/'selected.json').read_text(encoding='utf-8'))
resume = (base/'resume-scope.json').exists()
expected = set(range(2973 if resume else 2954, 3061))-{2995}
assert set(p['id'] for p in selected) == expected and len(selected) == (87 if resume else 106)
original = {p['id']: p for p in preflight['selected']}
client = PrimaryTracker()
tab = client.sheet()
client.frozen(tab)
_, captcha = client.application_columns(tab)
verified, unprocessed, issues = [], [], []
for item in selected:
    ident = item['id']
    state_file = base/str(ident)/'state.json'
    if not state_file.exists():
        unprocessed.append(ident)
        continue
    state = json.loads(state_file.read_text(encoding='utf-8'))
    if not state.get('outcome_tracker', {}).get('verified'):
        unprocessed.append(ident)
        continue
    try:
        _, row = client.find(tab, ident)
        assert all(row.get(k, '') == original[ident]['row'].get(k, '') for k in ('Company','Job Title','Job URL','Previous Applied Date'))
        result = json.loads((base/str(ident)/'outcome-pending.json').read_text(encoding='utf-8'))
        assert result['note'] in row['Notes'], 'Outcome Notes missing'
        if state.get('category') == 'submitted':
            assert state.get('receipt', {}).get('confirmation_verified') is True
            date = datetime.fromisoformat(state['receipt']['submitted_at']).astimezone(ZoneInfo('America/Denver')).date().isoformat()
            assert str(row['Applied']).strip().upper() == 'X' and row['Applied Date'] == date
        elif not original[ident]['row'].get('Applied') and state.get('blocker') != 'Already Applied':
            assert not str(row.get('Applied','')).strip(), 'Unexpected Applied marker'
            assert row.get('Applied Date','') == original[ident]['row'].get('Applied Date',''), 'Unexpected Applied Date change'
        if state.get('captcha'):
            assert str(row.get(captcha,'')).strip().upper() == 'X'
        verified.append(dict(id=ident, employer=row['Company'], outcome=state['status'],
            category=state['category'], elapsed_seconds=state['elapsed_seconds'], blocker=state.get('blocker'),
            missing_questions=[q.get('question','') if isinstance(q,dict) else str(q) for q in state.get('missing_required',[])],
            url=state.get('url') or row['Job URL'], verified=True))
    except Exception as exc:
        issues.append(dict(id=ident, error=str(exc)))
constructor = None
if resume:
    _, constructor_row = client.find(tab, 2972)
    constructor_state = json.loads((base/'2972/state.json').read_text(encoding='utf-8'))
    assert str(constructor_row[captcha]).strip().upper() == 'X'
    assert not str(constructor_row.get('Applied','')).strip()
    assert constructor_state['submission_uncertain'] and constructor_state['never_automatically_retry']
    assert constructor_state['constructor_prerequisite'] is False
    assert 'Its resolution is not a prerequisite for unrelated jobs.' in constructor_row['Notes']
    constructor = dict(id=2972, captcha='X', Applied='', submission_unconfirmed=True,
                       never_automatically_retry=True, prerequisite=False, verified=True)
receipt = dict(verified_at=datetime.now(timezone.utc).isoformat(), selected_count=len(selected),
    excludes_2995=True, includes_3046=True, verified_count=len(verified), jobs=verified,
    unprocessed_ids=unprocessed, issues=issues, frozen_header_verified=True,
    spreadsheet_id=client.cfg.spreadsheet_id, constructor=constructor)
save(base/'final-sheet-readback.json', receipt)
print(json.dumps(receipt))
if issues:
    raise SystemExit(1)
