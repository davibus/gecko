"""Local tracker columns and explicit, values-only Google Sheets exports."""
import json
import uuid
from datetime import datetime, timezone
from tracker_schema import CURRENT_SCOUT_HEADERS, SCOUT_HEADER_ALIASES, resolve_headers, header_key
from sqlite_tracker import stamp

RESERVED = set(CURRENT_SCOUT_HEADERS) | {a for aliases in SCOUT_HEADER_ALIASES.values() for a in aliases}
PROTECTED = {'ID', 'Scout ID', 'Source', 'Company', 'Job Title', 'Job URL',
             'Resume Created', 'Resume Link', 'Applied', 'Apply?', 'Qualifies', 'Qualifies to Apply?', 'Notes',
             'Last Updated', 'Date Found', 'Last Seen'}

def columns(tracker):
    tab = tracker.scout()
    return [{'name': name, 'editable': name not in PROTECTED,
             'custom': header_key(name) not in {header_key(n) for n in RESERVED}}
            for name in tab.header_values]

def change_column(tracker, payload):
    name = payload.get('name')
    if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(c)<32 for c in name):
        raise ValueError('Use a column name of 1–80 characters.')
    name = name.strip()
    old = payload.get('old')
    with tracker.connection() as con, con:
        con.execute('BEGIN IMMEDIATE')
        headers = json.loads(con.execute("SELECT headers_json FROM workspace_datasets WHERE name='Job List'").fetchone()[0])
        if payload.get('headers') != headers:
            raise ValueError('Columns changed; refresh before saving.')
        if header_key(name) in {header_key(n) for n in RESERVED} or header_key(name) in {header_key(n) for n in headers if n != old}:
            raise ValueError('That column name is already used or reserved by Gecko.')
        if old:
            if old not in headers or header_key(old) in {header_key(n) for n in RESERVED}:
                raise ValueError('Only custom columns can be renamed.')
            updated = [name if n == old else n for n in headers]
            for record in con.execute("SELECT slot,values_json,formulas_json FROM workspace_records WHERE dataset='Job List'").fetchall():
                values, formulas = json.loads(record['values_json']), json.loads(record['formulas_json'])
                for data in (values, formulas):
                    if old in data:
                        data[name] = data.pop(old)
                con.execute("UPDATE workspace_records SET values_json=?, formulas_json=?,revision=revision+1 WHERE dataset='Job List' AND slot=?",(json.dumps(values),json.dumps(formulas),record['slot']))
        else:
            updated = headers + [name]
        resolve_headers(updated)
        con.execute("UPDATE workspace_datasets SET headers_json=? WHERE name='Job List'",(json.dumps(updated),))
        con.execute('INSERT INTO workspace_events(at,dataset,action,before_json,after_json) VALUES(?,?,?,?,?)',
                    (stamp(),'Job List','rename-column' if old else 'add-column',json.dumps(headers),json.dumps(updated)))
    return columns(tracker)

def cell_changes(tracker, data, changes):
    allowed = {c['name'] for c in columns(tracker) if c['editable']}
    if not isinstance(changes,dict) or not changes or set(changes)-allowed:
        raise ValueError('Use the job workspace actions for protected workflow fields.')
    if any(not isinstance(v,str) or len(v)>30000 for v in changes.values()):
        raise ValueError('Cell values must be text under 30,000 characters.')
    if 'Cost' in changes and changes['Cost'].strip().lower() not in ('','x'):
        raise ValueError('Cost must be blank or x for a confirmed required application fee.')
    result = dict(changes)
    from google_tracker import resume_approval_value, is_expired_indeed, INDEED_APPLICATION_HEADER
    after = {**data, **changes}
    eligible = resume_approval_value(after.get('Location'),after.get('Work Arrangement'),after.get('Cost')) == 'Yes' and not is_expired_indeed(after.get(INDEED_APPLICATION_HEADER))
    if set(changes) & {'Cost','Location','Work Arrangement',INDEED_APPLICATION_HEADER} and not eligible and str(data.get('Apply?','')).lower() == 'yes':
        result['Apply?'] = 'No'
    return result

def export_sheet(tracker, remote=None):
    # Each export creates a new tab. No existing Sheet cells are overwritten.
    if remote is None:
        from google_tracker import GoogleTracker, Config
        remote = GoogleTracker(config=Config.from_environment())
    tab = tracker.scout()
    rows = [list(tab.header_values)] + [[data.get(h,'') for h in tab.header_values] for _,data in tab.rows]
    title = 'Gecko export ' + datetime.now(timezone.utc).strftime('%Y-%m-%d %H%M%S') + ' ' + uuid.uuid4().hex[:6]
    sid = remote.config.spreadsheet_id
    created = remote.api.batchUpdate(spreadsheetId=sid, body={'requests':[{'addSheet':{'properties':{'title':title,'gridProperties':{'rowCount':len(rows)+1,'columnCount':len(rows[0]),'frozenRowCount':1}}}}]}).execute()
    sheet_id = created['replies'][0]['addSheet']['properties']['sheetId']
    target = "'" + title + "'!A1"
    try:
        remote.api.values().update(spreadsheetId=sid,range=target,valueInputOption='RAW',body={'values':rows}).execute()
        actual = remote.api.values().get(spreadsheetId=sid,range="'"+title+"'",valueRenderOption='UNFORMATTED_VALUE').execute().get('values',[])
        def trim(row):
            row = list(row)
            while row and row[-1] == '': row.pop()
            return row
        expected = [trim(r) for r in rows]
        while expected and not expected[-1]: expected.pop()
        if [trim(r) for r in actual] != expected:
            raise RuntimeError('Export readback did not match.')
    except Exception as exc:
        raise RuntimeError(f'Export tab {title} was created but could not be verified. Review it before retrying. {exc}') from exc
    return {'url':f'https://docs.google.com/spreadsheets/d/{sid}/edit#gid={sheet_id}', 'title':title,'rows':len(rows)-1}
