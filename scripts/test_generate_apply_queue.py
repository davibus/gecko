"""Apply queue tests use an isolated fake Google Sheet, never the live tracker."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "job-scout"))
sys.path.insert(0, str(ROOT / "job-scout/tests"))
import generate_apply_queue as queue
from google_tracker import Config, GoogleTracker
from test_google_tracker import FakeSheets, SCOUT


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSheets()
        def scout_row(scout_id, company, apply, created, *, link=""):
            row = [""] * len(SCOUT)
            for field, value in {
                "ID": scout_id, "Source": "test", "Company": company,
                "Job Title": "Role", "Status": "New", "Apply?": apply,
                "Resume Created": created, "Resume Link": link,
            }.items():
                row[SCOUT.index(field)] = value
            return row
        self.fake.data["Job Scout"].extend([
            scout_row(43, "Already", " YES ", " x ", link="https://drive.google.test/already"),
            scout_row(44, "No Apply", "No", ""),
            scout_row(45, "Another", "yes", ""),
            scout_row(46, "Retry", "YES", "failed"),
        ])
        self.tracker = GoogleTracker(Config("test", Path("unused.json"), "Job Tracker", "Job Scout"), self.fake)

    def add_scout_row(self, *, scout_id="", source="Indeed", company="Manual Company",
                      title="Marketing Director", apply="Yes", created="", url="",
                      location="", arrangement="", employment="", salary="", listing=""):
        row = [scout_id, source, company, title, "New", apply, created, "", ""]
        row.extend([""] * (len(SCOUT) - len(row)))
        row[SCOUT.index("Location")] = location
        row[SCOUT.index("Work Arrangement")] = arrangement
        row[SCOUT.index("Employment Type")] = employment
        row[SCOUT.index("Salary")] = salary
        row[SCOUT.index("Job URL")] = listing or url
        self.fake.data["Job Scout"].append(row)
        return len(self.fake.data["Job Scout"])

    def test_yes_queue_skips_x_and_continues_after_failure(self):
        snapshot = queue.read_queue(self.tracker)
        self.assertEqual([item.scout_id for item in snapshot.pending], [42, 45, 46])
        self.assertEqual([item.scout_id for item in snapshot.already_created], [43])
        processed = []

        with TemporaryDirectory() as temp:
            def generate(item, _db):
                processed.append(item.scout_id)
                if item.scout_id == 42:
                    raise RuntimeError("simulated Word QA failure")
                return queue.Artifacts(Path(temp) / "resume.docx", Path("listing.md"))

            def record(item, _artifacts, tracker):
                queue.manage_job_tracker.mark_batch_resume(
                    item.scout_id, item.row, tracker, f"https://drive.google.test/{item.scout_id}"
                )

            result = queue.run_queue(self.tracker, Path("unused.sqlite3"),
                                     generator=generate, recorder=record)
            self.assertEqual(result.exit_code, 1)
        self.assertEqual(processed, [42, 45, 46])
        rows = {int(data[0]): dict(zip(SCOUT, data)) for data in self.fake.data["Job Scout"][1:]}
        self.assertEqual(rows[42]["Resume Created"], "")
        self.assertEqual(rows[45]["Resume Created"], "X")
        self.assertEqual(rows[45]["Apply?"], "yes")
        self.assertEqual(rows[46]["Resume Created"], "X")

    def test_current_queue_eligibility_matrix_includes_repair_and_cost_exclusion(self):
        repair = self.add_scout_row(scout_id=1001, apply=" yes ", created=" X ")
        self.fake.data["Job Scout"][repair - 1][SCOUT.index("Resume Link")] = "   "
        create = self.add_scout_row(scout_id=1002, apply="YES", created="")
        cost = self.add_scout_row(scout_id=1003, apply="Yes", created="X")
        self.fake.data["Job Scout"][cost - 1][SCOUT.index("Cost")] = " X "
        linked = self.add_scout_row(scout_id=1004, apply="Yes", created="X")
        self.fake.data["Job Scout"][linked - 1][SCOUT.index("Resume Link")] = (
            "https://example.test/resume.docx"
        )
        declined = self.add_scout_row(scout_id=1005, apply="No", created="")

        snapshot = queue.read_queue(self.tracker, source="indeed")

        self.assertIn(repair, [item.row for item in snapshot.link_backfill])
        self.assertIn(create, [item.row for item in snapshot.pending])
        self.assertIn(cost, [item.row for item in snapshot.cost_excluded])
        self.assertIn(linked, [item.row for item in snapshot.already_created])
        self.assertIn(declined, [item.row for item in snapshot.not_approved])

    def test_repair_link_failure_preserves_existing_x_and_blank_q(self):
        row = self.add_scout_row(scout_id=1010, apply="Yes", created="X")
        failure_recorder = Mock()
        run = queue.run_queue(
            self.tracker, Path("unused.sqlite3"), source="indeed",
            existing_generator=lambda *_: queue.Artifacts(Path("resume.docx"), Path("listing.md")),
            recorder=Mock(side_effect=RuntimeError("simulated link failure")),
            failure_recorder=failure_recorder, print_summary=False,
        )
        stored = next(data for number, data in self.tracker.scout().rows if number == row)
        self.assertEqual(len(run.failures), 1)
        self.assertEqual(stored["Resume Created"], "X")
        self.assertEqual(stored["Resume Link"], "")
        failure_recorder.assert_called_once()

    def test_repair_uses_versioned_filename_without_overwriting_existing_resume(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "output" / "resumes"
            output.mkdir(parents=True)
            listing = root / "listing.md"
            listing.write_text("listing", encoding="utf-8")
            plan = {"job": {
                "company": "Version Company", "safe_company": "Version-Company",
                "title": "Marketing Director", "job_number": "job-1011",
            }}
            expected = output / queue.gecko_v2.resume_filename(
                "Version Company", "Marketing Director", "job-1011",
            )
            expected.write_bytes(b"old resume")

            def make_resume(_plan, destination):
                destination.write_bytes(b"current resume")

            item = queue.QueueRow(2, 1011, "Version Company", "Marketing Director")
            with patch.object(queue, "ROOT", root), \
                 patch.object(queue.gecko_v2, "create_plan", return_value=plan), \
                 patch.object(queue.gecko_v2, "make_resume", side_effect=make_resume), \
                 patch.object(queue.gecko_v2, "native_qa", return_value={"status": "pass"}):
                artifacts = queue._finish_generation(
                    item, listing, (), force_recreate=True,
                )

            self.assertEqual(expected.read_bytes(), b"old resume")
            self.assertEqual(artifacts.resume.read_bytes(), b"current resume")
            self.assertEqual(
                artifacts.resume.name,
                "Dave-Call+Version-Company+Marketing-Director+v2+job-1011.docx",
            )

    def test_final_step_updates_managed_cells_and_preserves_apply(self):
        self.fake.data["Job Scout"][1][SCOUT.index("Applied")] = "TRUE"
        self.fake.data["Job Scout"][1][SCOUT.index("Notes")] = (
            "Recruiter contacted\nResume not created: prior temporary failure"
        )
        with TemporaryDirectory() as temp:
            temp = Path(temp)
            resume = temp / "Dave-Call+Existing+queue-42.docx"
            listing = temp / "Existing+queue-42.md"
            resume.write_bytes(b"test artifact")
            listing.write_text("# Role\n\n- **Company:** Existing\n- **Job Number:** queue-42\n"
                               "- **Scout ID:** 42\n- **URL:** https://example.test/job\n", encoding="utf-8")
            item = queue.QueueRow(2, 42, "Existing", "Role")
            with patch.object(queue.manage_job_tracker, "publish_resume",
                              return_value="https://drive.google.test/queue-42"):
                queue.record_success(item, queue.Artifacts(resume, listing), self.tracker)
        self.assertEqual([(tab, col) for tab, _, col in self.fake.writes if tab == "Job Scout"],
                         [("Job Scout", "E"), ("Job Scout", "Q"),
                          ("Job Scout", "G"), ("Job Scout", "J")])
        scout = next(data for _, data in self.tracker.scout().rows if str(data.get("Scout ID")) == "42")
        self.assertEqual(scout["Resume Created"], "X")
        self.assertEqual(scout["Apply?"], "Yes")
        self.assertEqual(scout["Gecko Status"], "Resume Created")
        self.assertEqual(
            scout["Resume Link"],
            "https://drive.google.test/queue-42",
        )
        self.assertEqual(scout["Applied"], "TRUE")
        self.assertEqual(scout["Notes"], "Recruiter contacted")
        applications = [data for _, data in self.tracker.application().rows
                        if str(data.get("Job Number")) == "queue-42"]
        self.assertEqual(applications, [])

    def test_missing_artifact_or_changed_apply_never_marks_g(self):
        item = queue.QueueRow(2, 42, "Existing", "Role")
        with self.assertRaisesRegex(ValueError, "missing"):
            queue.record_success(item, queue.Artifacts(Path("missing.docx"), Path("listing.md")),
                                 self.tracker)
        self.fake.data["Job Scout"][1][SCOUT.index("Apply?")] = "No"
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "resume.docx"
            resume.write_bytes(b"docx")
            with self.assertRaisesRegex(RuntimeError, "Apply"):
                queue.record_success(item, queue.Artifacts(resume, Path("listing.md")),
                                     self.tracker)
        self.assertEqual(self.fake.writes, [])

    def test_tracker_write_failure_leaves_column_g_unchanged(self):
        item = queue.QueueRow(2, 42, "Existing", "Role")
        with TemporaryDirectory() as temp:
            temp = Path(temp)
            resume = temp / "Dave-Call+Existing+Role+queue-42.docx"
            listing = temp / "Existing+queue-42.md"
            resume.write_bytes(b"docx")
            listing.write_text(
                "# Role\n\n- **Company:** Existing\n- **Job Number:** queue-42\n"
                "- **Scout ID:** 42\n- **URL:** https://example.test/job\n",
                encoding="utf-8",
            )
            with patch.object(queue.manage_job_tracker, "publish_resume",
                              return_value="https://drive.google.test/queue-42"), \
                 patch.object(self.tracker, "mark_scout_resume",
                              side_effect=RuntimeError("simulated Sheets write failure")):
                with self.assertRaisesRegex(RuntimeError, "simulated Sheets"):
                    queue.record_success(item, queue.Artifacts(resume, listing), self.tracker)
        scout = next(data for _, data in self.tracker.scout().rows
                     if str(data.get("Scout ID")) == "42")
        self.assertEqual(scout["Resume Created"], "")

    def test_failure_reason_is_specific_retryable_and_preserves_other_notes(self):
        self.fake.data["Job Scout"][1][SCOUT.index("Notes")] = "Keep this note"
        queue.manage_job_tracker.record_queue_failure(
            42, 2, "Word-native validation returned three pages", self.tracker
        )
        scout = next(data for _, data in self.tracker.scout().rows
                     if str(data.get("Scout ID")) == "42")
        self.assertEqual(
            scout["Notes"],
            "Keep this note\nResume not created: Word-native validation returned three pages",
        )
        self.assertEqual(scout["Resume Created"], "")

    def test_sparse_row_context_has_no_description_length_floor(self):
        with TemporaryDirectory() as temp, patch.object(queue, "ROOT", Path(temp)):
            item = queue.QueueRow(
                2, 42, "Existing", "Paid Search Manager", "https://example.test/job",
                "test", {"Location": "Remote"},
            )
            listing = queue._archive_row_context(item)
            plan = queue.gecko_v2.create_plan(listing)
        self.assertEqual(plan["job"]["company"], "Existing")
        self.assertEqual(plan["job"]["title"], "Paid Search Manager")

    def test_indeed_source_filter_uses_source_or_job_url(self):
        rows = self.fake.data["Job Scout"]
        source_row = [50, "Indeed", "Source Match", "Role", "New", "Yes", "", "", ""]
        url_row = [51, "Manual", "URL Match", "Role", "New", "Yes", "", "", ""]
        completed = [52, "Indeed", "Complete", "Role", "Resume Created", "Yes", "X", "", ""]
        not_approved = [53, "Indeed", "No Apply", "Role", "New", "No", "", "", ""]
        unrelated = [54, "Manual", "Other", "Role", "New", "Yes", "", "", ""]
        for row in (source_row, url_row, completed, not_approved, unrelated):
            row.extend([""] * (len(SCOUT) - len(row)))
            rows.append(row)
        url_row[SCOUT.index("Job URL")] = "https://www.indeed.com/viewjob?jk=url-match-51"
        unrelated[SCOUT.index("Job URL")] = "https://example.test/viewjob?jk=not-indeed"

        run = queue.run_queue(
            self.tracker, Path("unused.sqlite3"), source="indeed", dry_run=True,
            generator=lambda *_: self.fail("dry run generated a resume"),
            recorder=lambda *_: self.fail("dry run updated the tracker"),
            print_summary=False,
        )
        snapshot = run.snapshot

        self.assertEqual([item.scout_id for item in snapshot.pending], [50, 51])
        self.assertEqual([item.scout_id for item in snapshot.link_backfill], [52])
        self.assertEqual([item.scout_id for item in snapshot.not_approved], [53])
        self.assertTrue(run.dry_run)
        self.assertEqual(run.successes, [])

    def test_manual_indeed_row_with_yes_and_blank_scout_id_is_eligible(self):
        row = self.add_scout_row(url="https://www.indeed.com/viewjob?jk=blank-id")

        snapshot = queue.read_queue(self.tracker, source="indeed")
        item = next(item for item in snapshot.pending if item.row == row)

        self.assertIsNone(item.scout_id)
        self.assertTrue(queue._still_pending(self.tracker, item))
        queue.manage_job_tracker.mark_batch_resume(
            None, row, self.tracker, "https://drive.google.test/blank-id"
        )
        completed = next(data for number, data in self.tracker.scout().rows if number == row)
        self.assertEqual(completed["Scout ID"], "")
        self.assertEqual(completed["Resume Created"], "X")

    def test_manual_indeed_row_without_sqlite_record_uses_row_context(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            item = queue.QueueRow(
                20, None, "No Database Company", "Growth Marketing Director",
                "https://www.indeed.com/viewjob?jk=no-database", "Indeed",
                {"Location": "Remote"},
            )
            expected = queue.Artifacts(root / "resume.docx", root / "listing.md")
            retrieval = queue.DescriptionRetrievalResult(
                "succeeded", description="Retrieved Indeed job duties and requirements.",
                source_url=item.job_url, attempts=[],
            )
            with patch.object(queue, "ROOT", root), patch.object(
                queue, "retrieve_full_description", return_value=retrieval
            ), patch.object(queue, "_finish_generation", return_value=expected) as finish:
                actual = queue.generate(item, root / "missing.sqlite3")

            self.assertEqual(actual, expected)
            content = finish.call_args.args[1].read_text(encoding="utf-8")
            self.assertIn("**Job Number:** no-database", content)
            self.assertNotIn("**Scout ID:**", content)
            self.assertIn("Retrieved Indeed job duties and requirements.", content)

    def test_indeed_url_with_blank_source_is_eligible(self):
        row = self.add_scout_row(
            source="", url="https://to.indeed.com/short-link", company="URL Company"
        )

        snapshot = queue.read_queue(self.tracker, source="indeed")

        self.assertIn(row, [item.row for item in snapshot.pending])

    def test_apply_yes_matching_normalizes_case_and_whitespace(self):
        rows = [self.add_scout_row(company=f"Company {index}", apply=value)
                for index, value in enumerate(("Yes ", "YES", "yes"), 1)]

        snapshot = queue.read_queue(self.tracker, source="indeed")

        self.assertTrue(set(rows) <= {item.row for item in snapshot.pending})

    def test_apply_not_yes_is_excluded_with_diagnostic(self):
        row = self.add_scout_row(company="Not Approved", apply="Later")

        snapshot = queue.read_queue(self.tracker, source="indeed")

        self.assertIn(row, [item.row for item in snapshot.not_approved])
        self.assertIn("explicit value", dict((item.row, reason)
                                              for item, reason in snapshot.decisions)[row])

    def test_resume_created_x_is_excluded(self):
        row = self.add_scout_row(company="Already Complete", created=" x ")

        snapshot = queue.read_queue(self.tracker, source="indeed")

        self.assertIn(row, [item.row for item in snapshot.link_backfill])
        self.assertNotIn(row, [item.row for item in snapshot.pending])

    def test_duplicate_indeed_job_key_is_queued_once(self):
        first = self.add_scout_row(
            company="Duplicate Company",
            url="https://www.indeed.com/viewjob?jk=same-job&from=first",
        )
        second = self.add_scout_row(
            company="Duplicate Company",
            url="https://www.indeed.com/viewjob?from=second&jk=same-job",
        )

        snapshot = queue.read_queue(self.tracker, source="indeed")

        self.assertIn(first, [item.row for item in snapshot.pending])
        self.assertIn(second, [item.row for item in snapshot.duplicate_excluded])

    def test_blank_apply_utah_location_would_auto_approve(self):
        row = self.add_scout_row(
            apply="", location="Salt Lake City, UT", listing="Lead paid search campaigns."
        )
        snapshot = queue.read_queue(self.tracker, source="indeed")
        decision = dict((item.row, reason) for item, reason in snapshot.decisions)[row]
        self.assertIn(row, [item.row for item in snapshot.pending])
        self.assertIn("WOULD SET APPLY? = Yes | Utah", decision)

    def test_blank_apply_remote_would_auto_approve_case_insensitively(self):
        row = self.add_scout_row(
            apply="", location="California", arrangement="fUlLy ReMoTe",
            listing="Own lifecycle marketing programs.",
        )
        snapshot = queue.read_queue(self.tracker, source="indeed")
        decision = dict((item.row, reason) for item, reason in snapshot.decisions)[row]
        self.assertIn("WOULD SET APPLY? = Yes | Remote", decision)

    def test_supported_explicit_remote_representations(self):
        examples = (
            "Remote", "Fully Remote", "100% Remote", "Remote - United States",
            "Remote, United States", "US Remote", "Work From Home",
            "Work from anywhere in the United States",
        )
        for value in examples:
            with self.subTest(value=value):
                item = queue.QueueRow(
                    2, None, "Company", "Role", fields={"Work Arrangement": value}
                )
                self.assertEqual(queue._geographic_qualification(item), "Remote")

    def test_blank_apply_california_onsite_does_not_qualify(self):
        row = self.add_scout_row(
            apply="", location="San Francisco, CA", arrangement="Onsite",
            listing="Lead the regional marketing team.",
        )
        snapshot = queue.read_queue(self.tracker, source="indeed")
        self.assertIn(row, [item.row for item in snapshot.not_approved])
        self.assertIn("outside Utah and not remote",
                      dict((item.row, reason) for item, reason in snapshot.decisions)[row])

    def test_blank_apply_non_utah_hybrid_does_not_qualify_without_full_remote(self):
        row = self.add_scout_row(
            apply="", location="Denver, CO", arrangement="Hybrid",
            listing="Hybrid role with occasional work from home and Zoom meetings.",
        )
        snapshot = queue.read_queue(self.tracker, source="indeed")
        self.assertIn(row, [item.row for item in snapshot.not_approved])

    def test_descriptive_remote_text_does_not_qualify_non_remote_fields(self):
        row = self.add_scout_row(
            apply="", location="California", arrangement="On-site",
            listing="The company also supports remote work in selected departments.",
        )
        snapshot = queue.read_queue(self.tracker, source="indeed")
        self.assertIn(row, [item.row for item in snapshot.not_approved])

    def test_utah_detection_handles_case_and_ut_abbreviation(self):
        for location in ("draper, utah", "LEHI, UT", "ut"):
            item = queue.QueueRow(2, None, "Company", "Role", fields={"Location": location})
            self.assertEqual(queue._geographic_qualification(item), "Utah")

    def test_existing_yes_is_eligible_even_outside_utah(self):
        row = self.add_scout_row(
            apply="YES ", location="San Diego, CA", arrangement="Onsite",
            listing="Manage demand generation campaigns.",
        )
        snapshot = queue.read_queue(self.tracker, source="indeed")
        self.assertIn(row, [item.row for item in snapshot.pending])

    def test_qualifying_utah_row_is_set_to_yes_even_when_previously_no(self):
        row = self.add_scout_row(
            apply="No", location="Provo, UT", listing="Manage paid media programs."
        )
        snapshot = queue.read_queue(self.tracker, source="indeed")
        self.assertIn(row, [item.row for item in snapshot.pending])
        with TemporaryDirectory() as temp:
            queue.run_queue(
                self.tracker, Path(temp) / "empty.sqlite3", source="indeed",
                generator=lambda *_: (_ for _ in ()).throw(RuntimeError("stop after approval")),
                print_summary=False,
            )
        stored = next(data for number, data in self.tracker.scout().rows if number == row)
        self.assertEqual(stored["Apply?"], "Yes")

    def test_unspecified_location_and_arrangement_are_left_unchanged(self):
        row = self.add_scout_row(
            apply="", location="", arrangement="",
            listing="Lead demand generation for a distributed company.",
        )
        snapshot = queue.read_queue(self.tracker, source="indeed")
        self.assertIn(row, [item.row for item in snapshot.not_approved])
        self.assertEqual(self.fake.data["Job Scout"][-1][SCOUT.index("Apply?")], "")

    def test_daily_all_source_geographic_approval_matrix(self):
        utah = self.add_scout_row(
            scout_id=930, source="Adzuna", company="Utah Company", apply="",
            location="Salt Lake City, UT", arrangement="Hybrid",
            listing="Lead lifecycle marketing.",
        )
        remote = self.add_scout_row(
            scout_id=931, source="Remotive", company="Remote Company", apply="",
            location="United States", arrangement="Remote",
            listing="Lead performance marketing.",
        )
        hybrid = self.add_scout_row(
            scout_id=932, source="LinkedIn", company="Hybrid Company", apply="",
            location="Denver, CO", arrangement="Hybrid",
            listing="Lead brand marketing.",
        )
        unspecified = self.add_scout_row(
            scout_id=933, source="Greenhouse", company="Unspecified Company", apply="",
            location="", arrangement="",
            listing="Lead acquisition marketing.",
        )
        with TemporaryDirectory() as temp:
            result = queue.run_queue(
                self.tracker, Path(temp) / "empty.sqlite3",
                eligible_scout_ids={930, 931, 932, 933},
                auto_approve_geographic=True,
                generator=lambda *_: (_ for _ in ()).throw(RuntimeError("simulated generation failure")),
                print_summary=False,
            )
        live = {row: data for row, data in self.tracker.scout().rows}
        self.assertEqual(live[utah]["Apply?"], "Yes")
        self.assertEqual(live[remote]["Apply?"], "Yes")
        self.assertEqual(live[hybrid]["Apply?"], "")
        self.assertEqual(live[unspecified]["Apply?"], "")
        self.assertEqual(live[utah]["Resume Created"], "")
        self.assertEqual(live[remote]["Resume Created"], "")
        self.assertEqual(len(result.failures), 2)

    def test_qualifying_blank_id_gets_unique_persistent_scout_id(self):
        row = self.add_scout_row(
            apply="", location="Midvale, UT", listing="Manage paid search campaigns."
        )
        item = next(item for item in queue.read_queue(
            self.tracker, source="indeed").pending if item.row == row)
        with TemporaryDirectory() as temp:
            prepared = queue._prepare_indeed_item(
                self.tracker, item, Path(temp) / "empty.sqlite3"
            )
        self.assertGreater(prepared.scout_id, 0)
        stored = next(data for number, data in self.tracker.scout().rows if number == row)
        self.assertEqual(stored["Apply?"], "Yes")
        self.assertEqual(stored["Scout ID"], prepared.scout_id)

    def test_existing_scout_id_is_preserved_by_preparation(self):
        row = self.add_scout_row(
            scout_id=812, apply="Yes", listing="Lead acquisition marketing strategy."
        )
        item = next(item for item in queue.read_queue(
            self.tracker, source="indeed").pending if item.row == row)
        with TemporaryDirectory() as temp:
            prepared = queue._prepare_indeed_item(
                self.tracker, item, Path(temp) / "empty.sqlite3"
            )
        self.assertEqual(prepared.scout_id, 812)

    def test_two_manual_rows_receive_different_scout_ids(self):
        rows = [self.add_scout_row(
            company=f"Unique Company {number}", apply="Yes",
            listing="Lead performance marketing programs.",
        ) for number in (1, 2)]
        items = [item for item in queue.read_queue(self.tracker, source="indeed").pending
                 if item.row in rows]
        with TemporaryDirectory() as temp:
            db = Path(temp) / "empty.sqlite3"
            prepared = [queue._prepare_indeed_item(self.tracker, item, db) for item in items]
        self.assertEqual(len({item.scout_id for item in prepared}), 2)

    def test_batch_prepares_all_blank_apply_and_ids_before_generation(self):
        self.add_scout_row(
            scout_id=2500, source="Other", company="Existing ID", title="Role",
            apply="No", listing="Existing unrelated job.",
        )
        rows = [self.add_scout_row(
            company=f"Batch Company {number}", title=f"Marketing Role {number}",
            apply="", location="Lehi, UT",
            listing="Lead measurable growth marketing programs.",
        ) for number in range(4)]
        self.fake.data["Job Scout"][rows[0] - 1][SCOUT.index("Applied")] = "x"
        generated = []

        with TemporaryDirectory() as temp:
            root = Path(temp)
            resume_dir = root / "output" / "resumes"
            resume_dir.mkdir(parents=True)

            def generate(item, _db):
                # All four rows must already have durable approval and IDs when
                # the first slow generation begins.
                live = {row: data for row, data in self.tracker.scout().rows}
                self.assertTrue(all(str(live[row]["Apply?"]).strip() == "Yes" for row in rows))
                self.assertTrue(all(queue._scout_id(live[row]["Scout ID"]) for row in rows))
                generated.append(item.scout_id)
                resume = resume_dir / f"resume-{item.scout_id}.docx"
                resume.write_bytes(b"validated docx")
                listing = root / f"listing-{item.scout_id}.md"
                listing.write_text(
                    f"# {item.title}\n\n- **Company:** {item.company}\n"
                    f"- **Job Number:** scout-{item.scout_id}\n"
                    f"- **Scout ID:** {item.scout_id}\n",
                    encoding="utf-8",
                )
                return queue.Artifacts(resume, listing)

            run = queue.run_queue(
                self.tracker, root / "empty.sqlite3", source="indeed",
                generator=generate,
                recorder=lambda item, *_: queue.manage_job_tracker.mark_batch_resume(
                    item.scout_id, item.row, self.tracker,
                    f"https://drive.google.test/{item.scout_id}", completion_marker="X",
                ),
                print_summary=False,
            )

        live = {row: data for row, data in self.tracker.scout().rows}
        assigned = [queue._scout_id(live[row]["Scout ID"]) for row in rows]
        self.assertEqual(run.apply_values_set, 4)
        self.assertEqual(run.scout_ids_assigned, 4)
        self.assertEqual(len(set(assigned)), 4)
        self.assertTrue(all(value > 2500 for value in assigned))
        self.assertEqual(generated, assigned)
        self.assertTrue(all(live[row]["Resume Created"] == "X" for row in rows))
        self.assertTrue(all("https://drive.google.test/" in live[row]["Resume Link"] for row in rows))
        self.assertEqual(live[rows[0]]["Applied"], "x")

    def test_one_manual_generation_failure_does_not_block_later_rows(self):
        rows = [self.add_scout_row(
            company=f"Resilient Company {number}", title=f"Role {number}",
            apply="", location="Provo, UT", listing="Lead lifecycle marketing.",
        ) for number in range(3)]
        generated_rows = []

        with TemporaryDirectory() as temp:
            root = Path(temp)
            resume_dir = root / "output" / "resumes"
            resume_dir.mkdir(parents=True)

            def generate(item, _db):
                generated_rows.append(item.row)
                if item.row == rows[1]:
                    raise RuntimeError("isolated generation failure")
                resume = resume_dir / f"resume-{item.scout_id}.docx"
                resume.write_bytes(b"validated docx")
                listing = root / f"listing-{item.scout_id}.md"
                listing.write_text(
                    f"# {item.title}\n\n- **Company:** {item.company}\n"
                    f"- **Job Number:** scout-{item.scout_id}\n"
                    f"- **Scout ID:** {item.scout_id}\n",
                    encoding="utf-8",
                )
                return queue.Artifacts(resume, listing)

            run = queue.run_queue(
                self.tracker, root / "empty.sqlite3", source="indeed",
                generator=generate,
                recorder=lambda item, *_: queue.manage_job_tracker.mark_batch_resume(
                    item.scout_id, item.row, self.tracker,
                    f"https://drive.google.test/{item.scout_id}", completion_marker="X",
                ),
                print_summary=False,
            )

        live = {row: data for row, data in self.tracker.scout().rows}
        self.assertEqual(generated_rows, rows)
        self.assertEqual(run.scout_ids_assigned, 3)
        self.assertEqual(live[rows[0]]["Resume Created"], "X")
        self.assertEqual(live[rows[1]]["Resume Created"], "")
        self.assertEqual(live[rows[2]]["Resume Created"], "X")
        self.assertIn("https://drive.google.test/", live[rows[2]]["Resume Link"])

    def test_column_r_listing_is_primary_and_short_listing_is_accepted(self):
        with TemporaryDirectory() as temp, patch.object(queue, "ROOT", Path(temp)):
            item = queue.QueueRow(
                20, 900, "Listing Company", "PPC Manager", "", "Indeed",
                {"Location": "Lehi, UT"}, "Manage paid search.",
            )
            listing = queue._archive_row_context(item)
            content = listing.read_text(encoding="utf-8")
        self.assertIn("## Job description (Google Sheet Job URL/listing field)", content)
        self.assertIn("Manage paid search.", content)

    def test_effectively_empty_listing_and_metadata_fail_safely(self):
        with TemporaryDirectory() as temp, patch.object(queue, "ROOT", Path(temp)):
            item = queue.QueueRow(20, 900, "Empty Company", "Marketing Role", fields={})
            with self.assertRaisesRegex(ValueError, "no usable job listing"):
                queue._archive_row_context(item)

    def test_successful_manual_run_sets_x_and_real_link_after_generation(self):
        row = self.add_scout_row(
            apply="", location="American Fork, UT",
            listing="Manage growth marketing campaigns.",
        )
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "resume.docx"
            resume.write_bytes(b"docx")
            run = queue.run_queue(
                self.tracker, Path(temp) / "empty.sqlite3", source="indeed",
                generator=lambda item, db: queue.Artifacts(resume, Path("listing.md")),
                recorder=lambda item, artifacts, tracker: queue.manage_job_tracker.mark_batch_resume(
                    item.scout_id, item.row, tracker, "https://drive.google.test/manual-resume",
                    completion_marker="X",
                ), print_summary=False,
            )
        stored = next(data for number, data in self.tracker.scout(
            value_render_option="FORMULA").rows if number == row)
        self.assertEqual(len(run.successes), 1)
        self.assertEqual(stored["Resume Created"], "X")
        self.assertIn("https://drive.google.test/manual-resume", stored["Resume Link"])

    def test_default_indeed_success_records_clickable_absolute_file_uri(self):
        row = self.add_scout_row(
            scout_id=901, apply="Yes", location="Lehi, UT",
            listing="Manage growth marketing campaigns.",
        )
        with TemporaryDirectory() as temp:
            root = Path(temp)
            resume_dir = root / "output" / "resumes"
            resume_dir.mkdir(parents=True)
            resume = resume_dir / "Dave-Call+Local-Co+Marketing-Director+local-901.docx"
            resume.write_bytes(b"validated docx")
            listing = root / "Local-Co+local-901.md"
            listing.write_text(
                "# Marketing Director\n\n- **Company:** Manual Company\n"
                "- **Job Number:** local-901\n- **Scout ID:** 901\n",
                encoding="utf-8",
            )
            with patch.object(queue, "ROOT", root), \
                 patch.object(queue.manage_job_tracker, "RESUME_DIR", resume_dir), \
                 patch("google_tracker.RESUME_DIR", resume_dir.resolve()):
                run = queue.run_queue(
                    self.tracker, root / "empty.sqlite3", source="indeed",
                    generator=lambda item, db: queue.Artifacts(resume, listing),
                    print_summary=False,
                )
        stored = next(data for number, data in self.tracker.scout(
            value_render_option="FORMULA").rows if number == row)
        self.assertEqual(len(run.successes), 1)
        self.assertEqual(stored["Resume Created"], "X")
        self.assertEqual(
            stored["Resume Link"],
            resume.resolve().as_uri(),
        )

    def test_local_record_rejects_empty_artifact_without_marking_completion(self):
        row = self.add_scout_row(
            scout_id=902, apply="Yes", location="Provo, UT",
            listing="Lead paid media programs.",
        )
        with TemporaryDirectory() as temp:
            root = Path(temp)
            resume_dir = root / "output" / "resumes"
            resume_dir.mkdir(parents=True)
            resume = resume_dir / "empty.docx"
            resume.touch()
            listing = root / "listing.md"
            listing.write_text(
                "# Marketing Director\n\n- **Company:** Manual Company\n"
                "- **Job Number:** local-902\n- **Scout ID:** 902\n",
                encoding="utf-8",
            )
            with patch.object(queue.manage_job_tracker, "RESUME_DIR", resume_dir), \
                 patch("google_tracker.RESUME_DIR", resume_dir.resolve()), \
                 patch.object(queue.manage_job_tracker, "publish_resume",
                              return_value="https://drive.google.test/local-903"):
                run = queue.run_queue(
                    self.tracker, root / "empty.sqlite3", source="indeed",
                    generator=lambda item, db: queue.Artifacts(resume, listing),
                    print_summary=False,
                )
        stored = next(data for number, data in self.tracker.scout(
            value_render_option="FORMULA").rows if number == row)
        self.assertEqual(len(run.failures), 1)
        self.assertEqual(stored["Resume Created"], "")
        self.assertEqual(stored["Resume Link"], "")

    def test_retry_after_prior_storage_failure_uses_existing_local_artifact(self):
        row = self.add_scout_row(
            scout_id=903, apply="Yes", location="Draper, UT",
            listing="Lead lifecycle marketing programs.",
        )
        self.fake.data["Job Scout"][-1][SCOUT.index("Notes")] = (
            "Resume not created: Google Drive resume storage is required: "
            "set GOOGLE_DRIVE_RESUME_FOLDER_ID"
        )
        with TemporaryDirectory() as temp:
            root = Path(temp)
            resume_dir = root / "output" / "resumes"
            resume_dir.mkdir(parents=True)
            resume = resume_dir / "Dave-Call+Retry-Co+Marketing-Director+local-903.docx"
            resume.write_bytes(b"already validated docx")
            listing = root / "listing.md"
            listing.write_text(
                "# Marketing Director\n\n- **Company:** Manual Company\n"
                "- **Job Number:** local-903\n- **Scout ID:** 903\n",
                encoding="utf-8",
            )
            with patch.object(queue, "ROOT", root), \
                 patch.object(queue.manage_job_tracker, "RESUME_DIR", resume_dir), \
                 patch("google_tracker.RESUME_DIR", resume_dir.resolve()):
                run = queue.run_queue(
                    self.tracker, root / "empty.sqlite3", source="indeed",
                    generator=lambda item, db: queue.Artifacts(
                        resume, listing, existing=True
                    ), print_summary=False,
                )
        stored = next(data for number, data in self.tracker.scout(
            value_render_option="FORMULA").rows if number == row)
        self.assertEqual(run.recovered, 1)
        self.assertEqual(stored["Resume Created"], "X")
        self.assertEqual(
            stored["Resume Link"],
            resume.resolve().as_uri(),
        )
        self.assertNotIn("Google Drive", stored["Notes"])

    def test_existing_canonical_local_resume_is_recovered_without_regeneration(self):
        row = self.add_scout_row(
            scout_id=904, apply="Yes", location="Lehi, UT",
            company="Recovery Company", title="Growth Marketing Manager",
            url="https://www.indeed.com/viewjob?jk=recovery-904",
        )
        with TemporaryDirectory() as temp:
            root = Path(temp)
            resume_dir = root / "output" / "resumes"
            resume_dir.mkdir(parents=True)
            listing = root / "Recovery-Company+recovery-904.md"
            listing.write_text(
                "# Growth Marketing Manager\n\n- **Company:** Recovery Company\n"
                "- **Job Number:** recovery-904\n- **Scout ID:** 904\n",
                encoding="utf-8",
            )
            plan = {
                "job": {
                    "company": "Recovery Company", "safe_company": "Recovery-Company",
                    "title": "Growth Marketing Manager", "job_number": "recovery-904",
                }
            }
            resume = resume_dir / queue.gecko_v2.resume_filename(
                "Recovery Company", "Growth Marketing Manager", "recovery-904",
            )
            resume.write_bytes(b"existing validated docx")
            with patch.object(queue, "ROOT", root), \
                 patch.object(queue.manage_job_tracker, "RESUME_DIR", resume_dir), \
                 patch("google_tracker.RESUME_DIR", resume_dir.resolve()), \
                 patch.object(queue.gecko_v2, "create_plan", return_value=plan), \
                 patch.object(queue.gecko_v2, "native_qa", return_value={"status": "pass"}), \
                 patch.object(queue.gecko_v2, "make_resume") as make_resume:
                run = queue.run_queue(
                    self.tracker, root / "empty.sqlite3", source="indeed",
                    generator=lambda item, db: queue._finish_generation(item, listing, ()),
                    print_summary=False,
                )
                make_resume.assert_not_called()

        stored = next(data for number, data in self.tracker.scout().rows if number == row)
        self.assertEqual(run.recovered, 1)
        self.assertEqual(stored["Resume Created"], "X")
        self.assertEqual(
            stored["Resume Link"],
            resume.resolve().as_uri(),
        )

    def test_completed_applied_row_backfills_local_link_without_reapproval(self):
        row = self.add_scout_row(
            scout_id=905, apply="", created="X", location="Lehi, UT",
            company="Applied Company", title="Marketing Manager",
            url="https://www.indeed.com/viewjob?jk=applied-905",
        )
        self.fake.data["Job Scout"][row - 1][SCOUT.index("Applied")] = "x"
        with TemporaryDirectory() as temp:
            root = Path(temp)
            resume_dir = root / "output" / "resumes"
            resume_dir.mkdir(parents=True)
            resume = resume_dir / "Dave-Call+Applied-Company+Marketing-Manager+applied-905.docx"
            resume.write_bytes(b"existing validated docx")
            listing = root / "listing.md"
            listing.write_text(
                "# Marketing Manager\n\n- **Company:** Applied Company\n"
                "- **Job Number:** applied-905\n- **Scout ID:** 905\n",
                encoding="utf-8",
            )
            with patch.object(queue.manage_job_tracker, "RESUME_DIR", resume_dir), \
                 patch("google_tracker.RESUME_DIR", resume_dir.resolve()), \
                 patch.object(queue.manage_job_tracker, "publish_resume",
                              return_value="https://drive.google.test/applied-905"):
                run = queue.run_queue(
                    self.tracker, root / "empty.sqlite3", source="indeed",
                    existing_generator=lambda item, db: queue.Artifacts(
                        resume, listing, existing=True,
                    ), print_summary=False,
                )

        stored = next(data for number, data in self.tracker.scout().rows if number == row)
        self.assertEqual(run.recovered, 1)
        self.assertEqual(stored["Apply?"], "Yes")
        self.assertEqual(stored["Applied"], "x")
        self.assertEqual(stored["Resume Created"], "X")
        self.assertIn("https://drive.google.test/applied-905", stored["Resume Link"])

    def test_completed_nonqualifying_row_is_not_repaired(self):
        row = self.add_scout_row(
            scout_id=906, apply="No", created="X", location="Denver, CO",
            arrangement="Hybrid", company="Repair Company", title="Marketing Manager",
            url="https://www.indeed.com/viewjob?jk=repair-906",
        )
        with TemporaryDirectory() as temp:
            root = Path(temp)
            resume = root / "Dave-Call+Repair-Company+Marketing-Manager+repair-906.docx"
            resume.write_bytes(b"rebuilt and validated docx")
            listing = root / "Repair-Company+repair-906.md"
            listing.write_text(
                "# Marketing Manager\n\n- **Company:** Repair Company\n"
                "- **Job Number:** repair-906\n- **Scout ID:** 906\n",
                encoding="utf-8",
            )
            generated = []

            def rebuild(item, _db):
                generated.append(item.scout_id)
                return queue.Artifacts(resume, listing)

            with patch.object(
                queue.manage_job_tracker, "publish_resume",
                return_value="https://drive.google.test/repair-906",
            ):
                run = queue.run_queue(
                    self.tracker, root / "empty.sqlite3", source="indeed",
                    generator=rebuild,
                    existing_generator=lambda *_: (_ for _ in ()).throw(RuntimeError(
                        "Resume Created is complete but an exact existing DOCX could not be identified; "
                        "no duplicate was generated"
                    )),
                    print_summary=False,
                )
        stored = next(data for number, data in self.tracker.scout().rows if number == row)
        self.assertEqual(generated, [])
        self.assertEqual(len(run.successes), 0)
        self.assertEqual(stored["Apply?"], "No")
        self.assertEqual(stored["Resume Created"], "X")
        self.assertEqual(stored["Resume Link"], "")

    def test_recovery_tolerates_punctuation_encoding_damage_and_qa_timestamp(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "input" / "job-descriptions"
            archive.mkdir(parents=True)
            listing = archive / "Tinoco+scout-1969.md"
            listing.write_text(
                "# Performance Creative Manager – Bilingual Social Media Advertising\n\n"
                "- **Company:** Tinoco Enterprises LLC\n"
                "- **Job Number:** scout-1969\n- **Scout ID:** 1969\n",
                encoding="utf-8",
            )
            item = queue.QueueRow(
                1140, 1969, "Tinoco Enterprises LLC",
                "Performance Creative Manager � Bilingual Social Media Advertising",
            )
            output = root / "output" / "resumes"
            output.mkdir(parents=True)
            resume = output / "Dave-Call+Tinoco--LLC+Performance-Creative-Manager.docx"
            resume.write_bytes(b"validated legacy docx")
            stamp = 1_800_000_000
            os.utime(resume, (stamp, stamp))
            scratch = root / "scratch" / "Tinoco-Enterprises-LLC+scout-1969"
            scratch.mkdir(parents=True)
            (scratch / "validation-status.json").write_text(
                '{"status":"native-valid","validated_at":"2027-01-15T03:59:55+00:00"}',
                encoding="utf-8",
            )
            plan = {
                "job": {
                    "company": "Tinoco Enterprises LLC",
                    "safe_company": "Tinoco-Enterprises-LLC",
                    "title": "Performance Creative Manager – Bilingual Social Media Advertising",
                    "job_number": "scout-1969",
                }
            }
            # Align the synthetic artifact time exactly with the validation record.
            validated = queue.datetime.fromisoformat("2027-01-15T03:59:55+00:00").timestamp()
            os.utime(resume, (validated, validated))
            with patch.object(queue, "ROOT", root):
                self.assertEqual(queue._saved_listing(item), listing)
                self.assertEqual(queue._find_existing_resume(plan, scratch), resume)

    def test_generation_failure_keeps_row_retryable_without_x(self):
        row = self.add_scout_row(
            apply="Yes", location="Sandy, UT", listing="Lead content marketing programs."
        )
        with TemporaryDirectory() as temp:
            queue.run_queue(
                self.tracker, Path(temp) / "empty.sqlite3", source="indeed",
                generator=lambda item, db: (_ for _ in ()).throw(RuntimeError("generation failed")),
                print_summary=False,
            )
        stored = next(data for number, data in self.tracker.scout(
            value_render_option="FORMULA").rows if number == row)
        self.assertEqual(stored["Resume Created"], "")
        self.assertEqual(stored["Resume Link"], "")
        self.assertIn("generation failed", stored["Notes"])

    def test_dry_run_has_zero_writes_generation_or_upload_and_reports_plans(self):
        self.add_scout_row(
            apply="", location="South Jordan, UT",
            listing="Lead integrated marketing campaigns.",
        )
        generated = []
        uploaded = []
        output = io.StringIO()
        with redirect_stdout(output):
            queue.run_queue(
                self.tracker, Path("unused.sqlite3"), source="indeed", dry_run=True,
                generator=lambda *args: generated.append(args),
                recorder=lambda *args: uploaded.append(args),
            )
        self.assertEqual(self.fake.writes, [])
        self.assertEqual(generated, [])
        self.assertEqual(uploaded, [])
        self.assertIn("WOULD SET APPLY? = Yes", output.getvalue())
        self.assertIn("WOULD ASSIGN SCOUT ID", output.getvalue())

    def test_manual_indeed_row_without_database_record_uses_sheet_context(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            item = queue.QueueRow(
                2, 812, "Manual Company", "Growth Marketing Director",
                "https://www.indeed.com/viewjob?jk=manual-812", "Indeed",
                {"Location": "Remote", "Work Arrangement": "Remote"},
            )
            expected = queue.Artifacts(root / "resume.docx", root / "listing.md")
            with patch.object(queue, "ROOT", root), patch.object(
                queue, "_finish_generation", return_value=expected
            ) as finish:
                actual = queue.generate(item, root / "empty.sqlite3")

            self.assertEqual(actual, expected)
            listing = finish.call_args.args[1]
            self.assertTrue(listing.is_file())
            content = listing.read_text(encoding="utf-8")
            self.assertIn("**Scout ID:** 812", content)
            self.assertIn("Growth Marketing Director", content)

    def test_description_failure_leaves_row_unprocessed_and_logs_attempts(self):
        item = queue.read_queue(self.tracker).pending[0]
        attempt = queue.RetrievalAttempt(
            "original aggregator URL", item.job_url, "failed", "HTTP Error 403: Forbidden"
        )
        result = queue.DescriptionRetrievalResult(
            "failed", attempts=[attempt], authoritative_url="https://careers.example.test/job",
            error="No source produced a complete description.",
        )
        recorded = []
        messages = []
        with TemporaryDirectory() as temp, patch.object(queue, "ROOT", Path(temp)):
            def generate(candidate, _db):
                if candidate.scout_id == item.scout_id:
                    raise queue.DescriptionUnavailableError(result, candidate.job_url)
                raise RuntimeError("second simulated failure")

            run = queue.run_queue(
                self.tracker, Path("unused.sqlite3"), generator=generate,
                recorder=lambda *args: recorded.append(args),
                logger=messages.append,
            )
        self.assertEqual(run.exit_code, 1)
        self.assertEqual(recorded, [])
        self.assertTrue(any("HTTP Error 403" in message for message in messages))
        self.assertFalse((Path(temp) / "output/apply-queue-results.md").exists())
        scout = next(data for _, data in self.tracker.scout().rows if str(data.get("Scout ID")) == "42")
        self.assertEqual(scout["Resume Created"], "")
        self.assertEqual(scout["Resume Link"], "")

    def test_daily_scope_processes_only_new_ids_and_respects_apply_and_existing_marker(self):
        processed = []
        with TemporaryDirectory() as temp:
            temp = Path(temp)

            def generate(item, _db):
                processed.append(item.scout_id)
                return queue.Artifacts(temp / "resume.docx", temp / "listing.md")

            run = queue.run_queue(
                self.tracker, Path("unused.sqlite3"), eligible_scout_ids={43, 44, 45},
                generator=generate,
                recorder=lambda item, *_: queue.manage_job_tracker.mark_batch_resume(
                    item.scout_id, item.row, self.tracker,
                    f"https://drive.google.test/{item.scout_id}"
                ),
            )
        self.assertEqual(processed, [45])
        self.assertEqual([item.scout_id for item in run.snapshot.already_created], [43])
        self.assertEqual([item.scout_id for item in run.snapshot.not_approved], [44])

    def test_jooble_row_is_eligible_when_user_marks_yes(self):
        row = [47, "Jooble", "Blocked", "Paid Search Manager", "New", "Yes", "", "", ""]
        while len(row) < len(SCOUT):
            row.append("")
        row[SCOUT.index("Job URL")] = "https://www.jooble.org/jobs/123"
        self.fake.data["Job Scout"].append(row)
        snapshot = queue.read_queue(self.tracker, {47})
        self.assertEqual([item.scout_id for item in snapshot.pending], [47])
        self.assertEqual(snapshot.jooble_excluded, [])

    def test_rerun_skips_rows_marked_x(self):
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "resume.docx"
            resume.write_bytes(b"docx")
            generated = []

            def generator(item, _db):
                generated.append(item.scout_id)
                return queue.Artifacts(resume, Path("listing.md"))

            first = queue.run_queue(
                self.tracker, Path("unused.sqlite3"), generator=generator,
                recorder=lambda item, *_: queue.manage_job_tracker.mark_batch_resume(
                    item.scout_id, item.row, self.tracker,
                    f"https://drive.google.test/{item.scout_id}"
                ), print_summary=False,
            )
            second = queue.run_queue(
                self.tracker, Path("unused.sqlite3"), generator=generator,
                recorder=lambda *_: self.fail("completed row was processed again"),
                print_summary=False,
            )
        self.assertEqual(len(first.successes), 3)
        self.assertEqual(second.snapshot.pending, [])
        self.assertEqual(second.snapshot.link_backfill, [])

    def test_indeed_rerun_skips_x_with_persistent_link(self):
        row = self.add_scout_row(
            scout_id=920, source="Indeed", company="Repeat Company",
            apply="", location="Ogden, UT", listing="Lead growth marketing programs.",
        )
        generated = []
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "resume.docx"
            resume.write_bytes(b"validated docx")

            def generator(item, _db):
                generated.append(item.scout_id)
                return queue.Artifacts(resume, Path("listing.md"))

            recorder = lambda item, *_: queue.manage_job_tracker.mark_batch_resume(
                item.scout_id, item.row, self.tracker,
                "https://drive.google.test/repeat-920", completion_marker="X",
            )
            first = queue.run_queue(
                self.tracker, Path(temp) / "empty.sqlite3", source="indeed",
                generator=generator, recorder=recorder, print_summary=False,
            )
            second = queue.run_queue(
                self.tracker, Path(temp) / "empty.sqlite3", source="indeed",
                generator=lambda *_: self.fail("completed Indeed row was regenerated"),
                recorder=lambda *_: self.fail("completed Indeed row was rewritten"),
                print_summary=False,
            )
        stored = next(data for number, data in self.tracker.scout().rows if number == row)
        self.assertEqual(len(first.successes), 1)
        self.assertEqual(generated, [920])
        self.assertEqual(stored["Apply?"], "Yes")
        self.assertEqual(stored["Resume Created"], "X")
        self.assertEqual(second.snapshot.pending, [])
        self.assertEqual(second.snapshot.link_backfill, [])

    def test_legacy_open_resume_formula_is_repair_eligible(self):
        row = self.add_scout_row(
            scout_id=921, source="Indeed", company="Legacy Company",
            apply="Yes", created="C", location="Denver, CO", arrangement="Onsite",
        )
        self.fake.data["Job Scout"][row - 1][SCOUT.index("Resume Link")] = (
            '=HYPERLINK("https://drive.google.test/legacy-921","Open Resume")'
        )
        run = queue.run_queue(
            self.tracker, Path("unused.sqlite3"), source="indeed", dry_run=True,
            generator=lambda *_: self.fail("legacy completed row was generated"),
            recorder=lambda *_: self.fail("legacy completed row was rewritten"),
            print_summary=False,
        )
        self.assertNotIn(row, [item.row for item in run.snapshot.already_created])
        self.assertIn(row, [item.row for item in run.snapshot.link_backfill])

    def test_x_with_blank_s_backfills_existing_without_generating_duplicate(self):
        row = self.fake.data["Job Scout"][1]
        row[SCOUT.index("Resume Created")] = "X"
        generated = []
        recovered = []
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "existing.docx"
            resume.write_bytes(b"docx")

            def existing(item, _db):
                recovered.append(item.scout_id)
                return queue.Artifacts(resume, Path("listing.md"), existing=True)

            run = queue.run_queue(
                self.tracker, Path("unused.sqlite3"), eligible_scout_ids=set(),
                generator=lambda *args: generated.append(args), existing_generator=existing,
                recorder=lambda item, *_: queue.manage_job_tracker.mark_batch_resume(
                    item.scout_id, item.row, self.tracker,
                    f"https://drive.google.test/{item.scout_id}"
                ), print_summary=False,
            )
        self.assertEqual(generated, [])
        self.assertEqual(recovered, [42])
        self.assertEqual(run.recovered, 1)
        self.assertTrue(queue._valid_resume_link(
            self.tracker.scout(value_render_option="FORMULA").rows[0][1]["Resume Link"]
        ))

    def test_local_path_failure_leaves_g_and_s_blank(self):
        item = queue.QueueRow(2, 42, "Existing", "Role")
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "Dave-Call+Existing+Role+queue-42.docx"
            listing = Path(temp) / "Existing+queue-42.md"
            resume.write_bytes(b"docx")
            listing.write_text(
                "# Role\n\n- **Company:** Existing\n- **Job Number:** queue-42\n"
                "- **Scout ID:** 42\n", encoding="utf-8",
            )
            with patch.object(
                queue.manage_job_tracker, "publish_resume",
                side_effect=RuntimeError(
                    "Resume path could not be verified; Resume Link was not updated"
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "path could not be verified"):
                    queue.record_success(item, queue.Artifacts(resume, listing), self.tracker)
        scout = self.tracker.scout(value_render_option="FORMULA").rows[0][1]
        self.assertEqual(scout["Resume Created"], "")
        self.assertEqual(scout["Resume Link"], "")


if __name__ == "__main__":
    unittest.main()
