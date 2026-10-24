"""Primary-Sheet preflight and receipt-backed completion for direct Playwright."""
import argparse
import json
import pathlib
import sys
from datetime import datetime
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'job-scout'))
from google_tracker import Config, GoogleTracker, _a1, _col


def job_id(row):
    return str(row.get('Scout ID', row.get('ID', ''))).strip()


def tracker():
    cfg = Config.from_environment()
    backend = json.loads((ROOT / 'job-scout/preferences/tracker-backend.json').read_text())
    assert backend['authority'] == 'google_sheets'
    assert cfg.spreadsheet_id == backend['spreadsheet_id']
    return cfg, GoogleTracker(config=cfg)


def check_row(row):
    assert not str(row.get('Applied', '')).strip(), 'Already Applied'
    assert str(row.get('Qualifies to Apply?', '')).strip().lower() == 'yes', 'Not eligible'
    assert str(row.get('Cost', '')).strip().lower() != 'x', 'Excluded by Cost'
    assert str(row.get('Resume Created', '')).strip().upper() == 'X', 'No completed resume'
    uri = urlparse(row['Resume Link'])
    assert uri.scheme == 'file'
    resume = pathlib.Path(unquote(uri.path.lstrip('/'))).resolve()
    assert resume.parent == ROOT / 'output/resumes' and resume.is_file()
    assert resume.stat().st_size > 0
    return resume


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--inventory', type=pathlib.Path)
    ap.add_argument('--out', type=pathlib.Path)
    ap.add_argument('--check', type=int)
    ap.add_argument('--receipt', type=pathlib.Path)
    args = ap.parse_args()
    cfg, t = tracker()
    tab = t.scout()
    for header in ('Company', 'Job Title', 'Applied', 'Applied Date', 'Resume Link'):
        assert sum(str(x).strip() == header for x in tab.header_values) == 1
    if args.inventory:
        requested = json.loads(args.inventory.read_text(encoding='utf-8-sig'))
        packets = []
        for previous in requested:
            ident = int(previous['ID'])
            hits = [(n, r) for n, r in tab.rows if job_id(r) == str(ident)]
            assert len(hits) == 1, f'Nonunique job {ident}'
            n, row = hits[0]
            assert row['Company'] == previous['Company'] and row['Job Title'] == previous['Job Title']
            packet = dict(id=ident, company=row['Company'], title=row['Job Title'], row=dict(row))
            try:
                resume = check_row(row)
                packet.update(resume=str(resume), url=row.get('Application URL') or row['Job URL'], status='queued')
            except AssertionError as exc:
                packet.update(status='skipped', reason=str(exc))
            packets.append(packet)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(packets, indent=2), encoding='utf-8')
        print(json.dumps([{'id':p['id'], 'company':p['company'], 'status':p['status'], 'reason':p.get('reason')} for p in packets]))
        return
    receipt = json.loads(args.receipt.read_text()) if args.receipt else None
    ident = int(receipt['id']) if receipt else args.check
    hits = [(n, r) for n, r in tab.rows if job_id(r) == str(ident)]
    assert len(hits) == 1
    n, row = hits[0]
    if not receipt:
        check_row(row)
        print(json.dumps(dict(row)))
        return
    assert receipt['confirmation_verified'] is True and receipt['confirmation_text'].strip()
    assert receipt['company'] == row['Company'] and receipt['title'] == row['Job Title']
    date = datetime.fromisoformat(receipt['submitted_at']).astimezone(ZoneInfo('America/Denver')).date().isoformat()
    old_applied = str(row.get('Applied', '')).strip()
    assert not old_applied or (old_applied.upper() == 'X' and row.get('Applied Date') == date)
    assert str(row.get('Applied Date') or '').strip() in ('', date)
    formula = t.scout(value_render_option='FORMULA')
    assert formula.header_values == tab.header_values
    entries = []
    for field, value in {'Applied':'X', 'Applied Date':date}.items():
        raw = dict(formula.rows)[n].get(field, '')
        assert not (isinstance(raw, str) and raw.lstrip().startswith('='))
        if row.get(field) != value:
            entries.append({'range': _a1(tab.title, f'{_col(tab.headers[field])}{n}'), 'values':[[value]]})
    meta = t.api.get(spreadsheetId=cfg.spreadsheet_id, fields='sheets(properties(sheetId,gridProperties(frozenRowCount)))').execute()
    assert next(s['properties']['gridProperties']['frozenRowCount'] for s in meta['sheets'] if s['properties']['sheetId'] == tab.sheet_id) >= 1
    if entries:
        t.api.values().batchUpdate(spreadsheetId=cfg.spreadsheet_id, body={'valueInputOption':'RAW', 'data':entries}).execute()
    after = t.scout()
    found = [r for _,r in after.rows if job_id(r) == str(ident)]
    assert len(found) == 1
    r = found[0]
    assert r['Company'] == row['Company'] and r['Job Title'] == row['Job Title']
    assert r['Applied'] == 'X' and r['Applied Date'] == date
    assert r.get('Previous Applied Date','') == row.get('Previous Applied Date','')
    print(json.dumps({'id':ident, 'Applied':'X', 'Applied Date':date, 'cells_written':len(entries), 'verified':True}))


if __name__ == '__main__':
    main()
