"""Primary-Sheet preflight and receipt-backed per-job completion for direct Playwright."""
import argparse
import hashlib
import json
import pathlib
import re
import sys
from datetime import datetime
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'job-scout'))
from google_tracker import Config, GoogleTracker, _a1, _col, resume_approval_value
from tracker_schema import resolve_headers, INDEED_APPLICATION_HEADER
from rejected_jobs import REJECT_STATUSES
from normalize import posting_identity
import resume_naming

REQUIRED = ('Scout ID', 'Company', 'Job Title', 'Applied', 'Applied Date',
            'Resume Link', 'Resume Created', 'Apply?', 'Job URL', 'Source', 'Cost')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def job_id(row):
    return str(row.get('Scout ID', row.get('ID', ''))).strip()


def tracker():
    cfg = Config.from_environment()
    backend = json.loads((ROOT / 'job-scout/preferences/tracker-backend.json').read_text())
    require(backend['authority'] == 'google_sheets', 'Primary tracker authority changed')
    require(cfg.spreadsheet_id == backend['spreadsheet_id'], 'Primary spreadsheet changed')
    return cfg, GoogleTracker(config=cfg)


def local_resume(row, root=ROOT):
    uri = urlparse(str(row.get('Resume Link', '')))
    if uri.scheme == 'https':
        # The current Drive delivery workflow keeps the application artifact local.
        # Resolve its registered private, byte-verified receipt; never download,
        # upload, guess a filename or change the Sheet link during preparation.
        from resume_delivery import local_path
        resolved = local_path(str(row['Resume Link']))
        require(resolved is not None, 'Resume delivery link lacks an unchanged verified local receipt')
        resume = pathlib.Path(resolved).resolve()
    else:
        require(uri.scheme == 'file' and uri.netloc in ('', 'localhost') and not uri.query and not uri.fragment,
                'Resume delivery link needs verified local metadata; refusing to guess a filename')
        name = unquote(uri.path)
        if re.match(r'^/[A-Za-z]:/', name):
            name = name[1:]
        resume = pathlib.Path(name).resolve()
    require(resume.parent == (pathlib.Path(root)/'output/resumes').resolve() and resume.is_file()
            and resume.suffix.lower() == '.docx' and resume.stat().st_size > 0, 'Missing exact completed resume')
    return resume


def check_row(row, root=ROOT):
    for field in ('Ready to Apply?', 'Ready to Apply'):
        if field in row:
            require(str(row[field]).strip().casefold() == 'x', 'Ready to Apply is not X')
    for field in ('CAPTCHA', 'Capture'):
        if field in row:
            require(str(row[field]).strip().casefold() != 'x', 'Existing CAPTCHA marker')
    require(not str(row.get('Applied', '')).strip(), 'Already Applied')
    require(str(row.get('Apply?', row.get('Qualifies to Apply?', ''))).strip().lower() == 'yes', 'Not eligible')
    require(str(row.get('Cost', '')).strip().lower() != 'x', 'Excluded by Cost')
    require(str(row.get('Resume Created', '')).strip().upper() == 'X', 'No completed resume')
    require(resume_approval_value(row.get('Location'), row.get('Work Arrangement'), row.get('Cost')) == 'Yes',
            'Location/fee eligibility not confirmed')
    status = str(row.get('Gecko Status', '')).strip().lower()
    require(status not in set(REJECT_STATUSES) | {'expired', 'duplicate', 'applied', 'interview', 'offer', 'contacted'},
            'Rejected, expired, duplicate or previously applied')
    require(str(row.get(INDEED_APPLICATION_HEADER, '')).strip().lower() not in
            {'expired', 'this job has expired on indeed', 'applied', 'already applied', 'application submitted'},
            'Employer listing unavailable or already applied')
    require('duplicate' not in str(row.get('Notes', '')).lower(), 'Duplicate job flagged')
    return local_resume(row, root)


class PrimaryTracker:
    def __init__(self, cfg=None, remote=None, root=ROOT):
        self.cfg, self.remote = (cfg, remote) if remote is not None else tracker()
        self.root = pathlib.Path(root)

    def sheet(self, *, formulas=False):
        tab = self.remote.scout(**({'value_render_option': 'FORMULA'} if formulas else {}))
        resolve_headers(tab.header_values, required=REQUIRED)
        return tab

    def find(self, tab, ident):
        require(str(ident).isdigit() and int(ident) > 0, 'Positive stable job ID required')
        hits = [(n, r) for n, r in tab.rows if job_id(r) == str(ident)]
        require(len(hits) == 1, f'Nonunique job {ident}')
        return hits[0]

    def check(self, ident):
        tab = self.sheet()
        n, row = self.find(tab, ident)
        check_row(row, self.root)
        self.remote._assert_scout_row_not_rejected(row)
        key = posting_identity(str(row['Job URL']))
        require(bool(row['Company']) and bool(row['Job Title']) and bool(key), 'Incomplete job identity')
        require(not any(m != n and posting_identity(str(r.get('Job URL', ''))) == key for m, r in tab.rows),
                'Duplicate posting identity in tracker')
        return dict(row)

    def selected(self, ids):
        tab = self.sheet()
        self.application_columns(tab)
        self.frozen(tab)
        for ident in ids:
            self.find(tab, ident)
        return [dict(id=int(job_id(r)), company=r['Company'], title=r['Job Title'],
                     row=dict(r), sheet_row=n) for n, r in tab.rows if job_id(r).isdigit() and int(job_id(r)) in ids]

    def application_columns(self, tab):
        def unique(names):
            hits = [h for h in tab.header_values if str(h).strip().casefold() in names]
            require(len(hits) == 1, 'Missing/ambiguous application header: ' + str(names))
            return hits[0]
        return unique({'ready to apply', 'ready to apply?'}), unique({'capture', 'captcha'})

    def application_check(self, ident):
        tab = self.sheet()
        ready, captcha = self.application_columns(tab)
        _, row = self.find(tab, ident)
        reason = ('Already Applied' if str(row.get('Applied', '')).strip() else
                  'Existing CAPTCHA marker' if str(row.get(captcha, '')).strip().casefold() == 'x' else
                  'Ready to Apply is not X' if str(row.get(ready, '')).strip().casefold() != 'x' else None)
        return {'row': dict(row), 'skip': reason}

    def outcome(self, result):
        tab = self.sheet(formulas=True)
        _, captcha = self.application_columns(tab)
        n, row = self.find(tab, result['id'])
        require(row['Company'] == result['company'] and row['Job Title'] == result['title'], 'Outcome identity changed')
        require(posting_identity(row['Job URL']) == posting_identity(result['job_url']), 'Outcome posting changed')
        note = result['note']
        old = str(row.get('Notes', ''))
        values = {'Notes': old if note in old else old + ('\n' if old else '') + note}
        if result.get('captcha'):
            values[captcha] = 'X'
        for field in values:
            require(field in tab.headers, f'Missing {field}')
            require(not str(row.get(field, '')).lstrip().startswith('='), f'{field} is formula protected')
        require(not any('ARRAYFORMULA(' in str(v).upper() for _, r in tab.rows for v in r.values()),
                'Array formula requires review before writes')
        self.frozen(tab)
        fresh = self.sheet(formulas=True)
        fn, fr = self.find(fresh, result['id'])
        require(fresh.header_values == tab.header_values and fn == n and fr == row, 'Outcome row changed before write')
        entries = [{'range': _a1(tab.title, f'{_col(tab.headers[f])}{n}'), 'values': [[v]]}
                   for f, v in values.items() if row.get(f, '') != v]
        if entries:
            self.remote.api.values().batchUpdate(spreadsheetId=self.cfg.spreadsheet_id,
                body={'valueInputOption': 'RAW', 'data': entries}).execute()
        after = self.sheet(formulas=True)
        an, ar = self.find(after, result['id'])
        require(after.header_values == tab.header_values and an == n, 'Outcome readback moved')
        require(all(ar.get(f, '') == v for f, v in values.items()), 'Outcome readback failed')
        require(all(ar.get(f, '') == v for f, v in row.items() if f not in values), 'Unrelated outcome fields changed')
        self.frozen(after)
        return {'id': result['id'], 'verified': True, 'cells_written': len(entries), 'fields': list(values)}

    def prepare(self, ident):
        row = self.check(ident)
        path = local_resume(row, self.root)
        from prepare_application_package import description_for, validate_resume_identity
        _, number = description_for(str(ident), row, self.root)
        validate_resume_identity(path, row, number)
        mapped = resume_naming.identity(path)
        if mapped and 'company' in mapped:
            require(mapped['company'].casefold() == row['Company'].casefold() and
                    mapped['title'].casefold() == row['Job Title'].casefold(), 'Resume employer/title mismatch')
        data = path.read_bytes()
        url = str(row.get('Application URL') or row['Job URL'])
        require(urlparse(url).scheme == 'https' and bool(urlparse(url).hostname), 'Invalid application URL')
        return {'id': int(ident), 'company': row['Company'], 'title': row['Job Title'], 'row': row,
                'resume': str(path), 'resume_sha256': hashlib.sha256(data).hexdigest(), 'resume_bytes': len(data),
                'url': url, 'status': 'queued'}

    def frozen(self, tab):
        meta = self.remote.api.get(spreadsheetId=self.cfg.spreadsheet_id,
            fields='sheets(properties(sheetId,gridProperties(frozenRowCount)))').execute()
        count = next(s['properties'].get('gridProperties', {}).get('frozenRowCount', 0)
                     for s in meta['sheets'] if s['properties']['sheetId'] == tab.sheet_id)
        require(count >= 1, 'Frozen header verification failed')

    def receipt(self, receipt):
        require(receipt.get('confirmation_verified') is True and bool(receipt.get('confirmation_text', '').strip()),
                'Positive employer receipt required')
        at = datetime.fromisoformat(receipt['submitted_at'])
        require(at.tzinfo is not None, 'Receipt requires an actual timezone-aware submission time')
        date = at.astimezone(ZoneInfo('America/Denver')).date().isoformat()
        tab = self.sheet()
        n, row = self.find(tab, receipt['id'])
        require(receipt['company'] == row['Company'] and receipt['title'] == row['Job Title'], 'Receipt identity mismatch')
        if receipt.get('job_url'):
            require(posting_identity(receipt['job_url']) == posting_identity(row['Job URL']), 'Receipt posting changed')
        old = str(row.get('Applied', '')).strip()
        require(not old or (old.upper() == 'X' and row.get('Applied Date') == date), 'Conflicting Applied state')
        require(str(row.get('Applied Date') or '').strip() in ('', date), 'Conflicting Applied Date')
        formula = self.sheet(formulas=True)
        fn, protected = self.find(formula, receipt['id'])
        require(formula.header_values == tab.header_values and fn == n, 'Sheet moved during formula check')
        require(not any('ARRAYFORMULA(' in str(v).upper() for _, r in formula.rows for v in r.values()),
                'Array formula requires review before writes')
        values = {'Applied': 'X', 'Applied Date': date}
        for field in values:
            require(not str(protected.get(field, '')).lstrip().startswith('='), f'{field} is formula protected')
        self.frozen(tab)
        fresh = self.sheet(formulas=True)
        require(fresh.header_values == formula.header_values and fresh.rows == formula.rows,
                'Sheet changed before dispatch; receipt preserved for reconciliation')
        entries = [{'range': _a1(tab.title, f'{_col(tab.headers[f])}{n}'), 'values': [[v]]}
                   for f, v in values.items() if row.get(f) != v]
        if entries:
            self.remote.api.values().batchUpdate(spreadsheetId=self.cfg.spreadsheet_id,
                body={'valueInputOption': 'RAW', 'data': entries}).execute()
        after = self.sheet()
        an, r = self.find(after, receipt['id'])
        require(after.header_values == tab.header_values and an == n, 'Readback row/header moved')
        require(all(r.get(f) == v for f, v in values.items()), 'Applied/date readback failed')
        require(all(r.get(f, '') == row.get(f, '') for f in ('Company', 'Job Title', 'Job URL', 'Previous Applied Date')),
                'Identity/history readback failed')
        self.frozen(after)
        return {'id': int(receipt['id']), **values, 'cells_written': len(entries), 'verified': True}


def serve():
    for line in sys.stdin:
        try:
            request = json.loads(line)
            action = request['action']
            require(action in ('check', 'prepare', 'receipt', 'selected', 'application_check', 'outcome'), 'Unknown tracker operation')
            # Keep the worker and source caches, but renew the Sheets transport.
            # Reused live transports have stalled across employer transitions.
            client = PrimaryTracker()
            result = getattr(client, action)(request['receipt'] if action == 'receipt' else
                request['ids'] if action == 'selected' else request['result'] if action == 'outcome' else request['id'])
            response = {'ok': True, 'result': result}
        except Exception as exc:
            response = {'ok': False, 'error': str(exc)}
        print(json.dumps(response), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--serve', action='store_true')
    mode.add_argument('--check', type=int)
    mode.add_argument('--receipt', type=pathlib.Path)
    mode.add_argument('--inventory', type=pathlib.Path)
    ap.add_argument('--out', type=pathlib.Path)
    args = ap.parse_args()
    if args.serve:
        return serve()
    client = PrimaryTracker()
    if args.inventory:
        require(args.out is not None, '--out required with --inventory')
        packets = []
        for previous in json.loads(args.inventory.read_text(encoding='utf-8-sig')):
            ident = int(previous['ID'])
            try:
                p = client.prepare(ident)
                require((p['company'], p['title']) == (previous['Company'], previous['Job Title']), 'Inventory identity changed')
            except (ValueError, RuntimeError) as exc:
                p = {'id': ident, 'company': previous['Company'], 'title': previous['Job Title'],
                     'status': 'skipped', 'reason': str(exc)}
            packets.append(p)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(packets, indent=2), encoding='utf-8')
        print(json.dumps([{'id': p['id'], 'status': p['status'], 'reason': p.get('reason')} for p in packets]))
    elif args.receipt:
        print(json.dumps(client.receipt(json.loads(args.receipt.read_text(encoding='utf-8-sig')))))
    else:
        print(json.dumps(client.check(args.check)))


if __name__ == '__main__':
    main()
