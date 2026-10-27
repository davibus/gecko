"""Primary-Sheet completion transactions against isolated SQLite and mocked API."""
from contextlib import ExitStack, closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import sheet_sync
from sqlite_tracker import SCHEMA


class CompletionSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'cache.sqlite3'
        self.resume=self.root/'resume.docx';self.resume.write_bytes(b'isolated artifact')
        self.state=self.root/'state.json'
        self.original={'ID':1,'Company':'Employer','Job Title':'SEM','Job URL':'https://example.test/jobs/1',
            'Qualifies to Apply?':'Yes','Applied':'','Resume Created':'','Resume Created Date':'','Resume Link':'',
            'Location':'Remote','Work Arrangement':'Remote','Cost':'','Notes':'manual note','Create Resume':'Yes',
            'Previous Applied Date':'2020-01-01','Custom':'preserve'}
        self.headers=list(reversed(list(self.original)))
        self.remote_data=deepcopy(self.original)
        self.protected={'Create Resume':'=IF(TRUE,"Yes","No")'}
        with closing(sqlite3.connect(self.db)) as con,con:
            con.executescript(SCHEMA)
            con.execute("INSERT INTO workspace_datasets VALUES('Job List',?,1)",(json.dumps(self.headers),))
            con.execute("INSERT INTO workspace_records(dataset,slot,values_json,formulas_json) VALUES('Job List',2,?,?)",
                        (json.dumps(self.original),json.dumps(self.protected)))
        self.state.write_text(json.dumps({'spreadsheet_id':'mock','rows':{'1':self.original}}))
        self.remote=Mock();self.remote.config.spreadsheet_id='mock'
        self.remote._sheet_properties.return_value=[{'title':'Job List','sheetId':1,'gridProperties':{'frozenRowCount':3}}]
        self.remote.scout.side_effect=self.snapshot
        self.writes=[];self.bad_readback=False;self.move_during_read=False;self.reads=0
        self.remote.api.values.return_value.batchUpdate.side_effect=self.write
        stack=ExitStack();self.addCleanup(stack.close)
        for target,value in [('STATE',self.state),('STATUS',self.root/'status.json')]:
            stack.enter_context(patch.object(sheet_sync,target,value))
        stack.enter_context(patch('google_tracker.load_environment'))
        stack.enter_context(patch('google_tracker.Config.from_environment'))
        stack.enter_context(patch('google_tracker.GoogleTracker',return_value=self.remote))
        stack.enter_context(patch('google_tracker.RESUME_DIR',self.root))

    def snapshot(self,*,value_render_option='UNFORMATTED_VALUE'):
        self.reads+=1
        row=deepcopy(self.remote_data)
        if self.move_during_read and self.reads>=3:row['Notes']='concurrent edit'
        if value_render_option=='FORMULA':row.update(self.protected)
        row.update({'Scout ID':row['ID'],'Apply?':row['Qualifies to Apply?']})
        return SimpleNamespace(title='Job List',headers={h:i+1 for i,h in enumerate(self.headers)},
                               header_values=tuple(self.headers),rows=[(2,row)])

    def write(self,**kwargs):
        from google_tracker import _col
        entries=kwargs['body']['data'];self.writes.extend(entries)
        for entry in entries:
            field=next(h for i,h in enumerate(self.headers,1) if entry['range']==f"'Job List'!{_col(i)}2")
            self.assertIn(field,('Resume Created','Resume Created Date','Resume Link'))
            self.remote_data[field]=entry['values'][0][0]
        if self.bad_readback:self.remote_data['Resume Created Date']='wrong'
        return Mock(execute=lambda:{})

    def complete(self):
        return sheet_sync.complete_resume(1,self.resume.resolve().as_uri(),
            local_tracker=SimpleNamespace(path=self.db),identity=self.original)

    def cached(self):
        with closing(sqlite3.connect(self.db)) as con:
            return json.loads(con.execute('SELECT values_json FROM workspace_records').fetchone()[0])

    def test_only_three_named_cells_verified_then_cached_preserving_manual_and_formulas(self):
        self.remote_data['Notes']='edited in Google Sheet'
        baseline=deepcopy(json.loads(self.state.read_text()))
        receipt=self.complete()
        self.assertEqual(receipt['status'],'resume-completion-verified')
        self.assertEqual(len(self.writes),3)
        fields=receipt['fields']
        self.assertEqual(self.cached(),{**self.original,**fields})
        self.assertEqual(self.remote_data,{**self.original,'Notes':'edited in Google Sheet',**fields})
        self.assertEqual(json.loads(self.state.read_text())['rows']['1'],{**baseline['rows']['1'],**fields})
        self.remote.api.batchUpdate.assert_not_called()  # Larger frozen region kept.
        self.assertEqual(self.protected,{'Create Resume':'=IF(TRUE,"Yes","No")'})

    def test_completed_marker_even_with_blank_link_is_protected(self):
        self.remote_data['Resume Created']=' x '
        with self.assertRaisesRegex(ValueError,'SKIP RESUME'):self.complete()
        self.assertFalse(self.writes);self.assertEqual(self.cached(),self.original)

    def test_nonblank_link_is_protected(self):
        self.remote_data['Resume Link']='file:///existing.docx'
        with self.assertRaisesRegex(ValueError,'SKIP RESUME'):self.complete()
        self.assertFalse(self.writes)

    def test_formula_owned_completion_is_never_overwritten(self):
        self.protected['Resume Created Date']='=TODAY()'
        with self.assertRaisesRegex(ValueError,'formula protected'):self.complete()
        self.assertFalse(self.writes)

    def test_identity_and_eligibility_change_blocks_write(self):
        for field,value in [('Job URL','https://example.test/jobs/other'),('Qualifies to Apply?','No'),('Applied','X'),('Cost','x')]:
            with self.subTest(field=field):
                self.remote_data={**self.original,field:value}
                with self.assertRaises(ValueError):self.complete()
                self.assertFalse(self.writes)

    def test_global_conflict_is_preserved(self):
        self.remote_data['Notes']='remote'
        with closing(sqlite3.connect(self.db)) as con,con:
            con.execute('UPDATE workspace_records SET values_json=?',(json.dumps({**self.original,'Notes':'local'}),))
        with self.assertRaises(sheet_sync.SyncConflict):self.complete()
        self.assertFalse(self.writes)

    def test_concurrent_edit_before_dispatch_stops(self):
        self.move_during_read=True
        with self.assertRaisesRegex(ValueError,'changed while preparing'):self.complete()
        self.assertFalse(self.writes)

    def test_failed_readback_never_marks_local_complete_or_advances_baseline(self):
        self.bad_readback=True
        old=self.state.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'readback failed'):self.complete()
        self.assertEqual(self.cached(),self.original);self.assertEqual(self.state.read_bytes(),old)

    def test_removed_other_job_blocks_completion(self):
        state=json.loads(self.state.read_text());state['rows']['2']={**self.original,'ID':2}
        self.state.write_text(json.dumps(state))
        with closing(sqlite3.connect(self.db)) as con,con:
            con.execute("INSERT INTO workspace_records(dataset,slot,values_json) VALUES('Job List',3,?)",(json.dumps(state['rows']['2']),))
        with self.assertRaises(sheet_sync.SyncConflict):self.complete()
        self.assertFalse(self.writes)

    def test_archived_history_present_on_sheet_is_checked_without_unarchiving(self):
        other={**self.original,'ID':2,'Company':'Archived history'}
        state=json.loads(self.state.read_text());state['rows']['2']=other
        self.state.write_text(json.dumps(state))
        with closing(sqlite3.connect(self.db)) as con,con:
            con.execute("INSERT INTO workspace_records(dataset,slot,values_json,archived) VALUES('Job List',3,?,1)",(json.dumps(other),))
        original_snapshot=self.snapshot
        def snapshot(**kwargs):
            tab=original_snapshot(**kwargs)
            tab.rows.append((3,{**other,'Scout ID':2,'Apply?':'Yes'}))
            return tab
        self.remote.scout.side_effect=snapshot
        self.complete()
        with closing(sqlite3.connect(self.db)) as con:
            raw,archived,revision=con.execute("SELECT values_json,archived,revision FROM workspace_records WHERE slot=3").fetchone()
        self.assertEqual(json.loads(raw),other)
        self.assertEqual((archived,revision),(1,0))


if __name__=='__main__':unittest.main()
