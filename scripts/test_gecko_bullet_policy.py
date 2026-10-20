"""Native page capacity, expansion, and overflow regression checks."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gecko_v2 as v2


class GeckoBulletPolicyTests(unittest.TestCase):
    def test_two_pages_alone_does_not_pass_density(self):
        from docx import Document
        from docx.shared import Inches
        import fitz
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = Document()
            doc.sections[0].bottom_margin = Inches(.5)
            doc.save(root / 'resume.docx')
            pdf = fitz.open()
            pdf.new_page(width=612, height=792)
            page = pdf.new_page(width=612, height=792)
            page.insert_text((36, 400), 'EDUCATION & CERTIFICATIONS')
            page.insert_text((36, 420), 'Degree and certifications')
            pdf.save(root / 'short.pdf')
            result = v2.page_two_density(root / 'resume.docx', root / 'short.pdf')
            self.assertGreater(result['page_two_bottom_gap_pt'], 300)
            self.assertIn('underfilled', result['density_issue'])
            page.insert_text((36, 740), 'Additional relevant education detail')
            pdf.save(root / 'full.pdf')
            result = v2.page_two_density(root / 'resume.docx', root / 'full.pdf')
            self.assertLessEqual(result['page_two_bottom_gap_pt'], 36)
            self.assertEqual(result['density_issue'], '')

    def test_underfill_expands_beyond_three_bullets(self):
        plan = {'resume': {'selected_evidence_ids': ['a', 'b', 'c']}}
        def candidates(current):
            return [eid for eid in ['d', 'e'] if eid not in current['resume']['selected_evidence_ids']]
        reports = [{'status': 'fail', 'word_pages': 2, 'pdf_pages': 2, 'page_two_bottom_gap_pt': gap}
                   for gap in (180, 90)] + [
                   {'status': 'pass', 'word_pages': 2, 'pdf_pages': 2, 'page_two_bottom_gap_pt': 20}]
        with patch.object(v2, 'make_resume'), patch.object(v2, 'native_qa', side_effect=reports), \
             patch.object(v2, '_third_bullet_fallbacks', return_value=[]), \
             patch.object(v2, '_additional_evidence', side_effect=candidates):
            result = v2.generate_two_page_resume(plan, Path('test.docx'), Path('.'))
        self.assertEqual(plan['resume']['selected_evidence_ids'], ['a', 'b', 'c', 'd', 'e'])
        self.assertEqual(result['status'], 'pass')

    def test_expansion_overflow_restores_last_two_page_content(self):
        plan = {'resume': {'selected_evidence_ids': ['a', 'b', 'c']}}
        reports = [{'status': 'fail', 'word_pages': 2, 'pdf_pages': 2, 'page_two_bottom_gap_pt': 80},
                   {'status': 'fail', 'word_pages': 3, 'pdf_pages': 3},
                   {'status': 'fail', 'word_pages': 2, 'pdf_pages': 2, 'page_two_bottom_gap_pt': 80}]
        with patch.object(v2, 'make_resume'), patch.object(v2, 'native_qa', side_effect=reports), \
             patch.object(v2, '_third_bullet_fallbacks', return_value=[]), \
             patch.object(v2, '_additional_evidence', return_value=['d']):
            result = v2.generate_two_page_resume(plan, Path('test.docx'), Path('.'))
        self.assertEqual(plan['resume']['selected_evidence_ids'], ['a', 'b', 'c'])
        self.assertEqual(result['status'], 'fail')

    def test_native_overflow_removes_only_least_relevant_third_bullets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            listing = root / "listing.md"
            listing.write_text("analytics leadership", encoding="utf-8")
            plan = {
                "listing": str(listing),
                "evidence": [
                    {"id": "a1", "job": 0, "quote": "First result"},
                    {"id": "a2", "job": 0, "quote": "Second result"},
                    {"id": "a3", "job": 0, "quote": "Analytics leadership result"},
                    {"id": "b1", "job": 1, "quote": "First result"},
                    {"id": "b2", "job": 1, "quote": "Second result"},
                    {"id": "b3", "job": 1, "quote": "Unrelated supporting result"},
                ],
                "resume": {
                    "jobs": [{}, {}],
                    "selected_evidence_ids": ["a1", "a2", "a3", "b1", "b2", "b3"],
                    "relevant_metric_ids": [],
                },
            }
            page_reports = [
                {"status": "fail", "word_pages": 3, "pdf_pages": 3},
                {"status": "fail", "word_pages": 3, "pdf_pages": 3},
                {"status": "pass", "word_pages": 2, "pdf_pages": 2},
            ]
            rendered = []

            def record_render(current_plan, _path):
                rendered.append(list(current_plan["resume"]["selected_evidence_ids"]))

            with patch.object(v2, "make_resume", side_effect=record_render), \
                 patch.object(v2, "native_qa", side_effect=page_reports):
                report = v2.generate_two_page_resume(plan, root / "resume.docx", root)

            self.assertEqual(report["status"], "pass")
            self.assertEqual(rendered[0], ["a1", "a2", "a3", "b1", "b2", "b3"])
            self.assertNotIn("b3", rendered[1])
            self.assertEqual(plan["resume"]["selected_evidence_ids"], ["a1", "a2", "b1", "b2"])
            self.assertEqual(len(rendered), 3)


if __name__ == "__main__":
    unittest.main()
