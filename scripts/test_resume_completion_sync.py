"""Resume completion publishes to the configured primary Sheet, with no live I/O."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
import generate_apply_queue as queue
from sqlite_tracker import SQLiteTracker
import sheet_sync
class CompletionSyncTests(unittest.TestCase):
    def setUp(self):self.local=object.__new__(SQLiteTracker)
    def test_verified_local_completion_publishes(self):
        with patch.object(sheet_sync,'enabled',return_value=True),patch.object(sheet_sync,'sync') as sync:
            queue.sync_completed_resume_to_primary_sheet(self.local)
            sync.assert_called_once_with()
    def test_disabled_primary_does_not_publish(self):
        with patch.object(sheet_sync,'enabled',return_value=False),patch.object(sheet_sync,'sync') as sync:
            queue.sync_completed_resume_to_primary_sheet(self.local)
            sync.assert_not_called()
    def test_direct_sheet_writer_does_not_resync(self):
        with patch.object(sheet_sync,'sync') as sync:
            queue.sync_completed_resume_to_primary_sheet(object())
            sync.assert_not_called()
    def test_sync_failure_is_recorded_and_reported(self):
        failure=RuntimeError('conflicting edit')
        with patch.object(sheet_sync,'enabled',return_value=True),patch.object(sheet_sync,'sync',side_effect=failure),patch.object(sheet_sync,'record_error') as record:
            with self.assertRaisesRegex(RuntimeError,'conflicting edit'):
                queue.sync_completed_resume_to_primary_sheet(self.local)
            record.assert_called_once_with(failure)
if __name__=='__main__':unittest.main()
