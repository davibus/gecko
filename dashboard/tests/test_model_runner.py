import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[2]/'job-scout')]
from codex_runner import verified_context, MODEL, EFFORT, CodexJsonClient, review_resume
from dashboard.source_explanations import explanation
from dashboard.server import Workspace

class ModelRunnerTests(unittest.TestCase):
    def test_dashboard_passes_pins_to_pipeline_and_records_observed_settings(self):
        import subprocess
        receipt={'model':MODEL,'effort':EFFORT,'verified':True}
        app=Workspace()
        app.operation={'kind':'gecko','status':'running','started_at':'2026-10-17T01:00:00-06:00'}
        with tempfile.TemporaryDirectory() as temp,patch('dashboard.server.STATE',Path(temp)),patch('codex_runner.CodexJsonClient') as client,patch.object(app,'run_command',return_value=subprocess.CompletedProcess([],0)) as command,patch.dict('os.environ',{'JOB_SCOUT_TRIAGE_MODEL':'other'}):
            client.return_value.complete.return_value={'ok':True}
            client.return_value.last_receipt=receipt
            app.worker('gecko',None)
            env=command.call_args.kwargs['env']
            self.assertEqual(env['JOB_SCOUT_TRIAGE_MODEL'],MODEL)
            self.assertEqual(env['JOB_SCOUT_SCORING_MODEL'],MODEL)
            self.assertEqual(env['GECKO_REASONING_EFFORT'],EFFORT)
            self.assertEqual(env['GECKO_AI_RUNNER'],'codex')
            self.assertEqual(app.operation['model_info'],receipt)
            self.assertEqual(app.operation['status'],'complete')

    def test_runtime_mismatch_is_refused(self):
        identity='01234567-0123-0123-0123-012345678901'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/('rollout-'+identity+'.jsonl')
            path.write_text(json.dumps({'type':'turn_context','payload':{'model':MODEL,'effort':'high'}}))
            with self.assertRaises(RuntimeError): verified_context(identity,Path(temp))
            path.write_text(json.dumps({'type':'turn_context','payload':{'model':MODEL,'effort':EFFORT}}))
            self.assertTrue(verified_context(identity,Path(temp))['verified'])

    def test_other_model_cannot_override_pin(self):
        with self.assertRaises(RuntimeError): CodexJsonClient().complete(model='other',system='',payload={})

    def test_resume_review_requires_explicit_approval(self):
        plan={'job':{},'requirements':{},'resume':{'selected_evidence_ids':['one']},'evidence':[{'id':'one','quote':'Source-supported fact'}]}
        with patch('codex_runner.CodexJsonClient.complete',return_value={'approved':False,'reason':'unsupported claim'}):
            with self.assertRaisesRegex(ValueError,'unsupported claim'):review_resume(plan)

    def test_source_explanations_describe_saved_cause(self):
        self.assertIn('HTTP 402',explanation({'status':'partial failure','detail':'CREDIT_EXHAUSTED'}))
        self.assertIn('Oxylabs',explanation({'status':'partial failure','detail':'[{"company":"Oxylabs","error":"HTTP 404"}]'}))
        self.assertIn('credentials',explanation({'status':'missing credentials'}))
        self.assertIn('no provider errors',explanation({'status':'success'}))
