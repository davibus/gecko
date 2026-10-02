"""Google Drive resume storage tests without touching the live Drive."""

from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from resume_storage import GoogleDriveResumeStore


class Call:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.value


class FakeDrive:
    def __init__(self, matches=None, create_error=None):
        self.matches = list(matches or [])
        self.create_error = create_error
        self.list_kwargs = None
        self.create_kwargs = None

    def files(self):
        return self

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return Call({"files": self.matches})

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        if self.create_error:
            return Call(error=self.create_error)
        return Call({
            "id": "new-file-id",
            "webViewLink": "https://drive.google.test/file/new-file-id/view",
        })


class ResumeStorageTests(unittest.TestCase):
    def test_existing_job_identity_reuses_drive_url_without_upload(self):
        drive = FakeDrive([{
            "id": "existing-id",
            "name": "resume.docx",
            "webViewLink": "https://drive.google.test/file/existing-id/view",
        }])
        store = GoogleDriveResumeStore(Path("unused.json"), "folder-id", drive)
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "resume.docx"
            resume.write_bytes(b"docx")
            result = store.publish(resume, "job-123", scout_id=42)
        self.assertTrue(result.existing)
        self.assertIsNone(drive.create_kwargs)
        self.assertIn("geckoJobNumber", drive.list_kwargs["q"])
        self.assertNotIn("geckoScoutId", drive.list_kwargs["q"])

    def test_new_resume_upload_has_stable_properties_and_persistent_url(self):
        drive = FakeDrive()
        store = GoogleDriveResumeStore(Path("unused.json"), "folder-id", drive)
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "resume.docx"
            resume.write_bytes(b"docx")
            result = store.publish(resume, "job-123", scout_id=42)
        self.assertFalse(result.existing)
        self.assertEqual(result.url, "https://drive.google.test/file/new-file-id/view")
        self.assertEqual(drive.create_kwargs["body"]["parents"], ["folder-id"])
        self.assertEqual(drive.create_kwargs["body"]["appProperties"], {
            "geckoJobNumber": "job-123", "geckoScoutId": "42",
        })

    def test_upload_failure_is_descriptive(self):
        drive = FakeDrive(create_error=OSError("simulated upload outage"))
        store = GoogleDriveResumeStore(Path("unused.json"), "folder-id", drive)
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "resume.docx"
            resume.write_bytes(b"docx")
            with self.assertRaisesRegex(RuntimeError, "Resume Link was not updated"):
                store.publish(resume, "job-123", scout_id=42)

    def test_multiple_matches_are_rejected(self):
        drive = FakeDrive([{"id": "one"}, {"id": "two"}])
        store = GoogleDriveResumeStore(Path("unused.json"), "folder-id", drive)
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "resume.docx"
            resume.write_bytes(b"docx")
            with self.assertRaisesRegex(RuntimeError, "Multiple Google Drive resumes"):
                store.publish(resume, "job-123", scout_id=42)


if __name__ == "__main__":
    unittest.main()
