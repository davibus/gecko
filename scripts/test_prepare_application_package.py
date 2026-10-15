"""Offline safety tests for the one-job application handoff."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("prepare_application_package.py")
spec = importlib.util.spec_from_file_location("prepare_application_package", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(bridge)


class FakeRejections:
    def __init__(self, rejected=False):
        self.rejected = rejected

    def match(self, **_):
        return object() if self.rejected else None


class FakeTracker:
    def __init__(self, rows, rejected=False):
        self.config = SimpleNamespace(scout_tab="Job List")
        self.rows = rows
        self.rejected = rejected

    def discover_workbook(self, *, required):
        return {name: {} for name in required}

    def tab(self, _):
        headers = ("ID", "Source", "Company", "Job Title", "Apply?", "Resume Created",
                   "Applied", "Cost", "Notes", "Location", "Work Arrangement", "Job URL", "Resume Link",
                   bridge.INDEED_APPLICATION_HEADER)
        return SimpleNamespace(header_values=headers, headers=bridge.resolve_headers(headers),
                               rows=self.rows)

    def rejected_jobs_index(self):
        return FakeRejections(self.rejected)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        resume_dir = self.root / "output" / "resumes"
        resume_dir.mkdir(parents=True)
        self.resume = resume_dir / "Dave-Call+Acme+Product-Manager+scout-42.docx"
        self.resume.write_bytes(b"DOCX fixture")
        descriptions = self.root / "input" / "job-descriptions"
        descriptions.mkdir(parents=True)
        (descriptions / "Acme+scout-42.md").write_text(
            "# Product Manager — Acme\n\n- **Scout ID:** 42\n- **Job Number:** `scout-42`\n"
            "- **Company:** Acme\n- **Job Title:** Product Manager\n", encoding="utf-8")
        self.row = {"Scout ID": "42", "Source": "Company", "Company": "Acme",
                    "Job Title": "Product Manager", "Apply?": "Yes", "Resume Created": "X",
                    "Applied": "", "Cost": "", "Notes": "", "Location": "Utah",
                    "Work Arrangement": "On-site", "Job URL":
                    "https://jobs.acme.example/roles/42", "Resume Link": self.resume.as_uri(),
                    bridge.INDEED_APPLICATION_HEADER: ""}

    def run_prepare(self, *, row=None, rows=None, rejected=False, approved="42",
                    company_url=None, job_id="42"):
        tracker = FakeTracker(rows or [(7, row or self.row)], rejected)
        return bridge.prepare(tracker, job_id=job_id, physical_row=None,
                              approved_job_id=approved, company_url=company_url,
                              root=self.root,
                              url_verifier=lambda url, company, title: url)

    def assert_blocked(self, code, **kwargs):
        with self.assertRaises(bridge.PackageBlocked) as caught:
            self.run_prepare(**kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertFalse((self.root / "openclaw").exists())

    def test_success_one_package_and_sanitized_audit(self):
        package = self.run_prepare()
        self.assertEqual(package["job_id"], "42")
        self.assertEqual(package["verified_resume_file_path"], str(self.resume))
        paths = bridge.save_package(package, root=self.root)
        self.assertTrue(all(path.is_file() for path in paths))
        self.assertNotIn("https://", paths[1].read_text(encoding="utf-8"))
        self.assertNotIn("Resume Link", paths[1].read_text(encoding="utf-8"))

    def test_rejected_history(self):
        self.assert_blocked("permanently_rejected", rejected=True)

    def test_expired(self):
        self.assert_blocked("job_expired", row={**self.row,
            bridge.INDEED_APPLICATION_HEADER: "Expired", "Apply?": "No"})

    def test_duplicate(self):
        other = {**self.row, "Scout ID": "43"}
        self.assert_blocked("duplicate_job", rows=[(7, self.row), (8, other)])

    def test_paid(self):
        self.assert_blocked("paid_or_excluded_job", row={**self.row, "Cost": " X "})

    def test_already_applied(self):
        self.assert_blocked("already_applied", row={**self.row, "Applied": "X"})

    def test_missing_resume(self):
        self.resume.unlink()
        self.assert_blocked("missing_or_invalid_resume")

    def test_invalid_url(self):
        with self.assertRaises(bridge.PackageBlocked) as caught:
            bridge.safe_url("javascript:alert(1)")
        self.assertEqual(caught.exception.code, "invalid_application_url")

    def test_indeed_url_is_not_company_destination(self):
        with self.assertRaises(bridge.PackageBlocked) as caught:
            bridge.verify_application_url("https://www.indeed.com/viewjob?jk=abc", "Acme", "Product Manager")
        self.assertEqual(caught.exception.code, "company_application_url_required")

    def test_company_url_must_match_job_page(self):
        result = SimpleNamespace(final_url="https://careers.acme.com/jobs/42", status="exists",
                                 http_status=200, content="<html>Unrelated role</html>")
        with patch.object(bridge, "check_job_url", return_value=result):
            with self.assertRaises(bridge.PackageBlocked) as caught:
                bridge.verify_application_url("https://careers.acme.com/jobs/42", "Acme", "Product Manager")
        self.assertEqual(caught.exception.code, "application_job_identity_unverified")

    def test_company_url_checker_uses_required_fetcher(self):
        url = "https://careers.acme.com/jobs/42"
        result = SimpleNamespace(final_url=url, status="exists", http_status=200,
                                 content="<html>Acme Product Manager</html>")
        with patch.object(bridge, "check_job_url", autospec=True, return_value=result) as checker:
            self.assertEqual(bridge.verify_application_url(url, "Acme", "Product Manager"), url)
        self.assertIsInstance(checker.call_args.args[1], bridge.ThrottledFetcher)

    def test_unapproved(self):
        self.assert_blocked("preparation_not_approved", approved=None)
        self.assert_blocked("approved_job_id_mismatch", approved="43")

    def test_indeed_requires_employer_destination(self):
        row = {**self.row, "Source": "Indeed",
               "Job URL": "https://www.indeed.com/viewjob?jk=abc123"}
        self.assert_blocked("indeed_job_id_mismatch", row=row)

    def test_resume_id_mismatch(self):
        wrong = self.resume.with_name("Dave-Call+Acme+Product-Manager+scout-99.docx")
        wrong.write_bytes(b"wrong")
        self.assert_blocked("resume_job_id_mismatch", row={**self.row,
            "Resume Link": wrong.as_uri()})


if __name__ == "__main__":
    unittest.main()
