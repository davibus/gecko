"""Read-only verification of a canonical discovery writer's saved plan."""
from pathlib import Path
import sys, json
from collections import Counter
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'job-scout'))
sys.path.insert(0, str(ROOT / 'scripts'))
from google_tracker import GoogleTracker
from normalize import posting_identity
from audit_job_discovery import snapshot

FORMAT_FIELDS = 'sheets(properties,basicFilter,conditionalFormats,bandedRanges,merges,protectedRanges,data(startRow,startColumn,rowMetadata,columnMetadata,rowData(values(userEnteredFormat,dataValidation,textFormatRuns))))'

def matrices(value):
    return {v['range'].split('!')[0].strip("'").replace("''", "'"): v.get('values', [])
            for v in value['values']['valueRanges']}

def cell(rows, row, col):
    return rows[row-1][col-1] if row <= len(rows) and col <= len(rows[row-1]) else ''

def duplicate_keys(rows, headers):
    ids, urls = Counter(), Counter()
    for row in range(2, len(rows)+1):
        ident = str(cell(rows, row, headers['Scout ID'])).strip()
        url = str(cell(rows, row, headers['Job URL'])).strip()
        if ident: ids[ident] += 1
        if url.startswith(('http://', 'https://')): urls[posting_identity(url)] += 1
    return {'ids': {k:v for k,v in ids.items() if v>1},
            'postings': {repr(k):v for k,v in urls.items() if v>1}}

def main():
    folder = Path(sys.argv[1])
    tracker = GoogleTracker()
    before = json.loads((folder/'workbook-before.json').read_text(encoding='utf-8'))
    plan = json.loads((folder/'tracker-before-write.json').read_text(encoding='utf-8'))
    after = snapshot(tracker)
    (folder/'workbook-after.json').write_text(json.dumps(after, indent=2), encoding='utf-8')
    a,b = matrices(before), matrices(after)
    headers = after['ledger_headers']
    errors=[]
    expected={(int(v['row']),headers[v['field']]):v['value'] for v in plan['expected']}
    for (r,c),value in expected.items():
        if cell(b['Job List'],r,c)!=value: errors.append({'kind':'managed_readback','row':r,'column':c})
    unrelated=[]
    for tab in sorted(set(a)|set(b)):
        ar,br=a.get(tab,[]),b.get(tab,[])
        for r in range(1,max(len(ar),len(br))+1):
            for c in range(1,max(len(ar[r-1]) if r<=len(ar) else 0,len(br[r-1]) if r<=len(br) else 0)+1):
                if cell(ar,r,c)!=cell(br,r,c) and not (tab=='Job List' and (r,c) in expected):
                    unrelated.append({'tab':tab,'row':r,'column':c})
    errors.extend({'kind':'unplanned_cell_change',**x} for x in unrelated)
    affected=[]
    for job in plan['affected_jobs']:
        row=int(job['row']); matches=[]
        for r in range(2,len(b['Job List'])+1):
            if str(cell(b['Job List'],r,headers['Scout ID']))==str(job['job_id']): matches.append(r)
        identity_url=posting_identity(job['url'])
        actual_url=posting_identity(str(cell(b['Job List'],row,headers['Job URL'])))
        identity_ok=matches==[row] and identity_url==actual_url
        if not identity_ok: errors.append({'kind':'identity','row':row,'matches':matches})
        protected=['Applied','Response','Resume Created','Resume Link']
        protected_ok=all(cell(a['Job List'],row,headers[f])==cell(b['Job List'],row,headers[f]) for f in protected)
        if not protected_ok: errors.append({'kind':'protected_fields','row':row})
        old_notes=str(cell(a['Job List'],row,headers['Notes']))
        if old_notes and not str(cell(b['Job List'],row,headers['Notes'])).startswith(old_notes):
            errors.append({'kind':'notes_preservation','row':row})
        affected.append({**job,'identity_verified':identity_ok,'protected_fields_preserved':protected_ok,
                         'values':dict(dict(after['ledger_rows']).get(row,{}))})
    old_dups=duplicate_keys(a['Job List'],headers);new_dups=duplicate_keys(b['Job List'],headers)
    increased={kind:{k:v for k,v in new_dups[kind].items() if v>old_dups[kind].get(k,0)} for kind in new_dups}
    if any(increased.values()):errors.append({'kind':'introduced_duplicates','duplicates':increased})
    formats=tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,includeGridData=True,fields=FORMAT_FIELDS).execute()
    (folder/'workbook-format-after.json').write_text(json.dumps(formats,indent=2),encoding='utf-8')
    format_before=json.loads((folder/'workbook-format-before.json').read_text(encoding='utf-8'))
    autolinks=[]
    for sheet in formats['sheets']:
        if sheet['properties']['title']!='Job List':continue
        for data in sheet.get('data',[]):
            for i,rowdata in enumerate(data.get('rowData',[])):
                row=data.get('startRow',0)+i+1
                for j,value in enumerate(rowdata.get('values',[])):
                    col=data.get('startColumn',0)+j+1
                    uri=value.get('userEnteredFormat',{}).get('textFormat',{}).get('link',{}).get('uri')
                    if col==headers['Job URL'] and (row,col) in expected and uri:
                        if uri!=expected[row,col]:errors.append({'kind':'managed_url_hyperlink_target','row':row})
                        autolinks.append({'row':row,'column':col,'target':uri})
    def comparable(x):
        x=json.loads(json.dumps(x))
        for sheet in x['sheets']:
            sheet['properties'].get('gridProperties',{}).pop('rowCount',None)
            for data in sheet.get('data',[]):
                # Only new rows may have their height set. Preserve every old row property.
                data['rowMetadata']=data.get('rowMetadata',[])[:len(a.get(sheet['properties']['title'],[]))]
                # New rows may inherit existing formats automatically; compare existing cells.
                data['rowData']=data.get('rowData',[])[:len(a.get(sheet['properties']['title'],[]))]
                if sheet['properties']['title']=='Job List':
                    for i,rowdata in enumerate(data['rowData']):
                        row=data.get('startRow',0)+i+1
                        for j,value in enumerate(rowdata.get('values',[])):
                            col=data.get('startColumn',0)+j+1
                            if col==headers['Job URL'] and (row,col) in expected:
                                value.get('userEnteredFormat',{}).get('textFormat',{}).get('link',{}).pop('uri',None)
        return x
    format_ok=comparable(formats)==comparable(format_before)
    if not format_ok:errors.append({'kind':'format_metadata_difference'})
    new_rows=[j['row'] for j in plan['affected_jobs'] if not str(cell(a['Job List'],j['row'],headers['Scout ID']))]
    ledger_format=next(s for s in formats['sheets'] if s['properties']['title']=='Job List')
    heights={}
    for data in ledger_format.get('data',[]):
        start=data.get('startRow',0)
        for i,metadata in enumerate(data.get('rowMetadata',[])):
            row=start+i+1
            if row in new_rows:heights[row]=metadata.get('pixelSize')
    if any(heights.get(r)!=21 for r in new_rows):errors.append({'kind':'new_row_height','heights':heights})
    prior=json.loads((folder/'resume-files-before.json').read_text(encoding='utf-8-sig'))
    old_files={v['Name']:(v['Length'],datetime.fromisoformat(v['LastWriteTimeUtc'].replace('Z','+00:00')).timestamp()) for v in prior}
    current={p.name:(p.stat().st_size,p.stat().st_mtime) for p in (ROOT/'output/resumes').glob('*') if p.is_file()}
    changed_files=sorted(k for k in set(old_files)|set(current) if k not in old_files or k not in current
                         or old_files[k][0]!=current[k][0] or abs(old_files[k][1]-current[k][1])>0.001)
    if changed_files:errors.append({'kind':'resume_files_changed','files':changed_files})
    result={'verified':not errors,'errors':errors,'managed_cells_checked':len(expected),'affected_jobs':affected,
            'before_populated_rows':len(before['ledger_rows']),'after_populated_rows':len(after['ledger_rows']),
            'unplanned_changes':unrelated,'duplicates_before':old_dups,'duplicates_after':new_dups,
            'introduced_duplicates':increased,'format_metadata_preserved':format_ok,'new_row_heights':heights,
            'managed_url_hyperlinks_verified':autolinks,
            'resume_files_changed':changed_files,'resume_files_checked':len(current)}
    (folder/'independent-readback.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['affected_jobs','duplicates_before','duplicates_after']},indent=2))
    return 0 if not errors else 1

if __name__=='__main__':raise SystemExit(main())
