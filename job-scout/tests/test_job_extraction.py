"""Complete source evidence, field mapping and resume access; offline fixtures only."""
from copy import deepcopy
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2] / 'scripts'))
from job_extraction import extract, sheet_description, salary_display
from firecrawl_discovery import extract_listing
from models import RawListing
from normalize import normalize
from storage import JobStore
from google_tracker import GoogleTracker, Config
from tests.test_google_tracker import FakeSheets
from tests.test_firecrawl_discovery import page, URL, DESCRIPTION
import generate_apply_queue as queue


class CompleteExtractionTests(unittest.TestCase):
    def test_company_website_from_labeled_footer_links(self):
        from job_extraction import _company_website
        target = 'https://jobs.lever.co/silverbackstrategies/job'
        text = ('[Apply](https://jobs.lever.co/silverbackstrategies/job/apply)\n'
                '[EEOC](https://www.eeoc.gov/)\n'
                '[Silverback Strategies Home Page](http://www.silverbackstrategies.com/)')
        self.assertEqual(_company_website({}, text, '', target, 'Silverback Strategies'),
                         'http://www.silverbackstrategies.com/')
        self.assertIsNone(_company_website({}, '[Unrelated](https://other.example)', '', target, 'Silverback Strategies'))
        self.assertIsNone(_company_website({}, '[Company Website](http://127.0.0.1)', '', target, 'Acme'))
        self.assertEqual(_company_website({}, '', '<a href="https://acme.example">Acme Website</a>', target, 'Acme'), 'https://acme.example')
        self.assertEqual(_company_website({'hiringOrganization': {'url': 'https://official.example'}}, text, '', target, 'Silverback Strategies'), 'https://official.example')

    def setUp(self):
        blocked = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden'))
        blocked.start(); self.addCleanup(blocked.stop)

    def document(self, **overrides):
        data = page(**overrides)
        raw, evidence, _ = extract_listing(data, URL)
        return extract(data, raw, evidence), raw, data

    def test_every_published_field_and_original_evidence(self):
        doc, raw, data = self.document(
            hiringOrganization={'name': 'Acme', 'url': 'https://acme.example'},
            employmentType=['FULL_TIME', 'CONTRACTOR'], workHours='35 hours per week, Monday through Friday',
            baseSalary={'currency': 'USD', 'value': {'minValue': 90000, 'maxValue': 120000, 'unitText': 'YEAR'}},
            responsibilities='Manage PPC campaigns.', qualifications='Three years of paid search experience.',
            preferredQualifications='Google Ads certification.', jobBenefits='Medical insurance and paid leave.',
            applicantLocationRequirements={'name': 'United States; Utah residents only'},
            specialCommitments='Quarterly travel required.', applicationUrl=URL + '/apply',
            applicationFee={'required': True, 'value': 15, 'currency': 'USD'})
        f = doc['fields']
        self.assertEqual(doc['status'], 'complete')
        self.assertEqual(f['company'], 'Acme'); self.assertEqual(f['title'], 'Paid Search Manager')
        self.assertEqual(f['employment_types'], ['full-time', 'contract'])
        self.assertEqual(f['work_hours'], '35 hours per week, Monday through Friday')
        self.assertEqual(f['salary']['minimum'], 90000); self.assertEqual(f['salary']['maximum'], 120000)
        self.assertEqual(f['salary']['currency'], 'USD'); self.assertEqual(f['salary']['pay_period'], 'year')
        self.assertEqual(f['work_arrangement'], 'remote'); self.assertIn('Utah', f['remote_eligibility_restrictions'])
        self.assertTrue(f['application_fee_required']); self.assertTrue(f['application_fee_evidence'])
        self.assertEqual(f['application_url'], URL + '/apply'); self.assertEqual(f['employer_job_id'], 'abc-123')
        self.assertEqual(f['discovery_source'], 'Firecrawl'); self.assertTrue(f['posting_date_evidence'])
        for key in ('responsibilities', 'required_qualifications', 'preferred_qualifications', 'benefits', 'notes', 'location', 'schedule', 'original_posting_date'):
            self.assertTrue(f[key], key)
        self.assertEqual(doc['raw_html'], data['rawHtml'])
        self.assertEqual(doc['raw_markdown'], data['markdown'])
        self.assertEqual(doc['original_description'], DESCRIPTION)
        self.assertTrue(doc['full_description_markdown'].startswith(DESCRIPTION))
        self.assertIn('Manage PPC campaigns.', doc['full_description_markdown'])
        self.assertIn('Google Ads certification.', doc['full_description_markdown'])

    def test_no_salary_hours_type_or_fee_invented(self):
        doc, _, _ = self.document(employmentType='', jobLocationType='')
        f = doc['fields']
        self.assertEqual(f['employment_types'], [])
        for key in ('work_hours', 'schedule', 'work_arrangement', 'application_fee_required', 'application_url'):
            self.assertIsNone(f[key], key)
        self.assertIsNone(f['salary']['minimum']); self.assertIsNone(f['salary']['pay_period'])
        self.assertEqual(salary_display(f['salary']), '')

    def test_salary_periods_types_and_arrangements(self):
        for employment, expected in [('PART_TIME', 'part-time'), ('TEMPORARY', 'temporary'), ('INTERN', 'internship')]:
            doc, _, _ = self.document(employmentType=employment)
            self.assertEqual(doc['fields']['employment_types'], [expected])
        for arrangement in ('hybrid', 'on-site', 'remote'):
            doc, raw, data = self.document(jobLocationType='')
            data['markdown'] += f'\nThis is a {arrangement} position. Salary: USD 25 to 35 per hour.'
            f = extract(data, raw, '')['fields']
            self.assertEqual(f['work_arrangement'], arrangement)
            self.assertEqual(f['salary']['minimum'], 25); self.assertEqual(f['salary']['maximum'], 35)
            self.assertEqual(f['salary']['pay_period'], 'hour')
        doc, raw, data = self.document(jobLocationType='')
        data['markdown'] += '\nWorkplace type: Remote'
        self.assertEqual(extract(data, raw, '')['fields']['work_arrangement'], 'remote')

    def test_mandatory_optional_negated_and_unknown_fees(self):
        for text, expected in [('A mandatory application fee of $25 is required.', True),
                               ('No refunds for the mandatory application fee of $25.', True),
                               ('No application fee is required.', False),
                               ('An optional application fee of $25 may apply.', None),
                               ('Application fee: $25 non-refundable.', None)]:
            doc, raw, data = self.document()
            data['markdown'] += '\n' + text
            f = extract(data, raw, '')['fields']
            self.assertIs(f['application_fee_required'], expected)
            self.assertIsNone(f['salary']['minimum'], 'Application fee must never become salary')
        doc, raw, data = self.document()
        data['markdown'] += '\nMandatory application fee: $25.\nSalary: USD 90,000 to 120,000 per year.'
        self.assertEqual(extract(data, raw, '')['fields']['salary']['minimum'], 90000)

    def test_incomplete_empty_inaccessible_and_truncated_sources_need_review(self):
        for mode in ('empty', 'truncated', 'inaccessible', 'empty_section', 'flag'):
            data = page()
            raw, evidence, _ = extract_listing(data, URL)
            if mode == 'empty':
                data['markdown'] = ''; raw.metadata['description'] = ''
            elif mode == 'truncated': data['markdown'] += '\nRead more'
            elif mode == 'inaccessible': data['metadata']['statusCode'] = 403
            elif mode == 'empty_section': data['markdown'] += '\n## Qualifications\n'
            else: data['metadata']['truncated'] = True
            self.assertEqual(extract(data, raw, evidence)['status'], 'review', mode)

    def test_storage_reopen_and_resume_archive_reuse_full_description(self):
        doc, raw, _ = self.document()
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'jobs.sqlite'
            with JobStore(path) as store:
                job = normalize(raw); job.id = store.save(job)
                store.save_job_document(job.id, doc)
            with JobStore(path) as store:
                job = store.get(job.id)
                self.assertEqual(job.description, doc['full_description_markdown'])
                self.assertEqual(job.details['raw_html'], doc['raw_html'])
                item = queue.QueueRow(2, job.id, job.company, job.title, job.url, job.source)
                with patch.object(queue, 'ROOT', Path(temp)), patch.object(queue, 'retrieve_full_description') as fetch, patch.object(queue, '_saved_listing') as saved:
                    archive, attempts = queue._archive_listing(job, item, store, persist_retrieval=False)
                    archive2, _ = queue._archive_listing(job, item, store, persist_retrieval=False)
                self.assertIn(doc['full_description_markdown'], archive.read_text(encoding='utf-8'))
                fetch.assert_not_called(); saved.assert_not_called()
                self.assertEqual(attempts[0].method, 'durable complete job description')

    def test_sheet_mapping_uses_headers_and_preserves_manual_values(self):
        for fee in (True, None):
            doc, raw, _ = self.document(applicationFee={'required': True, 'value': 25} if fee else None)
            fake = FakeSheets()
            for row in fake.data['Job Scout']:
                row.extend(['Found Using', 'Job Description', 'Company Website'] if row is fake.data['Job Scout'][0] else ['', '', ''])
            # Insert a user column ahead of every mapped field.
            for row in fake.data['Job Scout']: row.insert(0, 'Custom' if row is fake.data['Job Scout'][0] else 'keep')
            tracker = GoogleTracker(Config('test', Path('unused'), 'Job Tracker', 'Job Scout'), fake)
            job = normalize(raw); job.id = 100; job.details = doc; job.found_using = 'Firecrawl'; job.description = doc['full_description_markdown']
            tracker.upsert_scout([job], discovery_notes={100: 'Source evidence'})
            values = dict(tracker.scout().rows)[3]
            self.assertEqual(values['Found Using'], 'Firecrawl')
            self.assertEqual(values['Job Description'], job.description)
            self.assertEqual(values.get('Cost', ''), 'x' if fee else '')
            if fee: self.assertEqual(values['Apply?'], 'No')
            headers = fake.data['Job Scout'][0]
            for name in ('Found Using', 'Notes', 'Job Description'):
                fake.data['Job Scout'][2][headers.index(name)] = 'Manual value'
            tracker.upsert_scout([job])
            values = dict(tracker.scout().rows)[3]
            for name in ('Found Using', 'Notes', 'Job Description'): self.assertEqual(values[name], 'Manual value')

    def test_sheet_cell_limit_retains_complete_local_evidence(self):
        doc, raw, _ = self.document()
        doc['full_description_markdown'] = DESCRIPTION * 30
        self.assertEqual(sheet_description(doc['full_description_markdown']), '')
        with TemporaryDirectory() as temp, JobStore(Path(temp) / 'jobs.sqlite') as store:
            job = normalize(raw); job.id = store.save(job)
            store.save_job_document(job.id, doc)
            self.assertEqual(store.get(job.id).description, doc['full_description_markdown'])


if __name__ == '__main__': unittest.main()
