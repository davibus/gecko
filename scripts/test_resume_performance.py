"""Isolated performance and recovery contracts; no live Sheet or Word access."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import fitz
import gecko_v2 as v2
import resume_performance as perf
from resume_visual_review import check_decision, digest


class ResumePerformanceTests(unittest.TestCase):
    def test_checkpoint_restores_every_byte_and_entire_plan_without_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root/name for name in ('resume.docx','word-export.pdf','validation-status.json','v2-qa.json','tailoring-plan.json')]
            original = {p: ('original '+p.name).encode() for p in paths}
            for path, content in original.items(): path.write_bytes(content)
            plan = {'resume': {'selected_evidence_ids':['a'], 'other': ['preserve']}}
            before = deepcopy(plan)
            report = {'status':'pass','word_pages':2,'pdf_pages':2}
            checkpoint = v2.ResumeCheckpoint(plan, paths[0], root, report)
            plan['resume']['other'].append('mutation')
            plan['resume']['selected_evidence_ids'].append('b')
            for path in paths: path.write_bytes(b'bad trial')
            self.assertEqual(checkpoint.restore(plan), report)
            self.assertEqual(plan, before)
            self.assertEqual({p:p.read_bytes() for p in paths}, original)

    def fitting(self, raises=False, structural=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root/'resume.docx'
            plan={'resume':{'selected_evidence_ids':['a']}}
            good={'status':'fail','word_pages':2,'pdf_pages':2,'page_two_bottom_gap_pt':80,
                  'density_issue':'underfilled','issues':['underfilled']}
            bad={'status':'fail','word_pages':2 if structural else 3,'pdf_pages':2 if structural else 3,
                 'page_two_bottom_gap_pt':20,'issues':['unsupported content'] if structural else ['overflow']}
            originals={}
            def make(current, output):
                content=json.dumps(current).encode()
                for p in (output, root/'word-export.pdf',root/'validation-status.json',root/'v2-qa.json'):
                    p.write_bytes(content)
                if not originals: originals.update({p:p.read_bytes() for p in root.iterdir()})
            with patch.object(v2,'make_resume',side_effect=make), \
                 patch.object(v2,'native_qa',side_effect=[good,RuntimeError('COM failure') if raises else bad]) as qa, \
                 patch.object(v2,'normalize_resume_format'), \
                 patch.object(v2,'_third_bullet_fallbacks',return_value=[]), \
                 patch.object(v2,'rendered_capacity',return_value={}), \
                 patch.object(v2,'_additional_evidence',side_effect=lambda p: ['b'] if 'b' not in p['resume']['selected_evidence_ids'] else []):
                if raises:
                    with self.assertRaisesRegex(RuntimeError,'COM failure'):
                        v2.generate_two_page_resume(plan,path,root)
                else:
                    self.assertEqual(v2.generate_two_page_resume(plan,path,root),good)
                self.assertEqual(qa.call_count,2)  # No rebuild/revalidation on restoration.
            self.assertEqual(plan,{'resume':{'selected_evidence_ids':['a']}})
            self.assertEqual({p:p.read_bytes() for p in originals},originals)

    def test_rejected_overflow_restores_exact_artifacts(self): self.fitting()
    def test_native_failure_recovers_exact_checkpoint(self): self.fitting(raises=True)
    def test_structurally_invalid_two_page_trial_is_rejected(self): self.fitting(structural=True)

    def test_late_worker_output_cannot_overwrite_restored_validation(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);docx=root/'resume.docx';docx.write_bytes(b'original docx')
            pdf=root/'word-export.pdf';pdf.write_bytes(b'original pdf')
            status=root/'validation-status.json';status.write_bytes(b'original status')
            plan={'resume':{'selected_evidence_ids':['a']}}
            checkpoint=v2.ResumeCheckpoint(plan,docx,root,{'status':'pass'})
            commands=[]
            def timeout(command,**kwargs):
                commands.append(command)
                raise subprocess.TimeoutExpired(command,360)
            with patch.object(v2.subprocess,'run',side_effect=timeout), \
                 patch('word_validation_client.active_bridge_root',return_value=None):
                with self.assertRaises(subprocess.TimeoutExpired):v2.native_qa(plan,docx,root)
            checkpoint.restore(plan)
            command=commands[0]
            late_pdf=Path(command[command.index('-PdfPath')+1])
            late_status=Path(command[command.index('-ResultPath')+1])
            self.assertNotEqual(late_pdf,pdf)
            late_pdf.write_bytes(b'late export');late_status.write_bytes(b'late status')
            self.assertEqual(pdf.read_bytes(),b'original pdf')
            self.assertEqual(status.read_bytes(),b'original status')

    def test_batch_source_parse_reused_and_invalidated_by_actual_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            master=Path(tmp)/'master.docx';master.write_bytes(b'first')
            with patch.object(v2,'MASTER',master), patch.object(v2,'read_master_text',side_effect=['source one','source two']) as read:
                with perf.batch():
                    self.assertEqual(v2.master_lines(),['source one'])
                    self.assertEqual(v2.master_lines(),['source one'])
                    master.write_bytes(b'other')
                    self.assertEqual(v2.master_lines(),['source two'])
                    self.assertEqual(read.call_count,2)
                self.assertEqual(read.call_count,2)

    def test_native_cache_exact_bytes_and_versions_and_stale_result_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'scripts').mkdir();scratch=root/'qa';scratch.mkdir()
            for name in ('validate_word_native.ps1','word_validation_bridge.ps1','word_bridge_common.ps1','word_validation_client.py'):
                (root/'scripts'/name).write_text(name)
            (root/'job-scout').mkdir();(root/'job-scout/resume_source.py').write_text('source parser')
            docx=root/'resume.docx';docx.write_bytes(b'one')
            plan={'requirements':{k:[] for k in ('required_skills','preferred_skills','responsibilities')},
                  'evidence':[],'resume':{'jobs':[],'selected_evidence_ids':[]}}
            def validate(command,**kwargs):
                pdf=Path(command[command.index('-PdfPath')+1]);status=Path(command[command.index('-ResultPath')+1])
                with fitz.open() as document:
                    for _ in range(2): document.new_page().insert_text((36,50),'Isolated native validation fixture')
                    document.save(pdf)
                status.write_text(json.dumps({'status':'native-valid','word_pages':2,'pdf_pages':2,
                    'request_id':command[command.index('-RequestId')+1]}))
                return SimpleNamespace(returncode=0,stdout='native',stderr='')
            with perf.batch(),patch.object(v2,'ROOT',root),patch.object(v2,'source_fingerprint',return_value='source'), \
                 patch.object(v2,'formatting_model_hash',return_value='model'), \
                 patch.object(v2,'inspect_docx',return_value=[]),patch.object(v2,'page_two_density',return_value={}), \
                 patch.object(v2.subprocess,'run',side_effect=validate) as run:
                a=v2.native_qa(plan,docx,scratch)
                originals={p:p.read_bytes() for p in (scratch/'word-export.pdf',scratch/'validation-status.json')}
                self.assertEqual(v2.native_qa(plan,docx,scratch),a)
                self.assertEqual(run.call_count,1)
                self.assertEqual({p:p.read_bytes() for p in originals},originals)
                docx.write_bytes(b'two');v2.native_qa(plan,docx,scratch)
                self.assertEqual(run.call_count,2)
                (root/'scripts/validate_word_native.ps1').write_text('validator changed')
                v2.native_qa(plan,docx,scratch);self.assertEqual(run.call_count,3)
                plan['review_notes']=['changed'];v2.native_qa(plan,docx,scratch)
                self.assertEqual(run.call_count,4)
                docx.write_bytes(b'three')
                run.side_effect=lambda *a,**k:SimpleNamespace(returncode=1,stdout='',stderr='failed COM')
                failed=v2.native_qa(plan,docx,scratch)
                self.assertEqual(failed['status'],'fail');self.assertIsNone(failed['word_pages'])
                self.assertFalse((scratch/'validation-status.json').exists())

    def test_visual_review_is_fresh_and_binds_both_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            docx=Path(tmp)/'resume.docx';pdf=Path(tmp)/'resume.pdf'
            docx.write_bytes(b'docx');pdf.write_bytes(b'pdf')
            request={'request_id':'new','sha256':digest(docx),'pdf_sha256':digest(pdf)}
            check_decision(request,{**request,'approved':True},docx,pdf)
            with self.assertRaises(ValueError):check_decision(request,{**request,'request_id':'stale','approved':True},docx,pdf)
            pdf.write_bytes(b'changed')
            with self.assertRaises(ValueError):check_decision(request,{**request,'approved':True},docx,pdf)

    def test_review_wait_is_excluded_from_active_and_parent_phase(self):
        with perf.batch() as metrics:
            before=metrics.snapshot()
            with perf.phase('tracker_sync'):
                with perf.phase('review_wait'):
                    import time;time.sleep(.01)
            result=metrics.delta(before)
            self.assertGreater(result['review_wait_seconds'],.005)
            self.assertLess(result['phases_seconds']['tracker_sync'],.005)
            self.assertAlmostEqual(result['wall_seconds']-result['review_wait_seconds'],result['active_seconds'],places=3)


if __name__=='__main__':unittest.main()
