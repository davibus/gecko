"""Direct Google tracker contract tests without touching the live spreadsheet."""

from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from google_tracker import Config, GoogleTracker, job_key
from models import RawListing
from normalize import normalize

APP = ["Resume #", "Company", "Job Title", "Pay", "Job Number", "Match Score",
       "Job Link", "Resume Link", "Date Created", "Applied", "Contacted", "Source",
       "Date Found", "Status"]
SCOUT = ["Scout ID", "Source", "Company", "Job Title", "Gecko Status", "Apply?",
         "Resume Created", "Applied", "Contacted", "Match Score", "Evidence Confidence",
         "Match Status", "Location", "Work Arrangement", "Employment Type", "Salary",
         "Date Posted", "Date Found", "Last Seen", "Job URL", "Enrichment URL",
         "Resume Link", "URL Status", "Authoritative URL"]


class Call:
    def __init__(self, function):
        self.function = function

    def execute(self):
        return self.function()


class FakeSheets:
    def __init__(self):
        self.data = {
            "Job Tracker": [APP, [7, "Existing", "Role", "", "job-123", "70/100",
                                  "https://example.test/job", "", "09/01/2026", "TRUE", "called", "", "", ""]],
            "Job Scout": [SCOUT, [42, "test", "Existing", "Role", "New", "Yes", "", "", "",
                                  75, .8, "Near Match", "Remote", "remote", "full-time", "", "", "", "",
                                  "https://example.test/job", "", "", "Not checked", ""]],
        }
        self.writes = []
        self.structural = []
        self.fail = False

    def spreadsheets(self):
        return self

    def values(self):
        return FakeValues(self)

    def get(self, **_kwargs):
        def respond():
            if self.fail:
                raise OSError("simulated Google outage")
            return {"sheets": [{"properties": {"title": title, "sheetId": index,
                                               "gridProperties": {"rowCount": 1000}}}
                               for index, title in enumerate(self.data)]}
        return Call(respond)

    def batchUpdate(self, **kwargs):
        return Call(lambda: self.structural.extend(kwargs["body"]["requests"]) or {})


class FakeValues:
    def __init__(self, parent):
        self.parent = parent

    def get(self, **kwargs):
        def respond():
            if self.parent.fail:
                raise OSError("simulated Google outage")
            title = kwargs["range"].split("'!")[0].strip("'")
            return {"values": [list(row) for row in self.parent.data[title]]}
        return Call(respond)

    def batchUpdate(self, **kwargs):
        def respond():
            if self.parent.fail:
                raise OSError("simulated Google outage")
            for entry in kwargs["body"]["data"]:
                match = re.fullmatch(r"'([^']+)'!([A-Z]+)(\d+)", entry["range"])
                title, letters, row_text = match.groups()
                column = 0
                for letter in letters:
                    column = column * 26 + ord(letter) - 64
                row_number = int(row_text)
                while len(self.parent.data[title]) < row_number:
                    self.parent.data[title].append([])
                row = self.parent.data[title][row_number - 1]
                while len(row) < column:
                    row.append("")
                row[column - 1] = entry["values"][0][0]
                self.parent.writes.append((title, row_number, letters))
            return {}
        return Call(respond)


class GoogleTrackerTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSheets()
        self.tracker = GoogleTracker(Config("test-id", Path("unused.json"), "Job Tracker", "Job Scout"), self.fake)

    def test_read_find_update_managed_cells_without_overwriting_manual_or_duplicates(self):
        self.fake.data["Job Tracker"][1][3] = "Manual pay"
        self.assertEqual(self.tracker.find_application(" job-123 ")[0], 2)
        row, created = self.tracker.upsert_application({
            "Job Number": "job-123", "Company": "Existing", "Match Score": "82/100",
            "Resume Link": "file:///new-resume.docx", "Status": "resume-created",
            "Applied": "FALSE", "Contacted": "overwrite attempt", "Pay": "",
            "Date Created": "09/23/2026",
        })
        self.assertEqual((row, created), (2, False))
        _, again = self.tracker.upsert_application({"Job Number": "job-123", "Match Score": "82/100"})
        self.assertFalse(again)
        self.assertEqual(len(self.fake.data["Job Tracker"]), 2)
        stored = dict(zip(APP, self.fake.data["Job Tracker"][1]))
        self.assertEqual(stored["Match Score"], "82/100")
        self.assertEqual(stored["Applied"], "TRUE")
        self.assertEqual(stored["Contacted"], "called")
        self.assertEqual(stored["Date Created"], "09/01/2026")
        self.assertEqual(stored["Pay"], "Manual pay")
        self.assertFalse(any(letter in ("J", "K") for title, _, letter in self.fake.writes if title == "Job Tracker"))
        self.assertEqual(self.fake.structural, [])

    def test_new_job_gets_next_index_and_native_checkboxes(self):
        row, created = self.tracker.upsert_application({"Job Number": "new-job", "Company": "New",
                                                        "Match Score": "88/100"})
        self.assertEqual((row, created), (3, True))
        self.assertEqual(self.fake.data["Job Tracker"][2][0], 8)
        rules = [request["setDataValidation"]["rule"]["condition"]["type"]
                 for request in self.fake.structural if "setDataValidation" in request]
        self.assertEqual(rules, ["BOOLEAN", "BOOLEAN"])

    def test_existing_application_status_is_not_downgraded(self):
        status_column = APP.index("Status")
        self.fake.data["Job Tracker"][1][status_column] = "Applied"
        self.tracker.upsert_application({"Job Number": "job-123", "Status": "resume-created",
                                         "Match Score": "84/100"})
        self.assertEqual(self.fake.data["Job Tracker"][1][status_column], "Applied")

    def test_scout_mark_preserves_apply_and_manual_fields(self):
        self.tracker.mark_scout_resume(42, "file:///resume.docx")
        stored = dict(zip(SCOUT, self.fake.data["Job Scout"][1]))
        self.assertEqual(stored["Apply?"], "Yes")
        self.assertEqual(stored["Resume Created"], "X")
        self.assertEqual(stored["Resume Link"], "file:///resume.docx")

    def test_marking_resume_does_not_downgrade_applied_status(self):
        self.fake.data["Job Scout"][1][4] = "Applied"
        self.tracker.mark_scout_resume(42, "file:///resume.docx")
        stored = dict(zip(SCOUT, self.fake.data["Job Scout"][1]))
        self.assertEqual(stored["Gecko Status"], "Applied")
        self.assertEqual(stored["Resume Created"], "X")

    def test_google_failure_never_falls_back_to_a_local_tracker(self):
        self.fake.fail = True
        with self.assertRaisesRegex(RuntimeError, "Cannot read Google Sheets"):
            self.tracker.find_application("job-123")

    def test_legacy_numeric_job_id_uses_exact_resume_filename(self):
        row = {"Job Number": -1.76537430016583e18,
               "Resume Link": "file:///resumes/Dave-Call+Unicity+-1765374300165839452.docx"}
        self.assertEqual(job_key(row), "-1765374300165839452")

    def test_scout_upsert_preserves_manual_fields_and_does_not_duplicate(self):
        job = normalize(RawListing(source="test", source_job_id="42",
                                   url="https://example.test/job", title="Role",
                                   company="Existing", description="Manage campaigns"))
        job.id = 42
        job.status = "selected"
        self.tracker.upsert_scout([job])
        self.assertEqual(len(self.fake.data["Job Scout"]), 2)
        row = dict(zip(SCOUT, self.fake.data["Job Scout"][1]))
        self.assertEqual(row["Gecko Status"], "Selected")
        self.assertEqual(row["Apply?"], "Yes")

    def test_highlight_scout_found_on_colors_only_matching_id_cells(self):
        self.fake.data["Job Scout"][1][SCOUT.index("Date Found")] = "2026-09-25"
        older = list(self.fake.data["Job Scout"][1])
        older[0] = 43
        older[SCOUT.index("Date Found")] = "2026-09-24"
        self.fake.data["Job Scout"].append(older)
        today = list(older)
        today[0] = 44
        today[SCOUT.index("Date Found")] = "2026-09-25"
        self.fake.data["Job Scout"].append(today)

        self.assertEqual(self.tracker.highlight_scout_found_on("2026-09-25"), 2)
        highlights = [request["repeatCell"] for request in self.fake.structural]
        self.assertEqual([item["range"]["startRowIndex"] for item in highlights], [1, 3])
        self.assertTrue(all(item["range"]["startColumnIndex"] == 0 and
                            item["range"]["endColumnIndex"] == 1 and
                            item["fields"] == "userEnteredFormat.backgroundColor"
                            for item in highlights))
        self.assertEqual(self.fake.writes, [])

    def test_dead_scout_clear_touches_only_managed_values(self):
        self.fake.data["Job Scout"][1][5] = ""
        self.fake.data["Job Scout"].append([43, "test", "Protected", "Role", "New", "Yes"])
        removed = self.tracker.remove_dead_scout({42, 43})
        self.assertEqual(removed, {42})
        self.assertEqual(self.fake.data["Job Scout"][1][0], "")
        self.assertEqual(self.fake.data["Job Scout"][2][0], 43)
        self.assertEqual(self.fake.data["Job Tracker"][1][9:11], ["TRUE", "called"])
        self.assertEqual(self.fake.structural, [])


if __name__ == "__main__":
    unittest.main()
