"""Read-only schema inspection tests with no Google API access."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import inspect_tracker_schema


class InventoryTests(unittest.TestCase):
    def test_spreadsheet_access_failure_stops_inventory(self):
        class OfflineTracker:
            config = SimpleNamespace(spreadsheet_id="test")

            class Api:
                def get(self, **kwargs):
                    raise OSError("offline")

            api = Api()

        with self.assertRaisesRegex(OSError, "offline"):
            inspect_tracker_schema.inventory(OfflineTracker())

    def test_unknown_tab_is_reported_without_a_writer(self):
        class FakeTracker:
            config = SimpleNamespace(spreadsheet_id="test", scout_tab="Job Scout")

            class Api:
                def get(self, **kwargs):
                    return SimpleNamespace(execute=lambda: {"properties": {"title": "Gecko Job Tracker"}})

            api = Api()

            def discover_workbook(self, *, required):
                self.required = required
                return {
                    "Job Scout": {"sheet_id": 1, "role": "required", "hidden": False,
                                  "header_row": 1, "physical_headers": ["ID"], "grid": {}},
                    "Rejected Jobs": {"sheet_id": 2, "role": "required", "hidden": True,
                                      "header_row": 1, "physical_headers": ["Source"], "grid": {}},
                    "Mystery": {"sheet_id": 3, "role": "unassigned", "hidden": False,
                                "header_row": None, "physical_headers": [], "grid": {}},
                }

            def scout(self):
                return SimpleNamespace(rows=[(2, {"ID": 1})])

        fake = FakeTracker()
        result = inspect_tracker_schema.inventory(fake)
        self.assertEqual(result["tabs"][2]["role"], "unassigned")
        self.assertEqual(result["tabs"][0]["row_count"], 1)
        self.assertFalse(result["validation"]["daily_tasks_present"])


if __name__ == "__main__":
    unittest.main()
