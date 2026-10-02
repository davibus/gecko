"""Tests for the one-cell-only legacy resume-link repair."""

from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "job-scout"))

import google_tracker
from google_tracker import Config, Tab
import repair_resume_links as repair


HEADERS = {
    "Scout ID": 1,
    "Company": 3,
    "Job Title": 4,
    "Job URL": 16,
    "Resume Link": 17,
}


class FakeTracker:
    def __init__(self, formula_tab: Tab, displayed_tab: Tab):
        self.formula_tab = formula_tab
        self.displayed_tab = displayed_tab
        self.config = Config("sheet", Path("unused.json"), "Job Tracker", "Job Scout")

    def scout(self, *, value_render_option: str = "UNFORMATTED_VALUE") -> Tab:
        return self.formula_tab if value_render_option == "FORMULA" else self.displayed_tab


def tab(value: str, raw_value: str) -> Tab:
    data = {
        "Scout ID": 42,
        "Company": "Example Company",
        "Job Title": "Marketing Manager",
        "Job URL": "https://example.test/jobs/job-42",
        "Resume Link": value,
    }
    raw = [""] * 17
    raw[16] = raw_value
    return Tab("Job Scout", 1, dict(HEADERS), [(2, data)], 100, (), {2: tuple(raw)})


class RepairResumeLinksTests(unittest.TestCase):
    def test_plan_uses_existing_formula_target_and_as_uri(self):
        with TemporaryDirectory() as temp:
            resume_dir = Path(temp).resolve()
            resume = resume_dir / "Dave-Call+Example-Company+Marketing-Manager+job-42.docx"
            resume.write_bytes(b"docx")
            formula = f'=HYPERLINK("{resume.as_uri()}","Open Resume")'
            tracker = FakeTracker(tab(formula, formula), tab("Open Resume", "Open Resume"))
            with patch.object(repair, "RESUME_DIR", resume_dir), \
                 patch.object(google_tracker, "RESUME_DIR", resume_dir):
                inspected, found, repairs, unresolved = repair.plan_repairs(tracker)
        self.assertEqual((inspected, found, len(repairs)), (1, 1, 1))
        self.assertEqual(repairs[0].uri, resume.as_uri())
        self.assertEqual(repairs[0].source, "formula")
        self.assertEqual(unresolved, [])

    def test_ambiguous_identifier_is_left_unresolved(self):
        with TemporaryDirectory() as temp:
            resume_dir = Path(temp).resolve()
            for version in ("v2", "v3"):
                (resume_dir / f"Dave-Call+Example-Company+Marketing-Manager+{version}+job-42.docx").write_bytes(b"docx")
            tracker = FakeTracker(tab("Open Resume", "Open Resume"), tab("Open Resume", "Open Resume"))
            with patch.object(repair, "RESUME_DIR", resume_dir), \
                 patch.object(google_tracker, "RESUME_DIR", resume_dir):
                _, found, repairs, unresolved = repair.plan_repairs(tracker)
        self.assertEqual(found, 1)
        self.assertEqual(repairs, [])
        self.assertEqual(unresolved[0].row, 2)
        self.assertIn("multiple resumes", unresolved[0].reason)


if __name__ == "__main__":
    unittest.main()
