import sys
import unittest
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dashboard import server as s, resume_batch
from rejected_jobs import PermanentlyRejectedError


class ResumeBatchTests(unittest.TestCase):
    def setUp(self):
        self.rows = [(i, {'Scout ID': i, 'Company': 'Company', 'Job Title': 'Role',
                         'Location': 'Utah', 'Apply?': 'Yes', 'Job URL': 'https://example.com/'+str(i)})
                     for i in range(1, 6)]
        self.rows[1][1]['Resume Created'] = ' X '
        self.rows[2][1]['Applied'] = 'X'
        self.rows[3][1]['Apply?'] = 'No'
        self.rows[4][1]['Resume Link'] = 'file:///missing.docx'
        self.tracker = SimpleNamespace(scout=lambda: SimpleNamespace(rows=self.rows),
                                       _assert_scout_row_not_rejected=lambda data: None)

    def selection(self):
        return [dict(id=str(i), version=s.version(data)) for i, data in self.rows]

    def test_mixed_selection_preserves_existing_and_exclusions(self):
        ids, items = resume_batch.select_jobs(self.tracker, self.selection())
        self.assertEqual(ids, [1])
        self.assertEqual([i['status'] for i in items], ['queued']+['skipped']*4)

    def test_stale_or_duplicate_selection_rejected(self):
        selected = self.selection()
        selected[0]['version'] = 'stale'
        with self.assertRaises(ValueError): resume_batch.select_jobs(self.tracker, selected)
        with self.assertRaises(ValueError): resume_batch.select_jobs(self.tracker, self.selection()[:1]*2)

    def test_rejection_history_excludes_job(self):
        def reject(data): raise PermanentlyRejectedError('Rejected')
        self.tracker._assert_scout_row_not_rejected = reject
        with self.assertRaisesRegex(ValueError, 'No selected jobs'):
            resume_batch.select_jobs(self.tracker, self.selection())

    def test_verified_file_and_marker_both_required(self):
        app = SimpleNamespace(operation={'items':[dict(id=str(i),status='queued') for i in range(3)]},
                              detail=lambda i: {'resume_available':i!='1', 'fields':{'Resume Created':'X' if i!='2' else ''}})
        resume_batch.verify_results(app)
        self.assertEqual([i['status'] for i in app.operation['items']], ['created','needs_attention','needs_attention'])

    def test_dispatch_exact_selected_ids_without_running_generator(self):
        app = s.Workspace(lambda:self.tracker)
        with patch.object(app, 'activity', return_value={'busy':False}), patch.object(app, 'model_info', return_value={}), patch.object(app, 'persist_operation'), patch.object(s.threading, 'Thread') as thread:
            op = app.start({'kind':'resumes','jobs':self.selection()})
        self.assertEqual(op['job_ids'], [1])
        self.assertEqual(thread.call_args.kwargs['args'], ('resumes',None))

    def test_worker_uses_only_resume_generator_and_reads_completion(self):
        app = s.Workspace(lambda:self.tracker)
        app.operation = dict(kind='resumes', status='running', started_at=s.now(), job_ids=[1], items=[dict(id='1',status='queued')])
        app.detail = lambda i: {'resume_available':True,'fields':{'Resume Created':'X'}}
        with tempfile.TemporaryDirectory() as folder, patch.object(s,'STATE',Path(folder)), patch.object(s,'run_lock',return_value=nullcontext()), patch('codex_runner.CodexJsonClient') as client, patch.object(app,'run_command',return_value=SimpleNamespace(returncode=0)) as run:
            client.return_value.complete.return_value = {'ok':True}
            client.return_value.last_receipt = {'verified':True}
            app.worker('resumes',None)
        self.assertEqual(run.call_args.args[0][-3:], [str(s.ROOT/'scripts/generate_apply_queue.py'),'--ids','1'])
        self.assertEqual(app.operation['status'],'complete')
        self.assertEqual(app.operation['items'][0]['status'],'created')


if __name__ == '__main__': unittest.main()
