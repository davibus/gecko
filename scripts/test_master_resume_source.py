"""Canonical source routing, V2 archive parsing, and no-fallback regressions."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import gecko_v2 as v2

sys.path.insert(0, str(v2.ROOT / "job-scout"))
import candidate_profile
import resume_evidence
import scout


class MasterResumeSourceTests(unittest.TestCase):
    def test_canonical_jobs_use_user_confirmed_dates(self):
        jobs = v2.master_jobs()
        travelpass = next(job for job in jobs if "TravelPass" in job["company"])
        intercon = next(job for job in jobs if "Intercon" in job["company"])
        self.assertEqual(v2.employment_dates(travelpass), "Aug 2021–Apr 2022")
        self.assertEqual(v2.employment_dates(intercon), "Feb 2018–Feb 2020")

    def test_all_runtime_sources_and_project_config_agree(self):
        expected = v2.ROOT / "input/master-resume/master-resume-v4.docx"
        for source in (v2.MASTER, candidate_profile.MASTER_RESUME,
                       resume_evidence.MASTER_RESUME, scout.MASTER_RESUME):
            self.assertEqual(source.resolve(), expected.resolve())
        config = json.loads((v2.ROOT / "project.json").read_text(encoding="utf-8-sig"))
        self.assertEqual((v2.ROOT / config["master_resume"]).resolve(), expected.resolve())
        self.assertIn("input/master-resume/master-resume-v4.docx",
                      (v2.ROOT / "scripts/gecko_daily.py").read_text(encoding="utf-8-sig"))

    def test_active_instructions_name_the_new_source(self):
        for relative in ("AGENTS.md", "GECKO_SYSTEM.md", ".cursor/rules/gecko.mdc",
                         "README.md", "docs/workflow.md", "job-scout/README.md",
                         "prompts/use-gecko.md", "templates/resume-format.md",
                         "openclaw/application-answers.md"):
            with self.subTest(file=relative):
                text = (v2.ROOT / relative).read_text(encoding="utf-8-sig")
                self.assertIn("master-resume-v4.docx", text)
                self.assertNotIn("Dave-Call-" + "Resume.txt", text)

    def test_legacy_source_plan_rejected_even_with_matching_content_hash(self):
        old_key = "input/master-resume/" + "Dave-Call-" + "Resume.txt"
        digest = hashlib.sha256(v2.MASTER.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "rebuild the tailoring plan"):
            v2.verify_plan({"version": 3, "source_sha256": {old_key: digest}})

    def test_missing_new_source_does_not_use_existing_old_txt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            canonical = root / "input/master-resume/master-resume-v4.docx"
            canonical.parent.mkdir(parents=True)
            legacy = canonical.parent / ("Dave-Call-" + "Resume.txt")
            legacy.write_text("Old approved facts must not be a fallback", encoding="utf-8")
            with patch.object(v2, "MASTER", canonical):
                with self.assertRaisesRegex(OSError, "missing or unreadable"):
                    v2.source_text()
                with self.assertRaisesRegex(FileNotFoundError, "Required Gecko master"):
                    v2.validate_required_sources()
            with patch.object(resume_evidence, "MASTER_RESUME", canonical):
                with self.assertRaisesRegex(ValueError, "current master resume"):
                    resume_evidence.extract_resume_text(legacy)

    def test_mixed_archive_merges_duplicates_without_cross_role_bullets(self):
        lines = [
            "Digital Marketing Manager\tAugust 2021 to April 2022",
            "TravelPass Group - South Jordan, UT",
            "• Managed search campaigns with disciplined budget oversight.",
            "• Analyst | Acme",
            "• Provo, UT | January 2020 - July 2021",
            "• Built accurate weekly reporting for multiple marketing channels.",
            "• Digital Marketing Manager | TravelPass Group / Reservation Counter",
            "• South Jordan, UT | August 2021 - April 2022",
            "• • Automated keyword creation with Python for search campaigns.",
            "EDUCATION, ENTREPRENEURSHIP & RECOGNITION",
            "• A later education fact must not become an employment bullet.",
        ]
        jobs = v2._mixed_archive_jobs(lines)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(len(jobs[0]["bullets"]), 2)
        self.assertEqual(len(jobs[1]["bullets"]), 1)
        self.assertTrue(jobs[0]["bullets"][1].startswith("Automated"))
        self.assertNotIn("weekly reporting", " ".join(jobs[0]["bullets"]))

    def test_conflicting_duplicate_dates_stop_generation(self):
        lines = ["Manager\tAugust 2021 to April 2022", "Acme - Provo, UT",
                 "• Manager | Acme", "• Provo, UT | March 2021 - April 2022"]
        with self.assertRaisesRegex(ValueError, "Conflicting employment facts.*Acme"):
            v2._mixed_archive_jobs(lines)

    def test_conflicting_duplicate_locations_stop_generation(self):
        lines = ["Manager\tAugust 2021 to April 2022", "Acme - Provo, UT",
                 "• Manager | Acme", "• Orem, UT | August 2021 - April 2022"]
        with self.assertRaisesRegex(ValueError, "Conflicting employment facts.*Acme"):
            v2._mixed_archive_jobs(lines)

    def test_abbreviated_dates_and_dash_headings_are_source_preserved(self):
        lines = ["Marketing Manager - Acme - Provo, UT\tJan 2020 – June 2024",
                 "• Built verified weekly reporting for marketing channels."]
        jobs = v2._mixed_archive_jobs(lines)
        self.assertEqual(jobs[0]["title"], "Marketing Manager")
        self.assertEqual(jobs[0]["dates"], "January 2020 - June 2024")

    def test_incomplete_heading_stops_instead_of_omitting_role(self):
        lines = ["Intercon Inc\tFeb 2018 - Feb 2020"]
        with self.assertRaisesRegex(ValueError, "Incomplete work-history heading.*Intercon"):
            v2._mixed_archive_jobs(lines)

    def test_user_approved_company_only_heading_does_not_invent_title(self):
        jobs = v2._mixed_archive_jobs(["Intercon Inc - Salt Lake City, UT\tFeb 2018 - Feb 2020"])
        self.assertEqual(jobs[0]["title"], "")
        self.assertEqual(v2.employment_heading(jobs[0]), "Intercon Inc - Salt Lake City, UT")

    def test_employer_punctuation_does_not_hide_conflicting_dates(self):
        lines = ["Analyst - 1-800-Contacts - Draper, UT\tNov 2022 – June 2024",
                 "Analyst | 1-800 Contacts", "Draper, UT | November 2022 - June 2026"]
        with self.assertRaisesRegex(ValueError, "Conflicting employment facts.*1-800 Contacts"):
            v2._mixed_archive_jobs(lines)

    def test_v2_identity_strips_bullet_markers_and_keeps_source_header(self):
        identity = v2.master_identity()
        lines = [line.strip() for line in v2.master_lines() if line.strip()]
        name_index = next(i for i, line in enumerate(lines) if line.casefold() == "dave call")
        self.assertEqual(identity["headline"], lines[name_index + 1])
        self.assertFalse(identity["summary"].startswith("•"))
        self.assertIn("Digital marketing", identity["summary"])


if __name__ == "__main__":
    unittest.main()
