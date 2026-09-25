"""Regression tests for the evidence-first resume workflow."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gecko_v2 as v2


class GeckoV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.listing = v2.ROOT / "input/job-descriptions/Vitality-Medical+b1e13fda0b6ba9cb.md"
        cls.plan = v2.create_plan(cls.listing)

    def test_plan_precedes_generation_and_classifies_requirements(self):
        plan = self.plan
        self.assertEqual(plan["version"], 2)
        self.assertTrue(plan["requirements"]["required_skills"])
        self.assertTrue(plan["requirements"]["preferred_skills"])
        self.assertTrue(plan["requirements"]["responsibilities"])
        self.assertTrue(plan["requirements"]["tools"])
        self.assertTrue(plan["requirements"]["seniority_signals"])
        self.assertTrue(plan["requirements"]["industry_terminology"])
        self.assertTrue(plan["requirements"]["ats_keywords"])
        self.assertTrue(any(r["status"] == "gap" for r in plan["requirements"]["responsibilities"]))
        v2.verify_plan(plan)

    def test_resume_filename_includes_safe_title_and_keeps_number_last(self):
        self.assertEqual(
            v2.resume_filename("Acme / West", "Director, SEO / Growth: US?", "abc123"),
            "Dave-Call+Acme-West+Director,-SEO-Growth-US+abc123.docx",
        )
        self.assertTrue(v2.resume_filename("Acme", "Very Long Title " * 20, "abc123").endswith("+abc123.docx"))

    def test_changed_evidence_and_unsupported_skill_are_rejected(self):
        tampered = json.loads(json.dumps(self.plan))
        tampered["evidence"][0]["quote"] += " Invented result."
        with self.assertRaisesRegex(ValueError, "Unsupported or altered evidence"):
            v2.verify_plan(tampered)
        tampered = json.loads(json.dumps(self.plan))
        tampered["resume"]["skills"].append("Kubernetes")
        with self.assertRaisesRegex(ValueError, "Unsupported skill"):
            v2.verify_plan(tampered)

    def test_generated_docx_keeps_source_claims_and_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resume.docx"
            v2.make_resume(self.plan, path)
            self.assertEqual(v2.inspect_docx(self.plan, path), [])
            from docx import Document
            doc = Document(path)
            bullet = next(p for p in doc.paragraphs if p.style.name == "List Bullet")
            bullet.text += " Unsupported metric $999M."
            doc.save(path)
            self.assertIn("Resume bullets differ from the source-backed tailoring plan.", v2.inspect_docx(self.plan, path))

    def test_native_word_failure_blocks_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "resume.docx"
            v2.make_resume(self.plan, docx)
            with patch.object(v2.subprocess, "run") as run:
                run.return_value.returncode = 1
                run.return_value.stderr = "Word bridge unavailable"
                run.return_value.stdout = ""
                report = v2.native_qa(self.plan, docx, Path(tmp))
            self.assertEqual(run.call_args.kwargs["creationflags"], v2.windows_creationflags())
            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("Native Word pagination" in issue for issue in report["issues"]))

    def test_relevant_metric_cannot_disappear_silently(self):
        metric = self.plan["resume"]["relevant_metric_ids"][0]
        altered = json.loads(json.dumps(self.plan))
        altered["resume"]["selected_evidence_ids"].remove(metric)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resume.docx"
            v2.make_resume(altered, path)
            self.assertTrue(any("Relevant quantified accomplishment omitted" in issue
                                for issue in v2.inspect_docx(altered, path)))

    def test_reads_updated_master_docx_instead_of_cached_content(self):
        from docx import Document
        with tempfile.TemporaryDirectory() as tmp:
            master = Path(tmp) / "master.docx"
            document = Document()
            document.add_paragraph("First master version")
            document.save(master)
            with patch.object(v2, "ROOT", Path(tmp)), patch.object(v2, "MASTER", master):
                first = v2.source_text()
                first_hash = v2.source_hashes()
                document.add_paragraph("New approved accomplishment")
                document.save(master)
                self.assertIn("New approved accomplishment", v2.source_text())
                self.assertNotEqual(first, v2.source_text())
                self.assertNotEqual(first_hash, v2.source_hashes())

    def test_old_pdf_and_format_reference_are_not_evidence(self):
        self.assertEqual(v2.MASTER.name, "Dave-Call-resume-9-23-26.docx")
        self.assertEqual({Path(path).as_posix() for path in self.plan["source_sha256"]},
                         {"input/master-resume/Dave-Call-resume-9-23-26.docx"})
        self.assertTrue(all(e["source"].endswith("Dave-Call-resume-9-23-26.docx")
                            for e in self.plan["evidence"]))
        self.assertNotIn("Spanish", self.plan["resume"]["contact"])
        self.assertNotIn("Spanish", self.plan["resume"]["certifications"])

    def test_project_notes_do_not_authorize_ai_tool_claims(self):
        listing = "## Required Qualifications\n- Must have hands-on Codex experience in marketing operations."
        result = v2.requirements(listing, v2.source_text(), self.plan["evidence"])
        self.assertEqual(result["tools"][0]["text"], "Codex")
        self.assertEqual(result["tools"][0]["status"], "gap")
        self.assertEqual(result["required_skills"][0]["status"], "gap")


if __name__ == "__main__":
    unittest.main()
