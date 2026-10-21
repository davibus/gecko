import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'job-scout'))
from tracker_schema import LEGACY_SCOUT_HEADERS, REJECTED_HEADERS
from migrate_sqlite_tracker import import_snapshot
from sqlite_tracker import SQLiteTracker
from google_tracker import GoogleTracker
from generate_apply_queue import read_queue
from normalize import normalize
from models import RawListing


class SQLiteTrackerTests(unittest.TestCase):
    def test_reordered_current_layout_preserves_informational_resume_column(self):
        from tracker_schema import CURRENT_SCOUT_HEADERS
        headers=list(reversed(CURRENT_SCOUT_HEADERS))
        with self.tracker.connection() as con, con:
            con.execute("UPDATE workspace_datasets SET headers_json=? WHERE name='Job List'",(json.dumps(headers),))
            for slot,raw in con.execute("SELECT slot,values_json FROM workspace_records WHERE dataset='Job List'").fetchall():
                data=json.loads(raw)
                data['Qualifies to Apply?']=data.pop('Apply?','')
                data['Create Resume']='No'
                data['Enough Data']='User note'
                con.execute("UPDATE workspace_records SET values_json=? WHERE dataset='Job List' AND slot=?",(json.dumps(data),slot))
        self.assertEqual([j.scout_id for j in read_queue(self.tracker).pending],[10])
        original=self.tracker.scout().rows[0][1]
        self.tracker.dashboard_edit(original,{'Notes':'Notes in the new location'})
        saved=self.tracker.scout().rows[0][1]
        self.assertEqual(saved['Notes'],'Notes in the new location')
        self.assertEqual(saved['Create Resume'],'No')
        self.assertEqual(saved['Enough Data'],'User note')
        self.assertEqual(saved['Qualifies to Apply?'],'Yes')

    def test_qualifies_header_keeps_queue_and_approval_writes_working(self):
        with self.tracker.connection() as con, con:
            headers=json.loads(con.execute("SELECT headers_json FROM workspace_datasets WHERE name='Job List'").fetchone()[0])
            headers[headers.index('Apply?')]='Qualifies'
            con.execute("UPDATE workspace_datasets SET headers_json=? WHERE name='Job List'",(json.dumps(headers),))
            for slot,raw in con.execute("SELECT slot,values_json FROM workspace_records WHERE dataset='Job List'").fetchall():
                data=json.loads(raw)
                data['Qualifies']=data.pop('Apply?','')
                con.execute("UPDATE workspace_records SET values_json=? WHERE dataset='Job List' AND slot=?",(json.dumps(data),slot))
        self.assertEqual([j.scout_id for j in read_queue(self.tracker).pending],[10])
        original=self.tracker.scout().rows[0][1]
        self.tracker.dashboard_edit(original,{'Apply?':'No'})
        current=self.tracker.scout().rows[0][1]
        self.assertEqual(current['Qualifies'],'No')
        self.assertEqual(current['Apply?'],'No')
        with self.tracker.connection() as con:
            raw=json.loads(con.execute("SELECT values_json FROM workspace_records WHERE dataset='Job List'").fetchone()[0])
        self.assertNotIn('Apply?',raw)

    def test_resume_completion_records_denver_date_in_named_column(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with self.tracker.connection() as con, con:
            headers=json.loads(con.execute("SELECT headers_json FROM workspace_datasets WHERE name='Job List'").fetchone()[0])
            if 'Resume Created Date' not in headers:
                headers.insert(2, 'Resume Created Date')
            con.execute("UPDATE workspace_datasets SET headers_json=? WHERE name='Job List'",(json.dumps(headers),))
        resume=Path(self.temp.name)/'date-test.docx'
        resume.write_bytes(b'nonempty test artifact')
        with patch('google_tracker.RESUME_DIR',Path(self.temp.name)):
            self.tracker.mark_scout_resume(10,resume.as_uri(),allow_local=True,require_approved=True)
        data=next(d for _,d in self.tracker.scout().rows if str(d['Scout ID'])=='10')
        self.assertEqual(data['Resume Created Date'],datetime.now(ZoneInfo('America/Denver')).date().isoformat())
        self.assertEqual(data['Resume Created'],'X')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name)/'gecko.sqlite3'
        headers = list(LEGACY_SCOUT_HEADERS)
        # Keep the physical current Sheet ID spelling, not a historical alias.
        headers = ['ID' if h=='Scout ID' else h for h in headers]
        values = {'ID':10,'Source':'test','Company':'Example','Job Title':'Paid Search Manager',
                  'Apply?':'Yes','Location':'Remote - United States','Work Arrangement':'Remote',
                  'Job URL':'https://example.com/jobs/10','Notes':'Keep my notes'}
        row = [values.get(h,'') for h in headers]
        self.snapshot = {'datasets':[
            {'name':'Job List','source_id':1,'values':[headers,row],'formulas':[headers,row]},
            {'name':'Rejected Jobs','source_id':2,'values':[list(REJECTED_HEADERS)],'formulas':[list(REJECTED_HEADERS)]},
            {'name':'Daily Run','source_id':3,'values':[['Historical report']],'formulas':[['Historical report']]},
        ]}
        import_snapshot(self.snapshot,self.db)
        self.tracker = SQLiteTracker(db=self.db)

    def test_queue_uses_sqlite_without_google(self):
        with patch('google_tracker.build_service',side_effect=AssertionError('network')):
            queue = read_queue(self.tracker,auto_approve_geographic=True)
        self.assertEqual([j.scout_id for j in queue.pending],[10])

    def test_imported_formula_does_not_block_unrelated_note_edit(self):
        with self.tracker.connection() as con, con:
            con.execute("UPDATE workspace_records SET formulas_json=? WHERE dataset='Job List'",(json.dumps({'Cost':'=IF(FALSE,\"x\",\"\")'}),))
        original = self.tracker.scout().rows[0][1]
        self.tracker.dashboard_edit(original,{'Notes':'A real note'})
        self.assertEqual(self.tracker.scout().rows[0][1]['Notes'],'A real note')
        with self.assertRaisesRegex(RuntimeError,'formula'):
            self.tracker.dashboard_edit(self.tracker.scout().rows[0][1],{'Cost':'x'})

    def test_completed_resume_is_protected_and_completion_is_atomic(self):
        from docx import Document
        import google_tracker
        resume = Path(self.temp.name)/'resume.docx'
        Document().save(resume)
        with patch.object(google_tracker,'RESUME_DIR',Path(self.temp.name)):
            self.tracker.mark_scout_resume(10,resume.as_uri(),allow_local=True,require_approved=True)
            with self.assertRaisesRegex(RuntimeError,'already has'):
                self.tracker.mark_scout_resume(10,resume.as_uri(),allow_local=True,require_approved=True)
        data = self.tracker.scout().rows[0][1]
        self.assertEqual(data['Resume Created'],'X')
        self.assertEqual(data['Resume Link'],resume.as_uri())
        self.assertFalse(read_queue(self.tracker).pending)

    def test_stale_dashboard_edit_is_rejected_and_history_kept(self):
        original = self.tracker.scout().rows[0][1]
        self.tracker.dashboard_edit(original,{'Notes':'First edit'})
        with self.assertRaisesRegex(RuntimeError,'changed'):
            self.tracker.dashboard_edit(original,{'Notes':'Stale edit'})
        self.assertEqual(self.tracker.scout().rows[0][1]['Notes'],'First edit')
        with self.tracker.connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM workspace_events').fetchone()[0],1)

    def test_discovery_adds_distinct_rows_and_preserves_manual_fields(self):
        jobs = []
        for number in (11,12):
            job = normalize(RawListing('test',str(number),f'https://example.com/jobs/{number}',
                'Paid Search Manager','New Company',location='Remote',description='Manage paid search'))
            job.id = number
            jobs.append(job)
        result = self.tracker.upsert_scout(jobs,append_only=True)
        self.assertEqual(result['added'],2)
        self.assertEqual({d['Scout ID'] for _,d in self.tracker.scout().rows},{10,11,12})
        self.assertEqual(self.tracker.scout().rows[0][1]['Notes'],'Keep my notes')

    def test_repeated_migration_cannot_overwrite_workspace(self):
        with self.assertRaisesRegex(RuntimeError,'never be overwritten'):
            import_snapshot(self.snapshot,self.db)

    def test_archive_preserves_record_and_does_not_shift_other_ids(self):
        self.tracker.delete_scout_rows([2])
        self.assertEqual(self.tracker.scout().rows,[])
        with self.tracker.connection() as con:
            record = con.execute('SELECT values_json,archived FROM workspace_records WHERE dataset=?',('Job List',)).fetchone()
        self.assertEqual(record['archived'],1)
        self.assertEqual(json.loads(record['values_json'])['ID'],10)

    def test_backend_factory_never_constructs_google_service(self):
        with patch('tracker_backend.sqlite_enabled',return_value=True), \
             patch('sqlite_tracker.DATABASE',self.db), \
             patch('google_tracker.build_service',side_effect=AssertionError('Google called')):
            self.assertIsInstance(GoogleTracker(),SQLiteTracker)

    def test_batch_rolls_back_when_any_identity_conflicts(self):
        before = self.tracker.scout()
        with self.assertRaises(sqlite3.IntegrityError):
            self.tracker.update_records({('Job List',2):{'Notes':'Must roll back'},
                                         ('Job List',3):{'ID':10}},expected=before)
        self.assertEqual(self.tracker.scout().rows[0][1]['Notes'],'Keep my notes')


if __name__=='__main__':
    unittest.main()
