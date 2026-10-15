"""The scouting reader must use the current master archive for evidence."""

import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import resume_evidence
from resume_evidence import extract_resume_text


class ResumeEvidenceTests(unittest.TestCase):
    def test_reads_updated_text_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "master-resume-v2.txt"
            path.write_text("First approved fact\nApproved tool\n", encoding="utf-8")
            with patch.object(resume_evidence, "MASTER_RESUME", path):
                self.assertIn("Approved tool", extract_resume_text(path))
                path.write_text(path.read_text(encoding="utf-8") + "Updated accomplishment\n", encoding="utf-8")
                self.assertIn("Updated accomplishment", extract_resume_text(path))

    def test_rejects_same_named_file_outside_canonical_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            impostor = Path(tmp) / "master-resume-v2.txt"
            impostor.write_text("Unverified fact", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "current master resume"):
                extract_resume_text(impostor)

    def test_missing_and_empty_master_fail_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            master = Path(tmp) / "master-resume-v2.txt"
            with patch.object(resume_evidence, "MASTER_RESUME", master):
                with self.assertRaisesRegex(OSError, "missing or unreadable"):
                    extract_resume_text(master)
                master.write_text("  \n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "is empty"):
                    extract_resume_text(master)

    def test_rejects_old_pdf_as_evidence(self):
        with self.assertRaisesRegex(ValueError, "must come from"):
            extract_resume_text("input/master-resume/dcall-resume-3-15-26.pdf")

    def test_rejects_old_docx_as_evidence(self):
        with self.assertRaisesRegex(ValueError, "must come from"):
            extract_resume_text("input/master-resume/Dave-Call-resume-9-23-26.docx")


if __name__ == "__main__":
    unittest.main()
