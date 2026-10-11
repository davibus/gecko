"""Focused safety tests for the explicit Cursor instruction cell sync."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("sync_cursor_instructions.py")
spec = importlib.util.spec_from_file_location("cursor_sheet_sync", SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class Request:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeValues:
    def __init__(self, value):
        self.value = value
        self.writes = []

    def get(self, **_kwargs):
        return Request({"values": [[self.value]]} if self.value else {})

    def update(self, **kwargs):
        self.writes.append(kwargs)
        self.value = kwargs["body"]["values"][0][0]
        return Request({})


class FakeApi:
    def __init__(self, value):
        self.cells = FakeValues(value)

    def values(self):
        return self.cells

    def get(self, **_kwargs):
        return Request({"sheets": [{"properties": {"title": "Instructions", "sheetId": 5,
                                                "gridProperties": {"rowCount": 10, "columnCount": 3}}}]})


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "gecko.mdc"
        self.file.write_text("cursor version", encoding="utf-8")
        self.api = FakeApi("sheet version")
        self.state = Path(self.temp.name) / "state.json"
        self.patches = [patch.object(sync, "local_file", return_value=self.file),
                        patch.object(sync, "state_path", return_value=self.state),
                        patch.object(sync, "STATE_DIR", Path(self.temp.name))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def args(self, direction, apply=False, expected=None):
        return argparse.Namespace(command=direction, file="gecko.mdc", tab="Instructions",
                                  sheet_id=5, cell="A1", apply=apply,
                                  expect_destination_sha256=expected)

    def test_initial_divergence_requires_exact_target_hash(self):
        result = sync.run(self.args("cursor-to-sheets", apply=True), self.api, "book")
        self.assertEqual(result, "conflict")
        self.assertEqual(self.api.cells.value, "sheet version")
        self.assertEqual(self.api.cells.writes, [])

    def test_write_has_backup_and_readback(self):
        expected = sync.digest("sheet version")
        result = sync.run(self.args("cursor-to-sheets", apply=True, expected=expected),
                          self.api, "book")
        self.assertEqual(result, "synced")
        self.assertEqual(self.api.cells.value, "cursor version")
        self.assertEqual(self.state.exists(), True)
        self.assertEqual(len(list((Path(self.temp.name) / "backups").glob("*.json"))), 1)

    def test_changed_destination_blocks_followup(self):
        self.state.write_text('{"spreadsheet_id":"book","content_sha256":"' +
                              sync.digest("sheet version") + '"}', encoding="utf-8")
        self.api.cells.value = "human update"
        result = sync.run(self.args("cursor-to-sheets", apply=True), self.api, "book")
        self.assertEqual(result, "conflict")
        self.assertEqual(self.api.cells.writes, [])

    def test_sheet_to_cursor_preserves_file_without_explicit_hash(self):
        result = sync.run(self.args("sheets-to-cursor", apply=True), self.api, "book")
        self.assertEqual(result, "conflict")
        self.assertEqual(self.file.read_text(encoding="utf-8"), "cursor version")

    def test_sheet_to_cursor_writes_and_then_is_idempotent(self):
        expected = sync.digest("cursor version")
        result = sync.run(self.args("sheets-to-cursor", apply=True, expected=expected),
                          self.api, "book")
        self.assertEqual(result, "synced")
        self.assertEqual(self.file.read_text(encoding="utf-8"), "sheet version")
        self.assertEqual(sync.run(self.args("sheets-to-cursor", apply=True),
                                  self.api, "book"), "equal")
        self.assertEqual(self.api.cells.writes, [])

    def test_formula_is_protected(self):
        self.api.cells.value = "=A2"
        with self.assertRaisesRegex(ValueError, "formula"):
            sync.run(self.args("cursor-to-sheets", apply=True), self.api, "book")
        self.assertEqual(self.api.cells.writes, [])

    def test_wrong_tab_id_is_protected(self):
        args = self.args("cursor-to-sheets", apply=True)
        args.sheet_id = 6
        with self.assertRaisesRegex(ValueError, "Tab title and sheet ID"):
            sync.run(args, self.api, "book")
        self.assertEqual(self.api.cells.writes, [])

    def test_watcher_syncs_only_changed_cursor_side(self):
        sync.save_baseline(self.state, "book", "sheet version")
        result = sync.watch_once(self.args("watch"), self.api, "book")
        self.assertEqual(result, "cursor-to-sheets")
        self.assertEqual(self.api.cells.value, "cursor version")
        self.assertEqual(sync.watch_once(self.args("watch"), self.api, "book"), "equal")

    def test_watcher_syncs_only_changed_sheet_side(self):
        sync.save_baseline(self.state, "book", "cursor version")
        result = sync.watch_once(self.args("watch"), self.api, "book")
        self.assertEqual(result, "sheets-to-cursor")
        self.assertEqual(self.file.read_text(encoding="utf-8"), "sheet version")

    def test_watcher_preserves_independent_edits(self):
        sync.save_baseline(self.state, "book", "older version")
        result = sync.watch_once(self.args("watch"), self.api, "book")
        self.assertEqual(result, "conflict")
        self.assertEqual(self.api.cells.value, "sheet version")
        self.assertEqual(self.file.read_text(encoding="utf-8"), "cursor version")
        self.assertEqual(self.api.cells.writes, [])


if __name__ == "__main__":
    unittest.main()
