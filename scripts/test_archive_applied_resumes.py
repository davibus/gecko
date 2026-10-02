"""Tests for preview-first applied-resume archival."""

from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "job-scout"))

import archive_applied_resumes as archive
from google_tracker import Config, Tab


class FakeTracker:
    def __init__(self, cells: dict[tuple[int, int], str]):
        self.cells = cells
        self.config = Config("test", Path("unused.json"), "Job Tracker", "Job Scout")


def make_tab(rows, *, applied_column: int = 8, link_column: int = 17) -> Tab:
    return Tab(
        "Job Scout",
        1,
        {"Company": 3, "Applied": applied_column, "Resume Link": link_column},
        rows,
        100,
    )


class ArchiveAppliedResumesTests(unittest.TestCase):
    def test_plan_selects_only_exact_x_and_does_not_create_folder(self):
        with TemporaryDirectory() as temp:
            resume_dir = Path(temp).resolve()
            applied_dir = resume_dir / "applied"
            selected = resume_dir / "Dave-Call+Selected+job-1.docx"
            ignored = resume_dir / "Dave-Call+Ignored+job-2.docx"
            selected.write_bytes(b"docx")
            ignored.write_bytes(b"docx")
            tab = make_tab([
                (2, {"Company": "Selected", "Applied": " x ", "Resume Link": selected.as_uri()}),
                (3, {"Company": "Ignored", "Applied": True, "Resume Link": ignored.as_uri()}),
            ])
            plan = archive.build_plan(
                tab, resume_dir=resume_dir, applied_dir=applied_dir
            )
            self.assertEqual([item.row for item in plan.moves], [2])
            self.assertEqual(plan.moves[0].new_uri, (applied_dir / selected.name).as_uri())
            self.assertFalse(applied_dir.exists())
            self.assertTrue(selected.exists())

    def test_plan_reports_blank_missing_outside_and_collision_without_changes(self):
        with TemporaryDirectory() as temp, TemporaryDirectory() as outside_temp:
            resume_dir = Path(temp).resolve()
            applied_dir = resume_dir / "applied"
            applied_dir.mkdir()
            collision = resume_dir / "collision.docx"
            collision.write_bytes(b"source")
            (applied_dir / collision.name).write_bytes(b"destination")
            missing = resume_dir / "missing.docx"
            outside = Path(outside_temp).resolve() / "outside.docx"
            outside.write_bytes(b"docx")
            tab = make_tab([
                (2, {"Company": "Blank", "Applied": "x", "Resume Link": ""}),
                (3, {"Company": "Missing", "Applied": "x", "Resume Link": missing.as_uri()}),
                (4, {"Company": "Outside", "Applied": "x", "Resume Link": outside.as_uri()}),
                (5, {"Company": "Collision", "Applied": "x", "Resume Link": collision.as_uri()}),
            ])
            plan = archive.build_plan(
                tab, resume_dir=resume_dir, applied_dir=applied_dir
            )
            self.assertEqual(len(plan.moves), 0)
            self.assertEqual(len(plan.issues), 4)
            self.assertTrue(collision.exists())
            self.assertTrue(outside.exists())

    def test_plan_requires_applied_in_column_h(self):
        with self.assertRaisesRegex(RuntimeError, "expected Column H"):
            archive.build_plan(make_tab([], applied_column=9))

    def test_apply_moves_file_updates_only_link_and_verifies(self):
        with TemporaryDirectory() as temp:
            resume_dir = Path(temp).resolve()
            applied_dir = resume_dir / "applied"
            source = resume_dir / "Dave-Call+Example+job-1.docx"
            source.write_bytes(b"docx")
            tab = make_tab([
                (2, {"Company": "Example", "Applied": "x", "Resume Link": source.as_uri()}),
            ])
            plan = archive.build_plan(
                tab, resume_dir=resume_dir, applied_dir=applied_dir
            )
            tracker = FakeTracker({(8, 2): "x", (17, 2): source.as_uri()})

            def read_cell(_tracker, _worksheet, column, row):
                return tracker.cells[(column, row)]

            def write_cell(_tracker, _worksheet, column, row, value):
                tracker.cells[(column, row)] = value

            preflight = {2: ("x", source.as_uri())}
            with patch.object(archive, "_read_preflight_values", return_value=preflight), \
                 patch.object(archive, "_read_cell", side_effect=read_cell), \
                 patch.object(archive, "_write_cell", side_effect=write_cell):
                completed = archive.apply_plan(
                    tracker, plan, applied_dir=applied_dir
                )

            self.assertEqual(len(completed), 1)
            self.assertFalse(source.exists())
            self.assertTrue(plan.moves[0].destination.is_file())
            self.assertEqual(tracker.cells[(8, 2)], "x")
            self.assertEqual(tracker.cells[(17, 2)], plan.moves[0].new_uri)

    def test_apply_rolls_file_back_when_sheet_write_fails(self):
        with TemporaryDirectory() as temp:
            resume_dir = Path(temp).resolve()
            applied_dir = resume_dir / "applied"
            source = resume_dir / "Dave-Call+Example+job-1.docx"
            source.write_bytes(b"docx")
            tab = make_tab([
                (2, {"Company": "Example", "Applied": "x", "Resume Link": source.as_uri()}),
            ])
            plan = archive.build_plan(
                tab, resume_dir=resume_dir, applied_dir=applied_dir
            )
            tracker = FakeTracker({(8, 2): "x", (17, 2): source.as_uri()})

            def read_cell(_tracker, _worksheet, column, row):
                return tracker.cells[(column, row)]

            preflight = {2: ("x", source.as_uri())}
            with patch.object(archive, "_read_preflight_values", return_value=preflight), \
                 patch.object(archive, "_read_cell", side_effect=read_cell), \
                 patch.object(archive, "_write_cell", side_effect=OSError("simulated outage")):
                with self.assertRaisesRegex(RuntimeError, "simulated outage"):
                    archive.apply_plan(tracker, plan, applied_dir=applied_dir)

            self.assertTrue(source.is_file())
            self.assertFalse(plan.moves[0].destination.exists())
            self.assertEqual(tracker.cells[(17, 2)], source.as_uri())


if __name__ == "__main__":
    unittest.main()
