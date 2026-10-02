"""Direct Google tracker contract tests without touching the live spreadsheet."""

from __future__ import annotations

from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import google_tracker
from google_tracker import (
    Config, GoogleTracker, NEW_SCOUT_ID_COLOR, SCOUT_FIELDS, apply_value, job_key,
)
from models import RawListing
from normalize import normalize

APP = ["Resume #", "Company", "Job Title", "Pay", "Job Number",
       "Job Link", "Resume Link", "Date Created", "Applied", "Contacted", "Source",
       "Date Found", "Status"]
SCOUT = ["ID", "Source", "Company", "Job Title", "Status", "Apply?",
         "Resume Created", "Applied", "Cost", "Notes", "Response", "Location",
         "Work Arrangement", "Employment Type", "Salary", "Job URL", "Resume Link",
         "Date Posted", "Date Found", "Last Seen"]


class Call:
    def __init__(self, function):
        self.function = function

    def execute(self):
        return self.function()


class FakeSheets:
    def __init__(self):
        self.data = {
            "Job Tracker": [list(APP), [7, "Existing", "Role", "", "job-123",
                                  "https://example.test/job", "", "09/01/2026", "TRUE", "called", "", "", ""]],
            "Job Scout": [list(SCOUT), [42, "test", "Existing", "Role", "New", "Yes", "", "", "", "",
                                  "", "Remote", "remote", "full-time", "",
                                  "https://example.test/job", "", "", "", ""]],
        }
        self.writes = []
        self.value_input_options = []
        self.value_batches = []
        self.structural = []
        self.formats = {}
        self.unclear_cells = set()
        self.fail = False

    def spreadsheets(self):
        return self

    def values(self):
        return FakeValues(self)

    def get(self, **kwargs):
        def respond():
            if self.fail:
                raise OSError("simulated Google outage")
            if kwargs.get("includeGridData"):
                rows = []
                for row_number in range(2, len(self.data["Job Scout"]) + 1):
                    cell = self.formats.get(row_number, {})
                    rows.append({"values": [cell]} if cell else {})
                return {"sheets": [{"data": [{"startRow": 1, "rowData": rows}]}]}
            return {"sheets": [{"properties": {"title": title, "sheetId": index,
                                               "gridProperties": {"rowCount": 1000}}}
                               for index, title in enumerate(self.data)]}
        return Call(respond)

    def batchUpdate(self, **kwargs):
        def respond():
            requests = kwargs["body"]["requests"]
            self.structural.extend(requests)
            for request in requests:
                if "deleteDimension" not in request:
                    continue
                dimension = request["deleteDimension"]["range"]
                title = list(self.data)[dimension["sheetId"]]
                if dimension["dimension"] == "ROWS":
                    del self.data[title][dimension["startIndex"]:dimension["endIndex"]]
                else:
                    for row in self.data[title]:
                        del row[dimension["startIndex"]:dimension["endIndex"]]
            return {}
        return Call(respond)


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
            self.parent.value_input_options.append(kwargs["body"]["valueInputOption"])
            self.parent.value_batches.append([
                entry["range"] for entry in kwargs["body"]["data"]
            ])
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
                if (title, row_number, letters) not in self.parent.unclear_cells:
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
            "Job Number": "job-123", "Company": "Existing",
            "Resume Link": "file:///new-resume.docx", "Status": "resume-created",
            "Applied": "FALSE", "Contacted": "overwrite attempt", "Pay": "",
            "Date Created": "09/23/2026",
        })
        self.assertEqual((row, created), (2, False))
        _, again = self.tracker.upsert_application({"Job Number": "job-123"})
        self.assertFalse(again)
        self.assertEqual(len(self.fake.data["Job Tracker"]), 2)
        stored = dict(zip(APP, self.fake.data["Job Tracker"][1]))
        self.assertEqual(stored["Applied"], "TRUE")
        self.assertEqual(stored["Contacted"], "called")
        self.assertEqual(stored["Date Created"], "09/01/2026")
        self.assertEqual(stored["Pay"], "Manual pay")
        self.assertFalse(any(letter in ("J", "K") for title, _, letter in self.fake.writes if title == "Job Tracker"))

    def test_new_job_gets_next_index_and_native_checkboxes(self):
        row, created = self.tracker.upsert_application({"Job Number": "new-job", "Company": "New"})
        self.assertEqual((row, created), (3, True))
        self.assertEqual(self.fake.data["Job Tracker"][2][0], 8)
        rules = [request["setDataValidation"]["rule"]["condition"]["type"]
                 for request in self.fake.structural if "setDataValidation" in request]
        self.assertEqual(rules, ["BOOLEAN", "BOOLEAN"])

    def test_apply_value_uses_only_normalized_location_and_work_arrangement(self):
        cases = (
            ("Salt Lake City, UT", "On-site", "Yes"),
            ("Lehi, Utah", "Hybrid", "Yes"),
            ("California", "Remote", "Yes"),
            ("Denver, CO", "Hybrid", "No"),
            ("Provo, UT", "On-site", "Yes"),
            ("Dallas, TX", "On-site", "No"),
        )
        for location, arrangement, expected in cases:
            with self.subTest(location=location, arrangement=arrangement):
                self.assertEqual(apply_value(location, arrangement), expected)

    def test_apply_value_is_case_insensitive_and_ignores_descriptive_text(self):
        self.assertEqual(apply_value("REMOTE - United States", ""), "Yes")
        self.assertEqual(apply_value("draper, utah", "HYBRID"), "Yes")
        self.assertEqual(apply_value("California", "Hybrid"), "No")

    def test_existing_application_status_is_not_downgraded(self):
        status_column = APP.index("Status")
        self.fake.data["Job Tracker"][1][status_column] = "Applied"
        self.tracker.upsert_application({"Job Number": "job-123", "Status": "resume-created"})
        self.assertEqual(self.fake.data["Job Tracker"][1][status_column], "Applied")

    def test_scout_mark_preserves_apply_and_manual_fields(self):
        self.tracker.mark_scout_resume(42, "https://drive.google.test/resume")
        stored = dict(zip(SCOUT, self.fake.data["Job Scout"][1]))
        self.assertEqual(stored["Apply?"], "Yes")
        self.assertEqual(stored["Resume Created"], "X")
        self.assertEqual(
            stored["Resume Link"],
            "https://drive.google.test/resume",
        )
        self.assertEqual(self.fake.value_input_options[-1], "RAW")
        self.assertEqual(len(self.fake.value_batches), 1)
        self.assertIn("'Job Scout'!G2", self.fake.value_batches[0])
        self.assertIn("'Job Scout'!Q2", self.fake.value_batches[0])
        self.assertEqual(
            [column for title, row, column in self.fake.writes if title == "Job Scout" and row == 2],
            ["E", "Q", "G"],
        )

    def test_local_resume_path_requires_explicit_local_mode(self):
        local_path = "C:\\Users\\DCALL\\Desktop\\gecko\\output\\resumes\\resume.docx"
        with self.assertRaisesRegex(ValueError, "explicitly allows"):
            self.tracker.mark_scout_resume(42, local_path)
        with TemporaryDirectory() as temp:
            resume_dir = Path(temp).resolve()
            resume = resume_dir / "resume.docx"
            resume.write_bytes(b"docx")
            local_uri = resume.as_uri()
            with patch.object(google_tracker, "RESUME_DIR", resume_dir):
                self.tracker.mark_scout_resume(42, local_uri, allow_local=True)
        stored = dict(zip(SCOUT, self.fake.data["Job Scout"][1]))
        self.assertEqual(stored["Resume Link"], local_uri)
        self.assertEqual(stored["Resume Created"], "X")

    def test_local_resume_uri_requires_existing_docx(self):
        with TemporaryDirectory() as temp:
            resume_dir = Path(temp).resolve()
            missing = (resume_dir / "missing.docx").as_uri()
            with patch.object(google_tracker, "RESUME_DIR", resume_dir):
                with self.assertRaisesRegex(ValueError, "missing or empty"):
                    self.tracker.mark_scout_resume(42, missing, allow_local=True)
        self.assertEqual(self.fake.writes, [])

    def test_marking_resume_does_not_downgrade_applied_status(self):
        self.fake.data["Job Scout"][1][4] = "Applied"
        self.tracker.mark_scout_resume(42, "https://drive.google.test/resume")
        stored = dict(zip(SCOUT, self.fake.data["Job Scout"][1]))
        self.assertEqual(stored["Status"], "Applied")
        self.assertEqual(stored["Resume Created"], "X")

    def test_missing_resume_link_header_fails_without_writing(self):
        self.fake.data["Job Scout"][0][SCOUT.index("Resume Link")] = ""
        with self.assertRaisesRegex(RuntimeError, "Resume Link"):
            self.tracker.mark_scout_resume(42, "https://drive.google.test/resume")
        self.assertEqual(self.fake.writes, [])

    def test_moved_resume_link_header_is_written_by_header(self):
        for row in self.fake.data["Job Scout"]:
            row[SCOUT.index("Resume Link")], row[SCOUT.index("Last Seen")] = (
                row[SCOUT.index("Last Seen")], row[SCOUT.index("Resume Link")]
            )
        self.tracker.mark_scout_resume(42, "https://drive.google.test/resume")
        self.assertIn(("Job Scout", 2, "T"), self.fake.writes)

    def test_ambiguous_renamed_id_headers_fail_clearly(self):
        self.fake.data["Job Scout"][0].append("Scout ID")
        self.fake.data["Job Scout"][1].append(999)
        with self.assertRaisesRegex(RuntimeError, "ambiguous header.*Scout ID"):
            self.tracker.scout()

    def test_scout_id_relocates_target_row_before_resume_write(self):
        self.fake.data["Job Scout"].insert(1, [99, "test", "Other", "Role"])
        row = self.tracker.mark_scout_resume(42, "https://drive.google.test/resume")
        self.assertEqual(row, 3)
        self.assertIn(("Job Scout", 3, "Q"), self.fake.writes)

    def test_manual_approval_fills_only_blank_apply_cell(self):
        self.fake.data["Job Scout"][1][SCOUT.index("Apply?")] = ""
        self.tracker.approve_manual_scout_row(2, company="Existing", title="Role")
        stored = dict(zip(SCOUT, self.fake.data["Job Scout"][1]))
        self.assertEqual(stored["Apply?"], "Yes")
        self.assertEqual([write[2] for write in self.fake.writes], ["F"])

    def test_manual_approval_overrides_no_for_verified_qualifying_row(self):
        self.fake.data["Job Scout"][1][SCOUT.index("Apply?")] = "No"
        self.tracker.approve_manual_scout_row(2, company="Existing", title="Role")
        self.assertEqual(self.fake.data["Job Scout"][1][SCOUT.index("Apply?")], "Yes")

    def test_assign_manual_scout_id_is_unique_and_preserves_existing(self):
        self.fake.data["Job Scout"][1][SCOUT.index("ID")] = ""
        assigned = self.tracker.assign_manual_scout_id(
            2, 100, company="Existing", title="Role"
        )
        self.assertEqual(assigned, 100)
        self.assertEqual(self.fake.data["Job Scout"][1][SCOUT.index("ID")], 100)
        self.assertEqual(self.tracker.assign_manual_scout_id(
            2, 100, company="Existing", title="Role"
        ), 100)

    def test_assign_manual_scout_id_rejects_zero_and_collision(self):
        self.fake.data["Job Scout"][1][SCOUT.index("ID")] = ""
        duplicate = [100, "Indeed", "Other", "Role"]
        duplicate.extend([""] * (len(SCOUT) - len(duplicate)))
        self.fake.data["Job Scout"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "positive"):
            self.tracker.assign_manual_scout_id(2, 0, company="Existing", title="Role")
        with self.assertRaisesRegex(RuntimeError, "already in use"):
            self.tracker.assign_manual_scout_id(2, 100, company="Existing", title="Role")

    def test_response_rows_are_applied_only_and_updates_touch_response_only(self):
        self.fake.data["Job Scout"][1][SCOUT.index("Applied")] = True
        rows = self.tracker.applied_response_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["_row"], 2)
        self.assertEqual(rows[0]["Job Number"], "job-123")
        changed = self.tracker.update_response_rows({2: "Interview request - received 9/27/26."})
        self.assertEqual(changed, [2])
        stored = dict(zip(SCOUT, self.fake.data["Job Scout"][1]))
        self.assertEqual(stored["Response"], "Interview request - received 9/27/26.")
        self.assertEqual(self.fake.writes[-1], ("Job Scout", 2, "K"))

    def test_declined_scout_cleanup_deletes_exact_no_rows_bottom_up(self):
        def add(*, apply="", notes=""):
            row = [""] * len(SCOUT)
            row[SCOUT.index("Company")] = f"Company {len(self.fake.data['Job Scout'])}"
            row[SCOUT.index("Apply?")] = apply
            row[SCOUT.index("Notes")] = notes
            self.fake.data["Job Scout"].append(row)

        self.fake.data["Job Scout"][1][SCOUT.index("Apply?")] = "Yes"
        add(apply="no")
        add(notes="No")
        add(apply=" NO ", notes=" no ")
        add(apply="Yes", notes="")
        add(apply="Yes", notes="not interested")

        removed = self.tracker.delete_declined_scout_rows()

        self.assertEqual(removed, [5, 4, 3])
        requests = [item["deleteDimension"]["range"] for item in self.fake.structural]
        self.assertEqual([item["startIndex"] for item in requests], [4, 3, 2])
        remaining = [dict(zip(SCOUT, row)) for row in self.fake.data["Job Scout"][1:]]
        self.assertEqual(
            [(row["Apply?"], row["Notes"]) for row in remaining],
            [("Yes", ""), ("Yes", ""), ("Yes", "not interested")],
        )

    def test_declined_scout_cleanup_uses_moved_headers(self):
        apply_index = SCOUT.index("Apply?")
        response_index = SCOUT.index("Response")
        for row in self.fake.data["Job Scout"]:
            row[apply_index], row[response_index] = row[response_index], row[apply_index]
        self.tracker.delete_declined_scout_rows()
        self.assertEqual(self.fake.structural, [])

    def test_google_failure_never_falls_back_to_a_local_tracker(self):
        self.fake.fail = True
        with self.assertRaisesRegex(RuntimeError, "Cannot read Google Sheets"):
            self.tracker.find_application("job-123")

    def test_legacy_numeric_job_id_uses_exact_resume_filename(self):
        row = {"Job Number": -1.76537430016583e18,
               "Resume Link": "file:///resumes/Dave-Call+Unicity+-1765374300165839452.docx"}
        self.assertEqual(job_key(row), "-1765374300165839452")

    def test_scout_upsert_recomputes_apply_and_does_not_duplicate(self):
        job = normalize(RawListing(source="test", source_job_id="42",
                                   url="https://example.test/job", title="Role",
                                   company="Existing", description="Manage campaigns"))
        job.id = 42
        job.status = "selected"
        self.tracker.upsert_scout([job])
        self.assertEqual(len(self.fake.data["Job Scout"]), 2)
        row = dict(zip(SCOUT, self.fake.data["Job Scout"][1]))
        self.assertEqual(row["Status"], "Selected")
        self.assertEqual(row["Apply?"], "No")

    def test_scout_upsert_sets_apply_for_new_and_updated_rows(self):
        new_job = normalize(RawListing(
            source="test", source_job_id="100", url="https://example.test/new",
            title="New Role", company="New Company", location="Dallas, TX",
            remote_type="On-site", description="Remote work may occasionally be discussed",
        ))
        new_job.id = 100
        self.tracker.upsert_scout([new_job])
        added = dict(zip(SCOUT, self.fake.data["Job Scout"][-1]))
        self.assertEqual(added["Apply?"], "No")

        existing = normalize(RawListing(
            source="test", source_job_id="42", url="https://example.test/job",
            title="Role", company="Existing", location="Lehi, Utah",
            remote_type="Hybrid", description="",
        ))
        existing.id = 42
        self.fake.data["Job Scout"][1][SCOUT.index("Apply?")] = "No"
        self.tracker.upsert_scout([existing])
        updated = dict(zip(SCOUT, self.fake.data["Job Scout"][1]))
        self.assertEqual(updated["Apply?"], "Yes")

    def test_manual_row_location_update_recomputes_apply_by_header(self):
        apply_index = SCOUT.index("Apply?")
        response_index = SCOUT.index("Response")
        for row in self.fake.data["Job Scout"]:
            row[apply_index], row[response_index] = row[response_index], row[apply_index]
        tab = self.tracker.scout()
        self.tracker.update_manual_scout_row(tab, 2, {
            "Location": "Denver, CO", "Work Arrangement": "Hybrid",
        })
        stored = dict(zip(self.fake.data["Job Scout"][0], self.fake.data["Job Scout"][1]))
        self.assertEqual(stored["Apply?"], "No")
        self.assertIn(("Job Scout", 2, "K"), self.fake.writes)

    def test_schema_migration_deletes_retired_columns_and_second_run_is_noop(self):
        legacy = [
            "Scout ID", "Source", "Company", "Job Title", "Gecko Status", "Apply?",
            "Resume Created", "Applied", "Notes", "Response", "Website",
            "Location", "Work Arrangement",
            "Employment Type", "Salary", "Date Posted", "Date Found", "Last Seen",
            "Job URL", "Enrichment URL", "Resume Link", "URL Status", "Authoritative URL",
        ]
        row = list(range(1, len(legacy) + 1))
        self.fake.data["Job Scout"] = [legacy, row]
        result = self.tracker.migrate_scout_schema()
        retained = [name for name in legacy if name not in {
            "Website", "Enrichment URL", "URL Status", "Authoritative URL"
        }]
        self.assertEqual(result["headers"], retained)
        self.assertEqual(self.fake.data["Job Scout"][1], [row[legacy.index(name)] for name in retained])
        request_count = len(self.fake.structural)
        again = self.tracker.migrate_scout_schema()
        self.assertEqual(again["deleted"], [])
        self.assertEqual(len(self.fake.structural), request_count)

    def test_scout_upsert_defensively_rejects_new_jooble_candidate(self):
        job = normalize(RawListing(source="web-careers", source_job_id="blocked",
                                   url="https://jooble.org/jobs/blocked", title="Role",
                                   company="Blocked", description="Manage campaigns"))
        job.id = 99
        result = self.tracker.upsert_scout([job], append_only=True)
        self.assertEqual(result["jooble_excluded"], 1)
        self.assertEqual(len(self.fake.data["Job Scout"]), 2)
        self.assertEqual(self.fake.writes, [])

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
        completed = list(today)
        completed[0] = 45
        completed[SCOUT.index("Status")] = "Resume Created"
        self.fake.data["Job Scout"].append(completed)
        self.fake.formats[3] = {
            "userEnteredFormat": {"backgroundColor": NEW_SCOUT_ID_COLOR},
            "effectiveFormat": {"backgroundColor": NEW_SCOUT_ID_COLOR},
        }
        self.fake.formats[4] = {
            "effectiveFormat": {"backgroundColor": {
                "red": 231 / 255, "green": 230 / 255, "blue": 230 / 255,
            }},
        }
        self.fake.formats[5] = {
            "userEnteredFormat": {"backgroundColor": NEW_SCOUT_ID_COLOR},
            "effectiveFormat": {"backgroundColor": NEW_SCOUT_ID_COLOR},
        }

        self.assertEqual(self.tracker.highlight_scout_found_on("2026-09-25"), 3)
        highlights = [request["updateCells"] for request in self.fake.structural]
        self.assertEqual([item["range"]["startRowIndex"] for item in highlights], [1, 2, 4])
        self.assertEqual(highlights[0]["rows"][0]["values"][0]["userEnteredFormat"]
                         ["backgroundColorStyle"]["rgbColor"],
                         NEW_SCOUT_ID_COLOR)
        self.assertEqual(highlights[1]["rows"][0]["values"][0]["userEnteredFormat"]
                         ["backgroundColorStyle"],
                         {"themeColor": "BACKGROUND"})
        self.assertEqual(highlights[2]["rows"][0]["values"][0]["userEnteredFormat"]
                         ["backgroundColorStyle"]["rgbColor"],
                         NEW_SCOUT_ID_COLOR)
        self.assertTrue(all(item["range"]["startColumnIndex"] == 0 and
                            item["range"]["endColumnIndex"] == 1 and
                            item["fields"] == "userEnteredFormat.backgroundColorStyle"
                            for item in highlights))
        self.assertEqual(self.fake.writes, [])

    def test_dead_scout_clear_ignores_and_preserves_manual_values(self):
        row = self.fake.data["Job Scout"][1]
        row[SCOUT.index("Apply?")] = "Yes"
        row[SCOUT.index("Resume Created")] = "X"
        row[SCOUT.index("Applied")] = False
        row[SCOUT.index("Notes")] = "Keep this manual note"
        row[SCOUT.index("Response")] = "Keep this response"
        removed = self.tracker.remove_dead_scout({42})
        self.assertEqual(removed, {42})
        stored = dict(zip(SCOUT, row))
        physical = {"Scout ID": "ID", "Gecko Status": "Status"}
        self.assertTrue(all(stored[physical.get(field, field)] == "" for field in SCOUT_FIELDS))
        self.assertEqual(stored["Apply?"], "Yes")
        self.assertEqual(stored["Resume Created"], "X")
        self.assertIs(stored["Applied"], False)
        self.assertEqual(stored["Notes"], "Keep this manual note")
        self.assertEqual(stored["Response"], "Keep this response")
        self.assertEqual(self.fake.data["Job Tracker"][1][8:10], ["TRUE", "called"])
        self.assertEqual(self.fake.structural, [])

    def test_dead_scout_clear_is_idempotent_when_id_is_already_absent(self):
        self.fake.data["Job Scout"][1][SCOUT.index("ID")] = ""
        self.fake.data["Job Scout"][1][SCOUT.index("Notes")] = "Preserved"
        self.assertEqual(self.tracker.remove_dead_scout({42}), {42})
        self.assertEqual(self.fake.data["Job Scout"][1][SCOUT.index("Notes")], "Preserved")

    def test_dead_scout_clear_removes_formulas_whitespace_and_false_values(self):
        row = self.fake.data["Job Scout"][1]
        row[SCOUT.index("Location")] = '=IF(TRUE,"","")'
        row[SCOUT.index("Salary")] = "   "
        row[SCOUT.index("Date Posted")] = False
        self.tracker.remove_dead_scout({42})
        stored = dict(zip(SCOUT, row))
        self.assertEqual(stored["Location"], "")
        self.assertEqual(stored["Salary"], "")
        self.assertEqual(stored["Date Posted"], "")

    def test_dead_scout_clear_reports_exact_managed_cell_failure(self):
        company_column = "C"
        self.fake.unclear_cells.add(("Job Scout", 2, company_column))
        with self.assertRaises(RuntimeError) as caught:
            self.tracker.remove_dead_scout({42})
        message = str(caught.exception)
        self.assertIn("sheet='Job Scout'", message)
        self.assertIn("row=2", message)
        self.assertIn("column=C (Company)", message)
        self.assertIn("cell=C2", message)
        self.assertIn("remaining_value='Existing'", message)
        self.assertIn("reason=write completed but the managed value remained", message)


if __name__ == "__main__":
    unittest.main()
