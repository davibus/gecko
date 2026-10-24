import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from models import RawListing
from normalize import normalize
from preferences import load_preferences
from hard_filters import deterministic_filter, salary_exclusion_reason
from google_tracker import Config, GoogleTracker
from storage import JobStore
from service import discover_listings
from tests.test_google_tracker import FakeSheets


class SalaryCeilingTests(unittest.TestCase):
    def raw(self, salary='', description='Manage paid search campaigns. ' * 40):
        return RawListing('test', 'salary-test', 'https://example.test/salary-test',
                          'Digital Marketing Manager', 'Example', location='Remote',
                          salary=salary, description=description)

    def test_starting_salary_boundary_and_ranges(self):
        cases = [('$120,000', True), ('$120,000-$180,000', True),
                 ('$120k–$180k', True), ('$120–180k', True),
                 ('$120,000.01', False), ('$120,001-$180,000', False),
                 ('$121,000', False), ('$125k–$150k', False),
                 ('USD 130,000 per year', False), ('$119,999', True)]
        for salary, allowed in cases:
            with self.subTest(salary=salary):
                self.assertEqual(deterministic_filter(normalize(self.raw(salary)), load_preferences())[0], allowed)

    def test_unknown_estimated_upper_only_and_nonannual_pay_remain_unproven(self):
        for salary in ('', 'Competitive', 'Up to $180,000', 'Estimated $150,000',
                       '$75 per hour', '$75/hr', 'CAD 150,000', '$15,000 per month',
                       '$200,000 OTE', 'Total compensation $200,000'):
            with self.subTest(salary=salary):
                self.assertFalse(salary_exclusion_reason(normalize(self.raw(salary)),load_preferences()))

    def test_explicit_base_salary_overrides_total_compensation(self):
        for description, allowed in [('Base salary: $110,000-$150,000. Plus bonus.', True),
                                      ('Annual base salary range: $121,000-$160,000.', False),
                                      ('Base salary: up to $180,000.', True)]:
            job=normalize(self.raw('$200,000 OTE',description))
            self.assertEqual(not bool(salary_exclusion_reason(job,load_preferences())),allowed)

    def test_gecko_and_firecrawl_are_filtered_before_storage(self):
        for source in ('adzuna','greenhouse'):
            with self.subTest(source=source), TemporaryDirectory() as folder, JobStore(Path(folder)/'jobs.db') as store:
                raw=self.raw('$125,000-$150,000');raw.source=source
                if source=='greenhouse':raw.metadata['_discovered_via']='firecrawl-search'
                summary=discover_listings([raw],store,preferences=load_preferences())
                self.assertEqual(summary.added,0)
                self.assertEqual(summary.deterministic_rejects,1)
                self.assertEqual(store.all(),[])

    def test_saved_full_description_is_checked_at_publication(self):
        job=normalize(self.raw(''))
        job.description='Short snippet'
        job.enriched_description='Annual base salary: $121,000-$160,000. Responsibilities: manage campaigns.'
        self.assertTrue(salary_exclusion_reason(job,load_preferences()))

    def test_real_ats_description_salary_formats(self):
        cases=[('Salary Range: $150,000 - 200,000 base + Equity',True),
               ('Salary Range: $120,000 - 200,000 base + Equity',False),
               ('For New York-based candidates, the range being offered for this role is $180k - 210k based on experience.',True),
               ('We raised $270 million. Manage a $150,000 advertising budget.',False),
               ('Salary: $75 per hour',False),('Salary: $90,000 - $115,000',False)]
        for text,excluded in cases:
            with self.subTest(text=text):
                self.assertEqual(bool(salary_exclusion_reason(normalize(self.raw('',text)),load_preferences())),excluded)

    def test_sheet_writer_blocks_new_high_salary_rows_and_keeps_existing(self):
        fake=FakeSheets()
        for index,row in enumerate(fake.data['Job Scout']):
            row.extend(['Gecko Job Description','Firecrawl Job Description'] if index==0 else ['',''])
        tracker=GoogleTracker(Config('test',Path('unused'),'Job Tracker','Job Scout'),fake)
        original=[list(r) for r in fake.data['Job Scout']]
        job=normalize(self.raw('$125,000'));job.id=100
        summary=tracker.upsert_scout([job])
        self.assertEqual(summary['added'],0)
        self.assertEqual(summary['salary_excluded'],1)
        self.assertEqual(fake.data['Job Scout'],original)
        job=normalize(self.raw('$120,000-$180,000'));job.id=101
        self.assertEqual(tracker.upsert_scout([job])['added'],1)
        # Existing jobs are not removed or silently disqualified by the cutoff.
        job.id=42;job.url=job.canonical_url='https://example.test/job';job.salary='$150,000'
        tracker.upsert_scout([job])
        self.assertEqual(len(fake.data['Job Scout']),3)
