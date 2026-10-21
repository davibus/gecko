"""Focused safety tests for the Job List validator."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

PATH = Path(__file__).with_name("validate_job_list.py")
spec = importlib.util.spec_from_file_location("validate_job_list", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def job(**updates):
    data = {"ID": "42", "Source": "indeed", "Company": "Acme", "Job Title": "Marketing Manager",
            "Apply?": "Yes", "Cost": "", "Notes": "", module.STATUS: "",
            "Job URL": "https://example.com/jobs/42", "Resume Link": ""}
    data.update(updates)
    return data


def result(**updates):
    data = {"classification": "valid", "status": "", "cost": "unverified",
            "cost_evidence": "", "reason": "loaded"}
    data.update(updates)
    return data


class JobListValidationTests(unittest.TestCase):
    def test_inserted_last_updated_column_resolves_notes_and_link_by_name(self):
        from types import SimpleNamespace
        from tracker_schema import LEGACY_SCOUT_HEADERS, resolve_headers
        names = list(LEGACY_SCOUT_HEADERS)
        tab = SimpleNamespace(header_values=names, headers=resolve_headers(names))
        tracker = Mock()
        tracker.tab.return_value = tab
        self.assertIs(module.schema(tracker, verify_title=False), tab)
        self.assertEqual(tab.headers['Last Updated'], 9)
        self.assertEqual(tab.headers['Notes'], 10)
        self.assertEqual(tab.headers['Job URL'], 17)
        self.assertEqual(tab.headers['Resume Link'], 18)

    def test_valid_job_url_requires_identity(self):
        page = "<h1>Marketing Manager</h1><p>Acme is hiring</p>"
        check = module.CheckResult("exists", "https://example.com/jobs/42",
                                   "https://example.com/jobs/42", "loaded", 200, page)
        with patch.object(module, "check_job_url", return_value=check):
            self.assertEqual(module.inspect(2, job())["classification"], "valid")

    def test_confirmed_404_and_410(self):
        for code in (404, 410):
            # The shared fetcher marks HTTPError responses as unknown; the
            # validator still recognizes definitive 404/410 status codes.
            check = module.CheckResult("unknown", "https://example.com/jobs/42",
                                       http_status=code, reason=f"HTTP {code}")
            with patch.object(module, "check_job_url", return_value=check):
                self.assertEqual(module.inspect(2, job())["classification"], "invalid")

    def test_inaccessible_and_challenge_are_review(self):
        for code, page in ((403, ""), (429, ""), (200, "Captcha verify you are human")):
            check = module.CheckResult("unknown", "https://example.com/jobs/42",
                                       http_status=code, content=page, reason="restricted")
            with patch.object(module, "check_job_url", return_value=check):
                self.assertEqual(module.inspect(2, job())["classification"], "needs_review")

    def test_unrelated_redirect_is_review(self):
        check = module.CheckResult("exists", "https://example.com/jobs/42",
                                   "https://example.com/", "loaded", 200, "<h1>Home</h1>")
        with patch.object(module, "check_job_url", return_value=check):
            self.assertEqual(module.inspect(2, job())["classification"], "needs_review")

    def test_indeed_labels(self):
        for label in ("Apply Now", "Apply on Company Website", "Apply on Indeed",
                      "Easily Apply", "Already applied"):
            self.assertEqual(module.indeed_status(f"<button>{label}</button>"), label)
        self.assertEqual(module.indeed_status("This job has expired on Indeed"), "Expired")

    def test_paid_free_optional_unverified(self):
        self.assertEqual(module.cost_evidence("A mandatory application fee of $25 is required")[0], "paid")
        self.assertEqual(module.cost_evidence("Premium membership is optional. Application fee of $25 for upgrade")[0], "unverified")
        self.assertEqual(module.cost_evidence("No application fee is required")[0], "free")
        self.assertEqual(module.cost_evidence("Please submit your application")[0], "unverified")

    def test_eligibility_and_manual_rejection(self):
        writes, _ = module.plan(job(), result(status="Apply on Company Website"), {}, "")
        self.assertEqual(writes["Apply?"], "No")
        writes, _ = module.plan(job(), result(status="Apply Now"), {}, "x")
        self.assertEqual(writes["Apply?"], "No")
        writes, _ = module.plan(job(**{"Notes": "rejected"}), result(status="Expired"), {}, "")
        self.assertNotIn("Apply?", writes)
        writes, _ = module.plan(job(), result(status="Apply Now"), {}, "")
        self.assertEqual(writes["Apply?"], "No")

    def test_blank_cost_does_not_disqualify_and_free_is_not_written(self):
        row = job(**{"Location": "Utah", "Work Arrangement": "On-site"})
        writes, _ = module.plan(row, result(status="Apply Now", cost="unverified"), {}, "")
        self.assertNotIn("Apply?", writes)
        self.assertNotIn("Cost", writes)
        writes, _ = module.plan(row, result(status="Apply Now", cost="free"), {}, "")
        self.assertNotIn("Cost", writes)
        writes, _ = module.plan(row, result(status="Apply Now", cost="paid"), {}, "")
        self.assertEqual(writes["Cost"], "x")
        self.assertEqual(writes["Apply?"], "No")

    def test_existing_status_must_be_confirmed(self):
        writes, _ = module.plan(job(**{module.STATUS: "Applied"}), result(), {}, "")
        self.assertEqual(writes["Apply?"], "No")

    def test_formula_cost_effective_x_blocks_eligibility_without_replacement(self):
        row = job(**{"Cost": '=IF(REGEXMATCH(LOWER(P2), "jooble"), "x", "")'})
        writes, _ = module.plan(row, result(), {}, "x")
        self.assertEqual(writes["Apply?"], "No")
        self.assertNotIn("Cost", writes)

    def test_note_preserves_manual_text(self):
        writes, _ = module.plan(job(**{"Notes": "Call recruiter"}),
                                result(classification="invalid"), {}, "")
        self.assertEqual(writes["Notes"], "Call recruiter\nInvalid Link")
        self.assertEqual(writes["Job URL"], "")

    def test_resume_link_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resume.docx"
            path.write_bytes(b"docx")
            with patch.object(module, "verified_resume_uri_target", return_value=path.as_uri()):
                writes, _ = module.plan(job(**{"Resume Link": path.as_uri()}), result(), {}, "")
                self.assertEqual(writes["Resume Link"], "Acme - Marketing Manager")
        writes, warnings = module.plan(job(), result(), {}, "")
        self.assertNotIn("Resume Link", writes)
        self.assertIn("Resume Link Missing", warnings)
        with patch.object(module, "verified_resume_uri_target", side_effect=ValueError("missing file")):
            writes, warnings = module.plan(job(**{"Resume Link": "file:///C:/missing.docx"}),
                                            result(), {}, "")
            self.assertNotIn("Resume Link", writes)
            self.assertIn("Existing resume link is broken; preserved", warnings)

    def test_checkpoint_replace_and_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            module.save_json(path, {"rows": {"42": {"status": "valid"}}})
            self.assertTrue(path.is_file())
            module.save_json(path, {"rows": {"42": {"status": "invalid"}}})
            self.assertIn("invalid", path.read_text(encoding="utf-8"))
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_red_formatting_is_scoped_and_idempotent(self):
        tracker = Mock()
        tracker.config.spreadsheet_id = "sheet-id"
        tab = Mock(sheet_id=17, grid_rows=100)
        old = {"properties": {"sheetId": 17, "title": module.TAB},
               "conditionalFormats": [{"booleanRule": {"condition": {"type": "TEXT_EQ"}}}]}
        calls = 0
        def metadata():
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"sheets": [old]}
            added = tracker.api.batchUpdate.call_args.kwargs["body"]["requests"][0]
            rule = added["addConditionalFormatRule"]["rule"]
            return {"sheets": [{**old, "conditionalFormats": [rule, *old["conditionalFormats"]]}]}
        tracker.api.get.return_value.execute.side_effect = metadata
        tab.headers = {"Apply?": 5, "Cost": 8, module.STATUS: 11, "Notes": 10}
        module.ensure_red_rule(tracker, tab)
        request = tracker.api.batchUpdate.call_args.kwargs["body"]["requests"][0]
        coverage = request["addConditionalFormatRule"]["rule"]["ranges"][0]
        self.assertEqual((coverage["startColumnIndex"], coverage["endColumnIndex"]), (0, 5))
        self.assertEqual(request["addConditionalFormatRule"]["index"], 0)
        rule_formula = request["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["values"][0]["userEnteredValue"]
        self.assertIn('$K2', rule_formula)
        self.assertIn('$J2', rule_formula)
        self.assertNotIn('$I2', rule_formula)

    def test_interrupted_run_reuses_checkpoint_and_changed_url_rechecks(self):
        with tempfile.TemporaryDirectory() as directory:
            row = job()
            tab = Mock(sheet_id=17, header_values=tuple(row), headers={name: i + 1 for i, name in enumerate(row)},
                       rows=[(2, row), (3, job(**{"ID": "", "Company": "", "Job Title": "",
                                                 "Source": "", "Job URL": "", "Apply?": "No"}))])
            tracker = Mock()
            tracker.tab.return_value = tab
            inspected = {"row": 2, "id": "42", "url": row["Job URL"],
                         "classification": "valid", "reason": "loaded", "status": "",
                         "cost": "unverified", "cost_evidence": "", "final_url": row["Job URL"]}
            with patch.object(module, "REPORT_DIR", Path(directory)), \
                 patch.object(module, "GoogleTracker", return_value=tracker), \
                 patch.object(module, "schema", return_value=tab), \
                 patch.object(module, "inspect", return_value=inspected) as check:
                first = module.run(False, 1)
                self.assertEqual(first["job_rows_scanned"], 1)
                module.run(False, 1)
                self.assertEqual(check.call_count, 1)
                row["Job URL"] = "https://example.com/jobs/43"
                module.run(False, 1)
                self.assertEqual(check.call_count, 2)


if __name__ == "__main__":
    unittest.main()
