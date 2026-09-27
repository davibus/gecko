"""The scouting reader must use the current master archive for evidence."""

import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from resume_evidence import extract_resume_text


class ResumeEvidenceTests(unittest.TestCase):
    def test_reads_updated_text_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Dave-Call-Resume.txt"
            path.write_text("First approved fact\nApproved tool\n", encoding="utf-8")
            self.assertIn("Approved tool", extract_resume_text(path))
            path.write_text(path.read_text(encoding="utf-8") + "Updated accomplishment\n", encoding="utf-8")
            self.assertIn("Updated accomplishment", extract_resume_text(path))

    def test_rejects_old_pdf_as_evidence(self):
        with self.assertRaisesRegex(ValueError, "must come from"):
            extract_resume_text("input/master-resume/dcall-resume-3-15-26.pdf")

    def test_rejects_old_docx_as_evidence(self):
        with self.assertRaisesRegex(ValueError, "must come from"):
            extract_resume_text("input/master-resume/Dave-Call-resume-9-23-26.docx")


if __name__ == "__main__":
    unittest.main()
