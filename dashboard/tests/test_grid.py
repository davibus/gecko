import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2]/'scripts')]
from test_sqlite_tracker import SQLiteTrackerTests
from dashboard.grid import columns, change_column, cell_changes, export_sheet
from dashboard.server import Workspace, version

class GridTests(SQLiteTrackerTests):
    def test_stop_targets_only_owned_live_process_and_rejects_stale_run(self):
        app=Workspace(tracker_factory=lambda:self.tracker)
        app.operation={'status':'running','started_at':'test-start'}
        app.run_process=MagicMock(pid=12345)
        app.run_process.poll.return_value=None
        with patch('dashboard.server.subprocess.run') as kill:
            with self.assertRaises(ValueError): app.stop({'started_at':'stale'})
            kill.assert_not_called()
            kill.return_value.returncode=0
            self.assertEqual(app.stop({'started_at':'test-start'}),{'stopping':True})
            self.assertEqual(kill.call_args.args[0],['taskkill.exe','/PID','12345','/T','/F'])
            self.assertTrue(app.operation['stop_requested'])

    def test_full_run_has_no_selected_job_limit(self):
        app=Workspace(tracker_factory=lambda:self.tracker)
        with patch.object(app,'activity',return_value={'busy':False}), patch('dashboard.server.configured_run_ids',return_value=None), patch('dashboard.server.threading.Thread'), patch.object(app,'persist_operation'):
            result=app.start({'kind':'gecko','job_ids':[2555]})
        self.assertNotIn('job_ids',result)

    def test_selected_run_database_guard_blocks_unrelated_writes(self):
        with patch.dict('os.environ',{'GECKO_ALLOWED_JOB_IDS':'11'}):
            before=self.tracker.scout().rows[0][1]
            with self.assertRaisesRegex(RuntimeError,'outside selected'):
                self.tracker.dashboard_edit(before,{'Notes':'Not allowed'})
            self.assertEqual(self.tracker.scout().rows[0][1],before)
        with patch.dict('os.environ',{'GECKO_ALLOWED_JOB_IDS':'10'}):
            self.tracker.dashboard_edit(before,{'Notes':'Allowed'})
            self.assertEqual(self.tracker.scout().rows[0][1]['Notes'],'Allowed')
            with self.assertRaisesRegex(RuntimeError,'archival'):
                self.tracker.delete_scout_rows([2])

    def test_dashboard_dispatch_pins_configured_scope(self):
        app=Workspace(tracker_factory=lambda:self.tracker)
        with patch('dashboard.server.configured_run_ids',return_value=[10]), patch('dashboard.server.threading.Thread'), patch.object(app,'persist_operation'):
            result=app.start({'kind':'gecko','job_ids':[999]})
        self.assertEqual(result['job_ids'],[10])

    def add(self, name, old=None):
        return change_column(self.tracker,{'name':name,'old':old,'headers':list(self.tracker.scout().header_values)})

    def test_custom_column_lifecycle_preserves_job(self):
        before = self.tracker.scout().rows[0][1]
        self.add('My priority')
        current = self.tracker.scout().rows[0][1]
        changes = cell_changes(self.tracker,current,{'My priority':'High'})
        self.tracker.dashboard_edit(current,changes)
        self.add('Personal priority',old='My priority')
        saved = self.tracker.scout().rows[0][1]
        self.assertEqual(saved['Personal priority'],'High')
        self.assertNotIn('My priority',saved)
        for key,value in before.items(): self.assertEqual(saved[key],value)

    def test_reserved_duplicate_and_stale_columns(self):
        for name in ('Scout ID',' notes ','','ID'):
            with self.assertRaises(ValueError): self.add(name)
        self.add('Priority')
        with self.assertRaises(ValueError): self.add('priority')
        with self.assertRaises(ValueError): change_column(self.tracker,{'name':'Other','headers':[]})
        with self.assertRaises(ValueError): self.add('Employer',old='Company')

    def test_cells_cannot_change_identity_completion_or_applied(self):
        data=self.tracker.scout().rows[0][1]
        for field in ('ID','Resume Created','Resume Link','Applied','Notes','Apply?','Job URL'):
            with self.assertRaises(ValueError):cell_changes(self.tracker,data,{field:'changed'})

    def test_fee_cancels_approval_atomically(self):
        data=self.tracker.scout().rows[0][1]
        changes=cell_changes(self.tracker,data,{'Cost':'x'})
        self.assertEqual(changes,{'Cost':'x','Apply?':'No'})
        self.tracker.dashboard_edit(data,changes)
        saved=self.tracker.scout().rows[0][1]
        self.assertEqual(saved['Apply?'],'No')

    def test_custom_edit_does_not_change_existing_approval(self):
        self.add('Priority')
        data=self.tracker.scout().rows[0][1]
        data['Location']='Unknown'
        data['Work Arrangement']=''
        self.assertEqual(cell_changes(self.tracker,data,{'Priority':'High'}),{'Priority':'High'})

    def test_grid_rejects_stale_save(self):
        app=Workspace(tracker_factory=lambda:self.tracker)
        data=self.tracker.scout().rows[0][1]
        self.tracker.dashboard_edit(data,{'Response':'New response'})
        with self.assertRaisesRegex(ValueError,'changed since'):
            app.edit({'id':10,'version':version(data),'action':'cells','changes':{'Salary':'changed'}})

    def test_export_raw_values_and_readback(self):
        self.add('Custom')
        data=self.tracker.scout().rows[0][1]
        self.tracker.dashboard_edit(data,{'Custom':'=literal text'})
        tab=self.tracker.scout()
        rows=[list(tab.header_values)]+[[d.get(h,'') for h in tab.header_values] for _,d in tab.rows]
        remote=MagicMock()
        remote.config.spreadsheet_id='test-sheet'
        remote.api.batchUpdate.return_value.execute.return_value={'replies':[{'addSheet':{'properties':{'sheetId':987}}}]}
        remote.api.values.return_value.get.return_value.execute.return_value={'values':rows}
        result=export_sheet(self.tracker,remote)
        self.assertIn('gid=987',result['url'])
        self.assertEqual(remote.api.values.return_value.update.call_args.kwargs['valueInputOption'],'RAW')
        remote.api.values.return_value.get.return_value.execute.return_value={'values':[['wrong']]}
        with self.assertRaisesRegex(RuntimeError,'could not be verified'):export_sheet(self.tracker,remote)
