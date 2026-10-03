from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from consolidate_drive_companies import (
    DriveCleanup, HashingBuffer, Journal, allocate_collision_name, normalize_company,
    retriable_error, retry,
)


class Request:
    def __init__(self, value): self.value = value
    def execute(self): return self.value


class FakeFiles:
    def __init__(self):
        self.pages = {
            None: {"files": [{"id": "a"}], "nextPageToken": "next"},
            "next": {"files": [{"id": "b"}]},
        }
    def list(self, **kwargs): return Request(self.pages[kwargs.get("pageToken")])


class FakeService:
    def __init__(self): self.api = FakeFiles()
    def files(self): return self.api


class CleanupTests(unittest.TestCase):
    def test_content_fingerprint_covers_every_chunk(self):
        import hashlib
        stream = HashingBuffer()
        chunks = [b"alpha", b"\x00\x01", b"omega"]
        for chunk in chunks:
            stream.write(chunk)
        self.assertEqual(stream.sha256.hexdigest(), hashlib.sha256(b"".join(chunks)).hexdigest())
        self.assertEqual(stream.getvalue(), b"".join(chunks))

    def test_priority_aliases(self):
        samples = {
            "TPG": "tpg", "Travel Pass Group": "tpg", "DCALL - TPG v2": "tpg",
            "18C": "1800contacts", "1-800 Contacts": "1800contacts",
            "DCALL - GRIP6": "grip6", "GRIP6_7-13-23_and_on": "grip6",
            "stonebridge_v3": "stonebridge",
        }
        for value, expected in samples.items():
            self.assertEqual(normalize_company(value), expected, value)

    def test_unrelated_substrings_are_not_aliases(self):
        self.assertNotEqual(normalize_company("Stonebridge Partners"), "stonebridge")
        self.assertNotEqual(normalize_company("My TPG Notes"), "tpg")

    def test_collision_suffixes_are_case_insensitive_and_sparse(self):
        occupied = ["REPORT.docx", "Report+1.docx", "report+3.docx"]
        self.assertEqual(allocate_collision_name("Report.docx", occupied), "Report+2.docx")
        self.assertEqual(allocate_collision_name("Marketing Plan", ["marketing plan", "Marketing Plan+1"]),
                         "Marketing Plan+2")

    def test_full_pagination(self):
        with tempfile.TemporaryDirectory() as directory:
            cleanup = DriveCleanup(FakeService(), "root", Journal(Path(directory) / "j.jsonl"),
                                   Path(directory))
            self.assertEqual([x["id"] for x in cleanup.list_children("root")], ["a", "b"])

    def test_recursive_folder_merge_preserves_equivalent_subfolder(self):
        class MergeCleanup(DriveCleanup):
            def __init__(self, directory):
                super().__init__(FakeService(), "root", Journal(Path(directory) / "j.jsonl"),
                                 Path(directory))
                self.mapping = {
                    "source": [{"id": "source-sub", "name": "Assets", "mimeType": "application/vnd.google-apps.folder"}],
                    "dest": [{"id": "dest-sub", "name": "assets", "mimeType": "application/vnd.google-apps.folder"}],
                    "source-sub": [{"id": "file", "name": "Logo.png", "mimeType": "image/png"}],
                    "dest-sub": [],
                }
                self.moves = []
                self.empty_checks = []
            def list_children(self, folder_id): return list(self.mapping[folder_id])
            def move(self, item, source_parent, destination_parent, **kwargs):
                self.moves.append((item["id"], source_parent, destination_parent))
            def trash_empty_folder(self, folder): self.empty_checks.append(folder["id"])

        with tempfile.TemporaryDirectory() as directory:
            cleanup = MergeCleanup(directory)
            cleanup.merge_folder(
                {"id": "source", "name": "Alias", "mimeType": "application/vnd.google-apps.folder"},
                {"id": "dest", "name": "Canonical", "mimeType": "application/vnd.google-apps.folder"},
            )
            self.assertEqual(cleanup.moves, [("file", "source-sub", "dest-sub")])
            self.assertEqual(cleanup.empty_checks, ["source-sub"])

    def test_journal_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.jsonl"
            journal = Journal(path)
            journal.append({"operation_id": "move:1", "phase": "before", "action": "move"})
            self.assertFalse(journal.done("move:1"))
            journal.append({"operation_id": "move:1", "phase": "after", "status": "confirmed",
                            "action": "move"})
            self.assertTrue(Journal(path).done("move:1"))

    def test_read_timeout_is_retried(self):
        calls = 0
        def flaky():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise TimeoutError("The read operation timed out")
            return "ok"
        with patch("consolidate_drive_companies.time.sleep"):
            self.assertEqual(retry(flaky), "ok")
        self.assertEqual(calls, 3)
        self.assertTrue(retriable_error(TimeoutError("read operation timed out")))

    def test_mutation_timeout_readback_prevents_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            cleanup = DriveCleanup(FakeService(), "root", Journal(Path(directory) / "j.jsonl"),
                                   Path(directory))
            calls = 0
            def mutation():
                nonlocal calls
                calls += 1
                raise TimeoutError("The read operation timed out")
            result = cleanup.mutation_with_readback(
                mutation, lambda: {"parents": ["destination"], "name": "Report+1.docx"},
                lambda value: value["parents"] == ["destination"],
                lambda value: value["parents"] == ["source"],
            )
            self.assertEqual(result["name"], "Report+1.docx")
            self.assertEqual(calls, 1)

    def test_mutation_failed_readback_stops_without_retrying_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            cleanup = DriveCleanup(FakeService(), "root", Journal(Path(directory) / "j.jsonl"),
                                   Path(directory))
            mutation_calls = 0

            def mutation():
                nonlocal mutation_calls
                mutation_calls += 1
                raise TimeoutError("The read operation timed out")

            def failed_readback():
                raise TimeoutError("The read operation timed out")

            with patch("consolidate_drive_companies.time.sleep"):
                with self.assertRaisesRegex(RuntimeError, "fresh readback failed"):
                    cleanup.mutation_with_readback(
                        mutation, failed_readback,
                        lambda value: value.get("state") == "after",
                        lambda value: value.get("state") == "before",
                    )
            self.assertEqual(mutation_calls, 1)

    def test_mutation_ambiguous_readback_stops_without_retrying_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            cleanup = DriveCleanup(FakeService(), "root", Journal(Path(directory) / "j.jsonl"),
                                   Path(directory))
            mutation_calls = 0

            def mutation():
                nonlocal mutation_calls
                mutation_calls += 1
                raise TimeoutError("The read operation timed out")

            with self.assertRaisesRegex(RuntimeError, "outcome is ambiguous"):
                cleanup.mutation_with_readback(
                    mutation, lambda: {"state": "changed-by-someone-else"},
                    lambda value: value.get("state") == "after",
                    lambda value: value.get("state") == "before",
                )
            self.assertEqual(mutation_calls, 1)

    def test_pending_move_is_reconciled_from_readback(self):
        class ReadbackFiles(FakeFiles):
            def get(self, **kwargs):
                return Request({"id": "file", "name": "Report+1.docx",
                                "parents": ["destination"], "trashed": False, "version": "2"})
        class ReadbackService:
            def __init__(self): self.api = ReadbackFiles()
            def files(self): return self.api

        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(Path(directory) / "j.jsonl")
            journal.append({"operation_id": "move:file:source:destination", "phase": "before",
                            "action": "move", "file_id": "file", "source_parent": "source",
                            "destination_parent": "destination", "target_name": "Report+1.docx",
                            "before": {"name": "Report.docx", "parents": ["source"]}})
            cleanup = DriveCleanup(ReadbackService(), "root", journal, Path(directory))
            self.assertEqual(cleanup.reconcile_pending_journal(), {"recovered": 1, "retryable": 0})
            recovered = Journal(journal.path).completed["move:file:source:destination"]
            self.assertTrue(recovered["recovered"])
            self.assertEqual(recovered["final"]["parents"], ["destination"])

    def test_changed_file_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            cleanup = DriveCleanup(FakeService(), "root", Journal(Path(directory) / "j.jsonl"),
                                   Path(directory))
            before = {"id": "a", "version": "1", "size": "2", "parents": ["x"]}
            self.assertFalse(cleanup.changed(before, dict(before)))
            after = dict(before, version="2")
            self.assertTrue(cleanup.changed(before, after))

    def test_known_shortcut_reference_blocks_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            cleanup = DriveCleanup(FakeService(), "root", Journal(Path(directory) / "j.jsonl"),
                                   Path(directory))
            cleanup.inventory.items = {
                "target": {"id": "target", "mimeType": "application/pdf"},
                "shortcut": {"id": "shortcut", "mimeType": "application/vnd.google-apps.shortcut",
                             "shortcutDetails": {"targetId": "target"}},
            }
            self.assertEqual(cleanup.known_shortcut_references("target"), ["shortcut"])


if __name__ == "__main__":
    unittest.main()
