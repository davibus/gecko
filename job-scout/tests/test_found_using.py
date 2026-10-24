"""Discovery provenance contracts, using isolated SQLite and fake Sheets only."""
from pathlib import Path
from contextlib import closing
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from google_tracker import Config, GoogleTracker
from models import RawListing
from normalize import normalize
from storage import JobStore
from sheet_sync import merge_rows, SyncConflict
from tests.test_google_tracker import FakeSheets


def listing(tool="Gecko", key="new"):
    return normalize(RawListing(
        "indeed", key, f"https://example.test/{key}", "Product Manager", "Example",
        location="Remote", metadata={"_retrieved_via": "firecrawl"} if tool == "Firecrawl" else {}))


class FoundUsingTests(unittest.TestCase):
    def tracker(self, position=5, existing=""):
        fake = FakeSheets()
        for row in fake.data["Job Scout"]:
            row.insert(position, "Found Using" if row is fake.data["Job Scout"][0] else existing)
        tracker = GoogleTracker(Config("test", Path("unused"), "Job Tracker", "Job Scout"), fake)
        return tracker, fake

    def test_new_sources_follow_moved_header_and_read_back(self):
        for position in (0, 5, 21):
            for tool in ("Gecko", "Firecrawl"):
                with self.subTest(position=position, tool=tool):
                    tracker, fake = self.tracker(position)
                    before = list(fake.data["Job Scout"][1])
                    job = listing(tool); job.id = 100
                    tracker.upsert_scout([job])
                    self.assertEqual(dict(tracker.scout().rows)[3]["Found Using"], tool)
                    self.assertEqual(fake.data["Job Scout"][1], before)

    def test_rediscovery_preserves_original_manual_and_historical_blank(self):
        for original in ("Gecko", "Firecrawl", "Dave's referral", ""):
            with self.subTest(original=original):
                tracker, _ = self.tracker(existing=original)
                job = listing("Firecrawl"); job.id = 42; job.url = job.canonical_url = "https://example.test/job"
                tracker.upsert_scout([job])
                self.assertEqual(dict(tracker.scout().rows)[2]["Found Using"], original)

    def test_same_batch_duplicate_keeps_first_source(self):
        for first in ("Gecko", "Firecrawl"):
            tracker, _ = self.tracker()
            a = listing(first); a.id = 100
            b = listing("Firecrawl" if first == "Gecko" else "Gecko"); b.id = 101
            tracker.upsert_scout([a, b])
            rows = tracker.scout().rows
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1][1]["Found Using"], first)

    def test_formula_and_concurrent_manual_value_are_protected(self):
        tracker, fake = self.tracker(existing='="Referral"')
        tab = tracker.scout()
        tracker._write(tab, 2, {"Found Using": "Gecko"})
        self.assertEqual(fake.data["Job Scout"][1][5], '="Referral"')
        fake.data["Job Scout"][1][5] = "Manual referral"
        tracker._write(tab, 2, {"Found Using": "Firecrawl"})
        self.assertEqual(dict(tracker.scout().rows)[2]["Found Using"], "Manual referral")

    def test_storage_reopen_merge_and_upsert_keep_first_source(self):
        for first in ("Gecko", "Firecrawl"):
            with TemporaryDirectory() as folder:
                path = Path(folder) / "jobs.sqlite3"
                with JobStore(path) as store:
                    job = listing(first); job.id = store.save(job)
                    other = listing("Firecrawl" if first == "Gecko" else "Gecko")
                    store.merge(job.id, other)
                    store.save(other)
                with JobStore(path) as store:
                    self.assertEqual(store.get(job.id).found_using, first)

    def test_migration_preserves_unknown_historical_source(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "jobs.sqlite3"
            with JobStore(path) as store:
                job = listing(); job.id = store.save(job)
            with closing(sqlite3.connect(path)) as con:
                with con:
                    con.execute("ALTER TABLE jobs DROP COLUMN found_using")
            with JobStore(path) as store:
                self.assertEqual(store.get(job.id).found_using, "")

    def test_sync_carries_new_source_and_preserves_sheet_manual_edit(self):
        headers = ["Found Using", "ID", "Resume Link"]
        new = {"1": {"ID": 1, "Found Using": "Firecrawl", "Resume Link": ""}}
        self.assertEqual(merge_rows({}, new, {}, headers), new)
        base = {"1": {"ID": 1, "Found Using": "Gecko", "Resume Link": "file:///resume.docx"}}
        manual = {"1": {**base["1"], "Found Using": "Referral"}}
        self.assertEqual(merge_rows(base, base, manual, headers), manual)
        with self.assertRaises(SyncConflict):
            merge_rows(base, new, manual, headers)


if __name__ == "__main__":
    unittest.main()
