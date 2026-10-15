"""Focused approval reconciliation tests; no Google Sheets access."""

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "job-scout")]
from reconcile_cost_approval import plan


class ApprovalReconciliationTests(unittest.TestCase):
    def test_blank_cost_approved_and_protections_preserved(self):
        header = ("ID", "Source", "Company", "Job Title", "Apply?", "Resume Created",
                  "Applied", "Cost", "Notes", "Apply or on Company Website (If Indeed)",
                  "Response", "Location", "Work Arrangement", "Employment Type", "Salary",
                  "Job URL", "Resume Link")
        def row(identity, **changes):
            value = {name: "" for name in header}
            value.update({"ID": str(identity), "Source": "test", "Company": "Acme",
                          "Job Title": "Role", "Apply?": "No", "Location": "Utah",
                          "Work Arrangement": "On-site", "Job URL": f"https://example.test/{identity}"})
            value.update(changes)
            return value
        rows = [
            (2, row(1)),
            (3, row(2, Cost=" x ", **{"Apply?": "Yes"})),
            (4, row(3, Applied="X")),
            (5, row(4, Notes="Invalid Link")),
            (6, row(5, **{"Apply or on Company Website (If Indeed)": "Expired"})),
            (7, row(6, **{"Resume Created": " X "})),
            (8, row(7, **{"Apply?": "Reject", "Cost": "x"})),
        ]
        tab = SimpleNamespace(rows=rows, raw_rows={n: tuple(d.values()) for n, d in rows},
                              headers={name: i for i, name in enumerate(header, 1)})
        store = SimpleNamespace(get=lambda identity: SimpleNamespace(status="new"))
        rejected = SimpleNamespace(matches_job=lambda job: None)
        provenance = {(n, d["ID"]) for n, d in rows}
        changes, reasons = plan(tab, tab.raw_rows, store, rejected, provenance)
        self.assertEqual([(x["row"], x["new"]) for x in changes], [(2, "Yes"), (3, "No"), (7, "Yes")])
        self.assertEqual(reasons["already_applied"], 1)
        self.assertEqual(reasons["rejected_or_invalid_note"], 1)
        self.assertEqual(reasons["expired_or_other_application_status"], 1)
        self.assertEqual(reasons["rejection_marker_preserved"], 1)

    def test_formula_approval_cell_is_protected(self):
        row = {"ID": "1", "Source": "test", "Company": "Acme", "Job Title": "Role",
               "Apply?": "No", "Cost": "", "Notes": "", "Location": "Utah",
               "Work Arrangement": "On-site", "Job URL": "https://example.test/1",
               "Applied": "", "Apply or on Company Website (If Indeed)": ""}
        headers = {name: i for i, name in enumerate(row, 1)}
        raw = list(row.values())
        raw[headers["Apply?"] - 1] = '=IF(TRUE,"No","")'
        tab = SimpleNamespace(rows=[(2, row)], raw_rows={2: tuple(raw)}, headers=headers)
        store = SimpleNamespace(get=lambda identity: SimpleNamespace(status="new"))
        rejected = SimpleNamespace(matches_job=lambda job: None)
        changes, reasons = plan(tab, tab.raw_rows, store, rejected, {(2, "1")})
        self.assertEqual(changes, [])
        self.assertEqual(reasons["formula_protected"], 1)


if __name__ == "__main__":
    unittest.main()
