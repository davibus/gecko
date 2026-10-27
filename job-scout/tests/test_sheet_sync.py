import sys
from pathlib import Path
import unittest
import json
import sqlite3
from copy import deepcopy
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sheet_sync import merge_rows, SyncConflict, index_rows, sync_headers


class SyncTests(unittest.TestCase):
    def test_formula_recalculation_is_preserved_and_cached_as_protected(self):
        self._check_formula_sync(reordered=False)

    def test_reordered_columns_write_description_by_name_and_preserve_resume_and_formula(self):
        self._check_formula_sync(reordered=True)

    def test_salary_formatting_is_verified_and_cached(self):
        self._check_formula_sync(reordered=False, format_salary=True)

    def _check_formula_sync(self, reordered, format_salary=False):
        import sheet_sync
        from sqlite_tracker import SCHEMA
        with TemporaryDirectory() as temp:
            root=Path(temp);db=root/'jobs.sqlite3';state=root/'state.json'
            local_headers=['ID','Job Description','# Words','Resume Link','User Column']
            headers=(['User Column','# Words','Resume Link','ID','Job Description']
                     if reordered else local_headers)
            original={'ID':1,'Job Description':'old','# Words':1,
                      'Resume Link':'file:///existing.docx','User Column':'keep my value'}
            if format_salary:
                local_headers.append('Salary')
                if headers is not local_headers:
                    headers.append('Salary')
                original['Salary']='USD 100000 - 120000 per year'
            local={**original,'Job Description':'two words'}
            with closing(sqlite3.connect(db)) as con, con:
                con.executescript(SCHEMA)
                con.execute("INSERT INTO workspace_datasets(name,headers_json,source_id) VALUES('Job List',?,1)",(json.dumps(local_headers+['','']),))
                con.execute("INSERT INTO workspace_records(dataset,slot,values_json) VALUES('Job List',2,?)",(json.dumps(local),))
            state.write_text(json.dumps({'spreadsheet_id':'test','rows':{'1':original}}))
            remote_data=deepcopy(original)
            formula='=COUNTA(SPLIT(E2," "))' if reordered else '=COUNTA(SPLIT(B2," "))'
            def snapshot(formulas=False):
                data=deepcopy(remote_data)
                if formulas:data['# Words']=formula
                return SimpleNamespace(title='Job List',sheet_id=1,grid_rows=100,
                    header_values=tuple(headers),rows=[(2,data)],
                    raw_rows={2:tuple(data[h] for h in headers)})
            remote=Mock()
            remote.config.spreadsheet_id='test'
            remote.scout.side_effect=lambda:snapshot()
            remote.tab.side_effect=lambda *a,**kw:snapshot(True)
            remote._sheet_properties.return_value=[{'title':'Job List','gridProperties':{'columnCount':len(headers),'rowCount':100,'frozenRowCount':1}}]
            remote.url.return_value='test'
            def write(**kwargs):
                expected=[{'range':"'Job List'!E2" if reordered else "'Job List'!B2",'values':[['two words']]}]
                if format_salary:expected.append({'range':"'Job List'!F2",'values':[['$100,000 - $120,000']]})
                self.assertEqual(kwargs['body']['data'],expected)
                remote_data.update({'Job Description':'two words','# Words':2})
                if format_salary:remote_data['Salary']='$100,000 - $120,000'
                return Mock(execute=lambda:{})
            remote.api.values.return_value.batchUpdate.side_effect=write
            with patch.object(sheet_sync,'DATABASE',db),patch.object(sheet_sync,'STATE',state),patch.object(sheet_sync,'ROOT',root), \
                    patch.object(sheet_sync,'STATUS',root/'status.json'), \
                    patch('google_tracker.load_environment'),patch('google_tracker.Config.from_environment'), \
                    patch('sheet_ranges.extend_job_list',return_value={'requests':0,'formulas_filled':0}), \
                    patch('google_tracker.GoogleTracker',return_value=remote):
                result=sheet_sync.sync()
                with closing(sqlite3.connect(db)) as check:
                    events_before=check.execute('SELECT count(*) FROM workspace_events').fetchone()[0]
                again=sheet_sync.sync()
                self.assertEqual(again['cells_written'],0)
                with closing(sqlite3.connect(db)) as check:
                    self.assertEqual(check.execute('SELECT count(*) FROM workspace_events').fetchone()[0],events_before)
            self.assertEqual(result['cells_written'],2 if format_salary else 1)
            with closing(sqlite3.connect(db)) as con:
                saved,formulas=con.execute("SELECT values_json,formulas_json FROM workspace_records").fetchone()
                wanted={**local,'# Words':2}
                if format_salary:wanted['Salary']='$100,000 - $120,000'
                self.assertEqual(json.loads(saved),wanted)
                self.assertEqual(json.loads(formulas),{'# Words':formula})
                self.assertEqual(json.loads(con.execute("SELECT headers_json FROM workspace_datasets").fetchone()[0]),headers)

    def test_sheet_order_and_custom_columns_override_local_order(self):
        self.assertEqual(sync_headers(['ID','Notes','Create Resume','Qualifies'],
                                      ['ID','Qualifies','Notes','','']),
                         ['ID','Notes','Create Resume','Qualifies'])

    def test_trailing_empty_headers_are_not_synced_as_columns(self):
        self.assertEqual(sync_headers(['ID','Notes','',''],['ID','Notes','']),
                         ['ID','Notes'])

    def test_unnamed_interior_column_requires_review(self):
        with self.assertRaisesRegex(ValueError,'Name each column'):
            sync_headers(['ID','','Notes'],['ID','Notes'])

    def test_preserves_local_resume_and_sheet_notes(self):
        base = {"1": {"Notes": "old", "Resume Link": ""}}
        local = {"1": {"Notes": "old", "Resume Link": "file:///new.docx"}}
        remote = {"1": {"Notes": "edited in Sheets", "Resume Link": ""}}
        result = merge_rows(base, local, remote, ["Notes", "Resume Link"])
        self.assertEqual(result["1"], {"Notes": "edited in Sheets", "Resume Link": "file:///new.docx"})

    def test_conflict_never_picks_a_winner(self):
        with self.assertRaises(SyncConflict) as caught:
            merge_rows({"1": {"Notes": "before"}}, {"1": {"Notes": "local"}},
                       {"1": {"Notes": "remote"}}, ["Notes"])
        self.assertEqual(caught.exception.conflicts[0]["local"], "local")
        self.assertEqual(caught.exception.conflicts[0]["sheet"], "remote")

    def test_new_jobs_in_either_direction_preserved(self):
        self.assertEqual(set(merge_rows({}, {"1": {"ID": "1"}}, {"2": {"ID": "2"}}, ["ID"])), {"1", "2"})

    def test_deletion_does_not_destroy_local_history(self):
        with self.assertRaises(SyncConflict):
            merge_rows({"1": {"ID": "1"}}, {"1": {"ID": "1"}}, {}, ["ID"])

    def test_sheet_clear_is_an_edit(self):
        merged = merge_rows({"1": {"Notes": "before"}}, {"1": {"Notes": "before"}},
                            {"1": {"Notes": ""}}, ["Notes"])
        self.assertEqual(merged["1"]["Notes"], "")

    def test_duplicate_identity_rejected(self):
        with self.assertRaises(ValueError):
            index_rows([(2, {"ID": 1}), (3, {"ID": "1"})])

    def test_old_note_only_rows_are_left_alone(self):
        self.assertEqual(index_rows([(2, {"Notes": "historical", "Apply?": "No"})]), {})

    def test_new_job_id_conflict_rejected(self):
        with self.assertRaises(SyncConflict):
            merge_rows({}, {"1": {"Company": "A"}}, {"1": {"Company": "B"}}, ["Company"])


if __name__ == "__main__":
    unittest.main()
