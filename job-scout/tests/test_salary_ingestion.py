"""Salary ingestion regressions: avoid treating ad budgets as pay."""
import unittest

from models import RawListing
from normalize import normalize
from salary_format import extract_salary, normalize_salary_row


class SalaryIngestionTests(unittest.TestCase):
    def pay(self, description, salary='', metadata=None):
        raw = RawListing(
            source='greenhouse', source_job_id='salary-case',
            url='https://example.com/jobs/salary-case', title='Paid Media Manager',
            company='Example', description=description, salary=salary,
            metadata=metadata or {})
        job = normalize(raw)
        return extract_salary(job.salary, raw.description, raw.metadata)

    def test_missing_provider_salary_recovered(self):
        self.assertEqual(self.pay('Expected base salary is $85,000 - $106,000 USD.'),
                         '$85,000 - $106,000')

    def test_ats_html_pay_range(self):
        description = ('<p>Pay Transparency</p><div class="title">Zone A</div>'
                       '<div class="pay-range"><span>$124,000</span>'
                       '<span>—</span><span>$198,000 USD</span></div>')
        self.assertEqual(self.pay(description), '$124,000 - $198,000')

    def test_space_thousands_and_currency(self):
        description = 'The salary range for this role is between $90 000 and $120 000 [CAD].'
        self.assertEqual(self.pay(description), '$90,000 - $120,000 CAD')

    def test_currency_on_both_endpoints(self):
        self.assertEqual(self.pay('Annual base salary is $110,000 USD - $130,000 USD.'),
                         '$110,000 - $130,000')

    def test_hourly_annualized(self):
        self.assertEqual(self.pay('Salary: $40 - $50 per hour.'),
                         '$83,200 - $104,000')

    def test_structured_salary_first(self):
        metadata = {'baseSalary': {'currency': 'USD', 'value': {
            'minValue': 120000, 'maxValue': 150000, 'unitText': 'YEAR'}}}
        self.assertEqual(self.pay('Manage $2M per month in advertising spend.', metadata=metadata),
                         '$120,000 - $150,000')

    def test_no_salary_from_ad_budget(self):
        self.assertEqual(self.pay('Manage $1M a month of ads across clients.'), '')

    def test_discovery_keeps_raw_salary_for_eligibility_filters(self):
        raw = RawListing(source='test', source_job_id='hour',
                         url='https://example.com/hour', title='PPC', company='Example',
                         salary='$75 per hour', description='Salary: $75 per hour.')
        self.assertEqual(normalize(raw).salary, '$75 per hour')
        self.assertEqual(self.pay(raw.description, raw.salary), '$156,000')

    def test_no_guessed_salary(self):
        self.assertEqual(self.pay('Competitive salary, based on experience.'), '')

    def test_provider_estimate_qualified(self):
        changes, evidence = normalize_salary_row({
            'Salary':'Estimated $93,299', 'Job Description':'Competitive salary.'})
        self.assertEqual(changes.get('Salary'), '$93,299')
        self.assertIn('Provider estimate', changes.get('Notes', ''))


if __name__ == '__main__':
    unittest.main()
