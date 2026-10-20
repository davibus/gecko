"""The dashboard must pass pinned CLI options directly to the native executable."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'job-scout'))
import codex_runner as runner


class NativeRunnerTests(unittest.TestCase):
    def test_review_receives_master_and_unselected_supporting_evidence(self):
        plan={'job':{},'requirements':{},'resume':{'selected_evidence_ids':['E001']},
              'evidence':[{'id':'E001','quote':'Selected bullet'},{'id':'E002','quote':'Summary support'}]}
        with patch('gecko_v2.source_text',return_value='Canonical master facts'),patch.object(runner.CodexJsonClient,'complete',return_value={'approved':True}) as complete:
            runner.review_resume(plan)
        payload=complete.call_args.kwargs['payload']
        self.assertEqual(payload['source_evidence'],plan['evidence'])
        self.assertEqual(payload['factual_master'],'Canonical master facts')

    def test_review_rejection_still_blocks_creation(self):
        plan={'job':{},'requirements':{},'resume':{},'evidence':[]}
        with patch('gecko_v2.source_text',return_value='Canonical facts'),patch.object(runner.CodexJsonClient,'complete',return_value={'approved':False,'reason':'Unsupported claim'}),self.assertRaisesRegex(ValueError,'Unsupported claim'):
            runner.review_resume(plan)

    def test_factual_review_ignores_heuristic_requirement_mappings(self):
        plan={'job':{},'requirements':{'tools':[{'text':'GTM','evidence_ids':['wrong']}]},'resume':{'summary':'Actual master-supported summary','codex_authored':True},'evidence':[]}
        with patch('gecko_v2.source_text',return_value='Master facts'),patch.object(runner.CodexJsonClient,'complete',return_value={'approved':True}) as complete:
            runner.review_resume(plan)
        self.assertNotIn('requirements',complete.call_args.kwargs['payload'])
        self.assertIn('codex_reviewed_summary_sha256',plan['resume'])

    def test_codex_drafts_summary_and_selects_actual_source_bullets(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            listing=Path(d)/'job.md';listing.write_text('Demand generation role')
            plan={'listing':str(listing),'evidence':[{'id':'E1','job':0,'quote':'First fact'},{'id':'E2','job':0,'quote':'Second fact'},{'id':'E3','job':0,'quote':'Relevant fact'}], 'resume':{'selected_evidence_ids':['E1','E2'],'relevant_metric_ids':[]}}
            answer={'summary':'Experienced marketing professional with source-supported demand generation and campaign reporting experience.','selected_evidence_ids':['E2','E3']}
            with patch('gecko_v2.source_text',return_value='Master facts'),patch.object(runner.CodexJsonClient,'complete',return_value=answer):
                runner.draft_resume(plan)
            self.assertEqual(plan['resume']['selected_evidence_ids'],['E2','E3'])
            self.assertEqual(plan['resume']['summary'],answer['summary'])

    def test_alignment_rejects_invented_evidence_id(self):
        plan={'requirements':{'tools':[{'text':'HubSpot'}]},'evidence':[{'id':'E1','quote':'Used HubSpot'}]}
        with patch.object(runner.CodexJsonClient,'complete',return_value={'requirements':{'tools':[{'text':'HubSpot','status':'supported','evidence_ids':['made-up']}]}}),self.assertRaisesRegex(ValueError,'invalid evidence'):
            runner.align_requirement_evidence(plan,'Master')

    def test_windows_uses_executable_instead_of_powershell_wrapper(self):
        process=MagicMock(returncode=0)
        events=[{'type':'thread.started','thread_id':'test-session'},
                {'type':'item.completed','item':{'type':'agent_message','text':'{"ok":true}'}},
                {'type':'turn.completed'}]
        process.communicate.return_value=('\n'.join(json.dumps(e) for e in events),'')
        with patch.object(runner.os,'name','nt'),patch.object(runner.shutil,'which',side_effect=lambda name:'C:/native/codex.exe' if name=='codex.exe' else 'C:/wrapper/codex.cmd'),patch.object(runner.subprocess,'Popen',return_value=process) as spawn,patch.object(runner,'verified_context',return_value={'verified':True}),patch.dict(runner.os.environ,{},clear=False):
            with patch.object(runner.os.environ,'get',side_effect=lambda key,default=None:None if key=='GECKO_MODEL_EVIDENCE' else default):
                result=runner.CodexJsonClient().complete(model=runner.MODEL,system='Return JSON',payload={})
        self.assertEqual(result,{'ok':True})
        self.assertEqual(spawn.call_args.args[0][0],'C:/native/codex.exe')
        self.assertIn('model_reasoning_effort="medium"',spawn.call_args.args[0])


if __name__=='__main__':
    unittest.main()
