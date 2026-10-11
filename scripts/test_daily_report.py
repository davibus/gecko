"""Daily Tasks dashboard and report safety tests with an in-memory Sheets API."""
from __future__ import annotations
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'job-scout'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_report as report
from daily_tasks_dashboard import TITLE, _parse
from rejected_jobs import RejectedJob, RejectedJobsIndex
from tracker_schema import CURRENT_SCOUT_HEADERS, INDEED_APPLICATION_HEADER

class Call:
    def __init__(self, callback): self.callback=callback
    def execute(self): return self.callback()

class FakeSheets:
    def __init__(self):
        self.data={'Daily Tasks':[], 'Daily Run':[[],[]],
                   'Job Scout':[list(CURRENT_SCOUT_HEADERS)], 'Deleted Jobs':[],
                   'Rejected Jobs':[['Source','Job ID','Original Job URL','Normalized Job URL','Company','Job Title','Date Rejected','Reason or Status']]}
        self.writes=[]
        self.formats=[]
        self.fail_partial=False
        self.fail_history_after_commit=False
        self.fail_history_before_commit=False
        self.width=46
    def _sheet_properties(self):
        return [{'title':n,'sheetId':i+10,'gridProperties':{'rowCount':1000,'columnCount':self.width}}
                for i,n in enumerate(self.data)]
    def values(self): return self
    def _set(self, range_, rows):
        match=re.fullmatch(r"'([^']+)'!([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?",range_)
        assert match, range_
        title, col, start, _, _=match.groups()
        column=0
        for char in col: column=column*26+ord(char)-64
        for offset, values in enumerate(rows):
            if self.fail_partial and offset>=4:
                self.fail_partial=False
                raise OSError('simulated partial write')
            number=int(start)+offset
            while len(self.data[title])<number: self.data[title].append([])
            line=self.data[title][number-1]
            while len(line)<column+len(values)-1: line.append('')
            for i,value in enumerate(values):
                line[column+i-1]=value
                self.writes.append((title,number,column+i))
    def get(self,**kwargs):
        if 'range' not in kwargs:
            return Call(lambda:{'sheets':[{'properties':{'sheetId':p['sheetId']}}
                                         for p in self._sheet_properties()]})
        title=kwargs['range'].split('!')[0].strip("'")
        return Call(lambda:{'values':[list(row) for row in self.data[title]]})
    def update(self,**kwargs): return Call(lambda:self._set(kwargs['range'],kwargs['body']['values']) or {})
    def batchUpdate(self,**kwargs):
        def apply():
            if 'requests' in kwargs['body']:
                if self.fail_history_before_commit and any('updateCells' in item for item in kwargs['body']['requests']):
                    self.fail_history_before_commit=False
                    raise OSError('simulated history request failure before commit')
                for request in kwargs['body']['requests']:
                    if 'insertDimension' in request:
                        target=request['insertDimension']['range']
                        name=next(p['title'] for p in self._sheet_properties()
                                  if p['sheetId']==target['sheetId'])
                        count=target['endIndex']-target['startIndex']
                        self.data[name][target['startIndex']:target['startIndex']]=[[] for _ in range(count)]
                    if 'updateCells' in request:
                        target=request['updateCells']['start']
                        name=next(p['title'] for p in self._sheet_properties()
                                  if p['sheetId']==target['sheetId'])
                        values=[]
                        for row in request['updateCells']['rows']:
                            values.append([next(iter(cell.get('userEnteredValue', {}).values()), '')
                                           for cell in row['values']])
                        self._set(f"'{name}'!A{target['rowIndex']+1}",values)
                if self.fail_history_after_commit and any('updateCells' in item for item in kwargs['body']['requests']):
                    self.fail_history_after_commit=False
                    raise OSError('simulated lost history response after commit')
                self.formats.extend(kwargs['body']['requests'])
                return {}
            for item in kwargs['body']['data']:
                self._set(item['range'],item['values'])
            return {}
        return Call(apply)

def tracker(fake):
    return SimpleNamespace(api=fake,config=SimpleNamespace(spreadsheet_id='id',scout_tab='Job Scout'),
                           _sheet_properties=fake._sheet_properties)

def fields(run_id, day='2026-10-10', sources=None):
    values={name:'Unavailable' for name in report.HEADERS}
    values.update({'Run Date':day,'Run ID':run_id,'Started At':day+'T07:00:00-06:00',
                   'Completed At':day+'T07:01:00-06:00','Mode':'Dry Run',
                   'Overall Status':'WARNING','Job Scout Actual Before':1441,
                   'Indeed Rows Evaluated':138,'Errors':0,'Warnings':3,
                   'Jobs by Source':sources if sources is not None else {'Adzuna':123,'Jooble':396}})
    return values

def tab_fixture():
    columns=list(CURRENT_SCOUT_HEADERS)
    def row(**values): return {**dict.fromkeys(columns,''),**values}
    rows=[(2,row(ID=1,Source='Indeed',Company='A',**{'Job Title':'Role','Location':'Utah',
           'Job URL':'https://indeed.com/viewjob?jk=one','Apply?':'Yes',
           INDEED_APPLICATION_HEADER:'This job has expired on Indeed'})),
          (3,row(ID=2,Source='adzuna',Company='B',**{'Job Title':'Role','Location':'Remote',
           'Job URL':'https://example.test/2','Apply?':'Yes','Resume Created':' X '})),
          (4,row(ID=3,Source='adzuna',Company='C',**{'Job Title':'Role','Location':'Remote',
           'Job URL':'https://example.test/3','Apply?':'Yes'}))]
    return {'Job Scout':{'rows':rows,'headers':{},'sheet_id':1},
            'Rejected Jobs':{'rows':[],'headers':{},'sheet_id':2},
            'Deleted Jobs':{'rows':[],'headers':{},'sheet_id':3}}

class DailyReportTests(unittest.TestCase):
    def test_vertical_layout_sources_and_preserved_history(self):
        fake=FakeSheets()
        fake.data['Daily Run']=[['Historical report'],['keep']]
        report.write_report(tracker(fake),fields('one'))
        rows=fake.data['Daily Tasks']
        self.assertEqual(rows[0][0],'DAILY TASKS')
        self.assertEqual(rows[2][0],TITLE)
        self.assertIn(['Job Scout Actual Before',1441], [row[:2] for row in rows])
        self.assertIn(['Indeed Rows Evaluated',138], [row[:2] for row in rows])
        self.assertIn(['Existing Tracker Jobs by Source','Jobs in Tracker'],[row[4:6] for row in rows])
        self.assertIn(['Jooble',396],[row[4:6] for row in rows])
        self.assertTrue(fake.formats)
        self.assertTrue(all(request['repeatCell']['range']['endColumnIndex']<=6
                            for request in fake.formats if 'repeatCell' in request))
        self.assertEqual(fake.data['Daily Run'][1],['keep'])
        self.assertEqual({title for title,_,_ in fake.writes},{'Daily Tasks'})
    def test_five_days_sorted_same_day_and_old_rerun(self):
        fake=FakeSheets()
        for day in (7,9,8,10,6,11):
            report.write_report(tracker(fake),fields(f'run-{day}',f'2026-10-{day:02d}'))
        parsed,_=_parse(fake.data['Daily Tasks'])
        self.assertEqual(list(parsed),[f'2026-10-{d:02d}' for d in (11,10,9,8,7)])
        before=[list(row) for row in fake.data['Daily Tasks']]
        self.assertIsNone(report.write_report(tracker(fake),fields('old','2026-10-06'))[0])
        self.assertEqual(fake.data['Daily Tasks'],before)
        report.write_report(tracker(fake),fields('rerun','2026-10-09'))
        parsed,_=_parse(fake.data['Daily Tasks'])
        self.assertEqual(parsed['2026-10-09']['Run ID'],'rerun')
        self.assertEqual(list(parsed)[0],'2026-10-11')
    def test_variable_source_height_and_deleted_section(self):
        fake=FakeSheets()
        report.write_report(tracker(fake),fields('one',sources={'A':5,'B':4,'C':3,'D':2,'E':1,
            'F':1,'G':1,'H':1,'I':1,'J':1,'K':1,'L':1,'M':1,'N':1,'O':1,'P':1}))
        rows=fake.data['Daily Tasks']
        self.assertLess(next(i for i,r in enumerate(rows) if r[4]=='P'),
                        next(i for i,r in enumerate(rows) if r[0]=='TRACKER CHANGES'))
        self.assertIn('DELETED JOBS PROTECTION',[r[0] for r in rows])
        report.write_report(tracker(fake),fields('two','2026-10-11',{'A':1}))
        self.assertEqual(len(_parse(fake.data['Daily Tasks'])[0]),2)
    def test_user_content_and_formula_conflicts(self):
        fake=FakeSheets()
        fake.data['Daily Tasks']=[['manual task']]
        with self.assertRaisesRegex(RuntimeError,'unrelated content'):
            report.write_report(tracker(fake),fields('one'))
        fake=FakeSheets()
        report.write_report(tracker(fake),fields('one'))
        fake.data['Daily Tasks'][0].extend(['manual'])
        report.write_report(tracker(fake),fields('two','2026-10-11'))
        self.assertEqual(fake.data['Daily Tasks'][0][6],'manual')
        fake.data['Daily Tasks'][5][1]='=TODAY()'
        with self.assertRaisesRegex(RuntimeError,'partial or unrelated content|Formula protects'):
            report.write_report(tracker(fake),fields('three','2026-10-12'))
    def test_missing_tab_and_narrow_grid(self):
        fake=FakeSheets(); del fake.data['Daily Tasks']
        with self.assertRaisesRegex(RuntimeError,'not found exactly once'):
            report.write_report(tracker(fake),fields('one'))
        fake=FakeSheets(); fake.width=5
        with self.assertRaisesRegex(RuntimeError,'insufficient columns'):
            report.write_report(tracker(fake),fields('one'))
    def test_partial_write_recovers_from_journal(self):
        fake=FakeSheets()
        with TemporaryDirectory() as folder:
            pending=Path(folder)/'pending.json'
            fake.fail_partial=True
            with self.assertRaisesRegex(OSError,'partial'):
                report.write_report(tracker(fake),fields('one'),pending_path=pending)
            self.assertTrue(pending.exists())
            report.write_report(tracker(fake),fields('one'),pending_path=pending)
            self.assertFalse(pending.exists())
            self.assertEqual(_parse(fake.data['Daily Tasks'])[0]['2026-10-10']['Run ID'],'one')
    def test_run_preserves_job_tabs(self):
        fake=FakeSheets()
        state=tab_fixture()
        before={name:[list(row) for row in fake.data[name]] for name in ('Job Scout','Rejected Jobs','Deleted Jobs')}
        with TemporaryDirectory() as folder, patch.object(report,'snapshot',return_value=state),\
             patch.object(report,'add_canonical_queue'), patch.object(report,'annotate_formula_protection'):
            result,row=report.run(tracker(fake),'safe-run','2026-10-10',Path(folder))
            self.assertEqual(result['overall_status'],'WARNING',result['errors'])
            self.assertEqual(row,3)
            self.assertTrue(result['validation']['job_data_unchanged'])
            self.assertIn(['Adzuna',2],[line[4:6] for line in fake.data['Daily Tasks']])
            self.assertEqual(result['daily_run_row'],3)
            self.assertEqual(fake.data['Daily Run'][8][4], 'Jobs by Source')
            self.assertIn(['Job Scout Found',0], [line[:2] for line in fake.data['Daily Run']])
            self.assertIn(['Job Scout Found','Unavailable'], [line[:2] for line in fake.data['Daily Tasks']])
            self.assertIsNone(result['metrics']['discovery']['job_scout_found'])
            self.assertNotIn('Report Details', [line[0] for line in fake.data['Daily Run'] if line])
            self.assertIn('"run_id": "safe-run"',(Path(folder)/'2026-10-10'/'safe-run.log').read_text())
        self.assertEqual(before,{name:fake.data[name] for name in before})
    def test_live_job_list_rename_blocks_stale_config_before_any_write(self):
        fake=FakeSheets()
        fake.data['Job List']=fake.data.pop('Job Scout')
        active=tracker(fake)
        active.scout=lambda: SimpleNamespace(rows=[],headers={},sheet_id=1274044170)
        with self.assertRaisesRegex(RuntimeError,'Required Job Scout'):
            report.snapshot(active)
        with TemporaryDirectory() as folder:
            result,row=report.run(active,'failed-id','2026-10-11',Path(folder))
            self.assertEqual(result['overall_status'],'FAIL')
            self.assertIsNone(row)
            self.assertFalse(fake.writes)
            self.assertEqual(fake.data['Daily Run'],[[],[]])
            self.assertEqual(fake.data['Daily Tasks'],[])
            active.config.scout_tab='Job List'
            with patch.object(report,'add_canonical_queue'), patch.object(report,'annotate_formula_protection'):
                retried,retry_row=report.run(active,'retry-id','2026-10-11',Path(folder))
            self.assertEqual(retried['overall_status'],'WARNING',retried['errors'])
            self.assertEqual(retry_row,3)
            self.assertEqual(retried['daily_run_row'],3)
            self.assertEqual(sum(row[:1]==['Run ID'] for row in fake.data['Daily Run']),1)
    def test_run_retry_after_history_commit_response_loss_keeps_one_block(self):
        fake=FakeSheets()
        state=tab_fixture()
        fake.fail_history_after_commit=True
        with TemporaryDirectory() as folder, patch.object(report,'snapshot',return_value=state),\
             patch.object(report,'add_canonical_queue'), patch.object(report,'annotate_formula_protection'):
            failed,_=report.run(tracker(fake),'same-id','2026-10-11',Path(folder))
            self.assertEqual(failed['overall_status'],'FAIL')
            self.assertEqual(sum(row[:1]==['Run ID'] for row in fake.data['Daily Run']),1)
            retried,row=report.run(tracker(fake),'same-id','2026-10-11',Path(folder))
            self.assertEqual(retried['overall_status'],'WARNING',retried['errors'])
            self.assertEqual(row,3)
            self.assertEqual(retried['daily_run_rows_inserted'],0)
            self.assertEqual(sum(row[:1]==['Run ID'] for row in fake.data['Daily Run']),1)
    def test_failed_cli_does_not_claim_daily_run_already_recorded(self):
        output=StringIO()
        failure={'overall_status':'FAIL','sheet_updated':False,'metrics':{},
                 'warnings':[],'errors':['report failed']}
        with patch.object(report,'GoogleTracker',return_value=tracker(FakeSheets())),\
             patch.object(report,'run',return_value=(failure,None)),redirect_stdout(output):
            self.assertEqual(report.main(['--run-id','failed-id','--date','2026-10-11']),1)
        self.assertIn('Daily Tasks not written | Daily Run not written',output.getvalue())
        self.assertNotIn('already recorded',output.getvalue())
    def test_verified_no_change_retry_returns_success(self):
        output=StringIO()
        success={'overall_status':'WARNING','sheet_updated':False,'report_row':3,
                 'daily_run_row':None,'daily_run_rows_inserted':0,'metrics':{},
                 'warnings':[],'errors':[]}
        with patch.object(report,'GoogleTracker',return_value=tracker(FakeSheets())),\
             patch.object(report,'run',return_value=(success,3)),redirect_stdout(output):
            self.assertEqual(report.main(['--run-id','same-id','--date','2026-10-11']),0)
        self.assertIn('Daily Run already recorded',output.getvalue())
    def test_missing_daily_run_stops_before_dashboard_write(self):
        fake=FakeSheets()
        del fake.data['Daily Run']
        state=tab_fixture()
        with TemporaryDirectory() as folder, patch.object(report,'snapshot',return_value=state),\
             patch.object(report,'add_canonical_queue'), patch.object(report,'annotate_formula_protection'):
            failed,row=report.run(tracker(fake),'missing-history','2026-10-11',Path(folder))
        self.assertEqual(failed['overall_status'],'FAIL')
        self.assertIsNone(row)
        self.assertEqual(fake.data['Daily Tasks'],[])
        self.assertFalse(fake.writes)
    def test_refresh_today_replaces_existing_date_without_daily_run(self):
        fake=FakeSheets()
        report.write_report(tracker(fake),fields('yesterday','2026-10-10'))
        report.write_report(tracker(fake),fields('old-today','2026-10-11'))
        fake.data['Daily Tasks'][0].extend(['manual note'])
        prior_dates,_=_parse(fake.data['Daily Tasks'])
        del fake.data['Daily Run']
        state=tab_fixture()
        fixed=datetime(2026,10,11,4,20,tzinfo=report.ZONE)
        with TemporaryDirectory() as folder, patch.object(report,'snapshot',return_value=state),\
             patch.object(report,'add_canonical_queue'), patch.object(report,'annotate_formula_protection'),\
             patch.object(report,'now',return_value=fixed):
            result,row=report.run(tracker(fake),'refreshed','2026-10-11',Path(folder),refresh_today=True)
            audit=(Path(folder)/'2026-10-11'/'refreshed.json').read_text()
        self.assertEqual(result['overall_status'],'WARNING',result['errors'])
        self.assertEqual(result['entry_action'],'updated')
        self.assertEqual(row,3)
        self.assertTrue(result['validation']['daily_tasks_today_verified'])
        self.assertTrue(result['validation']['historical_dates_unchanged'])
        self.assertTrue(result['daily_run_untouched'])
        self.assertNotIn('Daily Run',fake.data)
        self.assertEqual(fake.data['Daily Tasks'][0][6],'manual note')
        dates,_=_parse(fake.data['Daily Tasks'])
        self.assertEqual(list(dates),['2026-10-11','2026-10-10'])
        self.assertEqual(dates['2026-10-11']['Run ID'],'refreshed')
        self.assertEqual(dates['2026-10-10'],prior_dates['2026-10-10'])
        self.assertIn('B8',result['changed_cells'])
        self.assertIn('"entry_action": "updated"',audit)
        self.assertIn('"changed_cells"',audit)

    def test_refresh_today_creates_single_entry_when_absent(self):
        fake=FakeSheets()
        del fake.data['Daily Run']
        state=tab_fixture()
        fixed=datetime(2026,10,11,4,20,tzinfo=report.ZONE)
        with TemporaryDirectory() as folder, patch.object(report,'snapshot',return_value=state),\
             patch.object(report,'add_canonical_queue'), patch.object(report,'annotate_formula_protection'),\
             patch.object(report,'now',return_value=fixed):
            result,row=report.run(tracker(fake),'new-today','2026-10-11',Path(folder),refresh_today=True)
        self.assertEqual(result['overall_status'],'WARNING',result['errors'])
        self.assertEqual(result['entry_action'],'created')
        self.assertEqual(row,3)
        self.assertEqual(list(_parse(fake.data['Daily Tasks'])[0]),['2026-10-11'])

    def test_refresh_today_partial_write_retries_same_date(self):
        fake=FakeSheets()
        report.write_report(tracker(fake),fields('yesterday','2026-10-10'))
        del fake.data['Daily Run']
        fake.fail_partial=True
        state=tab_fixture()
        fixed=datetime(2026,10,11,4,20,tzinfo=report.ZONE)
        with TemporaryDirectory() as folder, patch.object(report,'snapshot',return_value=state),\
             patch.object(report,'add_canonical_queue'), patch.object(report,'annotate_formula_protection'),\
             patch.object(report,'now',return_value=fixed):
            failed,_=report.run(tracker(fake),'retry-today','2026-10-11',Path(folder),refresh_today=True)
            self.assertEqual(failed['overall_status'],'FAIL')
            self.assertTrue((Path(folder)/'.dashboard-pending.json').exists())
            retried,row=report.run(tracker(fake),'retry-today','2026-10-11',Path(folder),refresh_today=True)
            self.assertEqual(retried['overall_status'],'WARNING',retried['errors'])
            self.assertEqual(retried['entry_action'],'created')
            self.assertEqual(row,3)
            self.assertFalse((Path(folder)/'.dashboard-pending.json').exists())
        self.assertEqual(list(_parse(fake.data['Daily Tasks'])[0]),['2026-10-11','2026-10-10'])
    def test_refresh_today_will_not_evict_five_historical_dates(self):
        fake=FakeSheets()
        for day in range(6,11):
            report.write_report(tracker(fake),fields(f'old-{day}',f'2026-10-{day:02d}'))
        original=[list(row) for row in fake.data['Daily Tasks']]
        fake.writes.clear()
        del fake.data['Daily Run']
        state=tab_fixture()
        fixed=datetime(2026,10,11,4,20,tzinfo=report.ZONE)
        with TemporaryDirectory() as folder, patch.object(report,'snapshot',return_value=state),\
             patch.object(report,'add_canonical_queue'), patch.object(report,'annotate_formula_protection'),\
             patch.object(report,'now',return_value=fixed):
            failed,row=report.run(tracker(fake),'new-today','2026-10-11',Path(folder),refresh_today=True)
        self.assertEqual(failed['overall_status'],'FAIL')
        self.assertIsNone(row)
        self.assertEqual(fake.data['Daily Tasks'],original)
        self.assertFalse(fake.writes)
    def test_metrics_and_discovery_classification(self):
        metrics=report.evaluate(tab_fixture(),'Job Scout')
        self.assertEqual(metrics['resume']['marked_x'],1)
        self.assertEqual(metrics['indeed']['projected_status_updates'],1)
        self.assertIsNone(metrics['discovery']['total_found'])
        events=[{'Source':'a','Job ID':'1','Job URL':'https://example.test/job'},
                {'Source':'b','Job ID':'2','Job URL':'https://example.test/job'}]
        result=report.source_discoveries(events,[],RejectedJobsIndex())
        self.assertEqual(result['cross_source_duplicates'],1)
    def test_audit_and_link(self):
        self.assertNotIn('secret123',report.public_error(ValueError('token=secret123')))
        self.assertEqual(report.link_state('https://example.test/resume'),'cloud_syntax_valid_access_unverified')
        with TemporaryDirectory() as folder:
            target=Path(folder)/'audit.json'
            report.atomic_json(target,{'run_id':'test'})
            self.assertIn('"run_id": "test"',target.read_text())

if __name__=='__main__': unittest.main()
