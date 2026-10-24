"""Full description publication must not depend on optional discovery notes."""
import unittest
from unittest.mock import patch
from pathlib import Path

from google_tracker import Config, GoogleTracker
from models import RawListing
from normalize import normalize
from tests.test_google_tracker import FakeSheets


class DescriptionPublicationTests(unittest.TestCase):
    def setUp(self):
        guard=patch('description_readiness.assess',return_value={})
        guard.start();self.addCleanup(guard.stop)
    def tracker(self, description='', position=3):
        fake = FakeSheets()
        for index, row in enumerate(fake.data['Job Scout']):
            row.insert(position, 'Gecko Job Description' if index == 0 else description)
            row.append('Firecrawl Job Description' if index == 0 else '')
        return GoogleTracker(Config('test', Path('unused'), 'Job Tracker', 'Job Scout'), fake), fake

    def job(self, key='new'):
        job = normalize(RawListing('test', key, f'https://example.test/{key}',
                                   'Digital Marketing Manager', 'Example', location='Remote',
                                   description='Manage paid search campaigns. ' * 40))
        job.id = 100 if key == 'new' else 42
        return job

    def test_new_job_description_is_published_without_notes(self):
        for position in (0, 3, 21):
            tracker, _ = self.tracker(position=position)
            job = self.job()
            tracker.upsert_scout([job])
            self.assertEqual(tracker.scout().rows[-1][1]['Gecko Job Description'], job.description)

    def test_new_job_receives_semantic_readiness_and_preserves_existing_decision(self):
        tracker,fake=self.tracker()
        for index,row in enumerate(fake.data['Job Scout']):
            row.append('Enough Data' if index==0 else 'No')
        verdict={'100':{'value':'Yes','reason':'Specific duties and skills','status':'reviewed','evidence':[]}}
        with patch('description_readiness.assess',return_value=verdict):
            tracker.upsert_scout([self.job()])
        rows=tracker.scout().rows
        self.assertEqual(rows[0][1]['Enough Data'],'No')
        self.assertEqual(rows[-1][1]['Enough Data'],'Yes')

    def test_full_enrichment_is_published_instead_of_provider_snippet(self):
        tracker, _ = self.tracker()
        job = self.job(); job.description = 'Short search snippet...'
        job.enriched_description = 'Full verified responsibilities and requirements. ' * 40
        tracker.upsert_scout([job])
        self.assertEqual(tracker.scout().rows[-1][1]['Gecko Job Description'], job.enriched_description)

    def test_backfill_empty_description_preserves_manual_description(self):
        for original in ('', 'User edited description'):
            tracker, _ = self.tracker(original)
            job = self.job('job')
            tracker.upsert_scout([job], fill_blanks_only=True)
            self.assertEqual(tracker.scout().rows[0][1]['Gecko Job Description'], original or job.description)

    def test_ordinary_rediscovery_preserves_existing_description(self):
        tracker, _ = self.tracker('User edited description')
        tracker.upsert_scout([self.job('job')])
        self.assertEqual(tracker.scout().rows[0][1]['Gecko Job Description'], 'User edited description')

    def test_description_formula_is_preserved(self):
        tracker, _ = self.tracker('="Protected description"')
        tracker.upsert_scout([self.job('job')], fill_blanks_only=True)
        self.assertEqual(tracker.scout().rows[0][1]['Gecko Job Description'], '="Protected description"')
