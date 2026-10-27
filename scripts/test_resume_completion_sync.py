"""Resume completion publishes to the configured primary Sheet, with no live I/O."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
import generate_apply_queue as queue
from sqlite_tracker import SQLiteTracker
import sheet_sync
class CompletionSyncTests(unittest.TestCase):
    def setUp(self):
        self.local=object.__new__(SQLiteTracker)
        self.item=queue.QueueRow(2,42,'Employer','SEM','https://example.test/job/42')
        self.artifacts=queue.Artifacts(Path('resume.docx'),Path('listing.md'))
        self.record=Mock(scout_id=42,company='Employer',job_title='SEM',job_link=self.item.job_url)
    def test_verified_local_completion_publishes(self):
        with patch.object(sheet_sync,'enabled',return_value=True),patch.object(sheet_sync,'complete_resume') as sync, \
             patch.object(queue.manage_job_tracker,'record_from_files',return_value=self.record), \
             patch.object(queue.manage_job_tracker,'_assert_not_rejected'), \
             patch('resume_delivery.publish',return_value='https://drive.google.com/file/d/verified/view'), \
             patch.object(sheet_sync,'sync') as general:
            self.assertTrue(queue.sync_completed_resume_to_primary_sheet(self.local,self.item,self.artifacts))
            sync.assert_called_once_with(42,'https://drive.google.com/file/d/verified/view',local_tracker=self.local,
                identity={'Company':'Employer','Job Title':'SEM','Job URL':self.item.job_url})
            general.assert_not_called()
    def test_disabled_primary_does_not_publish(self):
        with patch.object(sheet_sync,'enabled',return_value=False),patch.object(sheet_sync,'sync') as sync:
            queue.sync_completed_resume_to_primary_sheet(self.local,self.item,self.artifacts)
            sync.assert_not_called()
    def test_direct_sheet_writer_does_not_resync(self):
        with patch.object(sheet_sync,'sync') as sync:
            queue.sync_completed_resume_to_primary_sheet(object(),self.item,self.artifacts)
            sync.assert_not_called()
    def test_sync_failure_is_recorded_and_reported(self):
        failure=RuntimeError('conflicting edit')
        with patch.object(sheet_sync,'enabled',return_value=True),patch.object(sheet_sync,'complete_resume',side_effect=failure),patch.object(sheet_sync,'record_error') as record, \
             patch.object(queue.manage_job_tracker,'record_from_files',return_value=self.record), \
             patch.object(queue.manage_job_tracker,'_assert_not_rejected'), \
             patch('resume_delivery.publish',return_value='https://drive.google.com/file/d/verified/view'):
            with self.assertRaisesRegex(RuntimeError,'conflicting edit'):
                queue.sync_completed_resume_to_primary_sheet(self.local,self.item,self.artifacts)
            record.assert_called_once_with(failure)
if __name__=='__main__':unittest.main()
