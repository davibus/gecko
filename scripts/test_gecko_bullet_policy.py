"""Focused tests for Gecko's three-bullet-first pagination policy."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gecko_v2 as v2


class GeckoBulletPolicyTests(unittest.TestCase):
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
