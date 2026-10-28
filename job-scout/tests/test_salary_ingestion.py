"""Salary ingestion regressions: avoid treating ad budgets as pay."""
import unittest

from models import RawListing
from normalize import normalize
from salary_format import extract_salary, normalize_salary_row


class SalaryIngestionTests(unittest.TestCase):
    def job(self, description, salary='', metadata=None):
        return normalize(RawListing(
            source='greenhouse', source_job_id='salary-case',
            url='https://example.com/jobs/salary-case', title='Paid Media Manager',
            company='Example', description=description, salary=salary,
            metadata=metadata or {}))

    def test_missing_provider_salary_recovered(self):
        self.assertEqual(self.job('Expected base salary is $85,000 - $106,000 USD.').salary,
                         '$85,000 - $106,000')

    def test_ats_html_pay_range(self):
        description = ('<p>Pay Transparency</p><div class="title">Zone A</div>'
                       '<div class="pay-range"><span>$124,000</span>'
                       '<span>—</span><span>$198,000 USD</span></div>')
        self.assertEqual(self.job(description).salary, '$124,000 - $198,000')

    def test_space_thousands_and_currency(self):
        description = 'The salary range for this role is between $90 000 and $120 000 [CAD].'
        self.assertEqual(self.job(description).salary, '$90,000 - $120,000 CAD')

    def test_currency_on_both_endpoints(self):
        self.assertEqual(self.job('Annual base salary is $110,000 USD - $130,000 USD.').salary,
                         '$110,000 - $130,000')

    def test_hourly_annualized(self):
        self.assertEqual(self.job('Salary: $40 - $50 per hour.').salary,
                         '$83,200 - $104,000')

    def test_structured_salary_first(self):
        metadata = {'baseSalary': {'currency': 'USD', 'value': {
            'minValue': 120000, 'maxValue': 150000, 'unitText': 'YEAR'}}}
        self.assertEqual(self.job('Manage $2M per month in advertising spend.', metadata=metadata).salary,
                         '$120,000 - $150,000')

    def test_no_salary_from_ad_budget(self):
        self.assertEqual(self.job('Manage $1M a month of ads across clients.').salary, '')

    def test_no_guessed_salary(self):
        self.assertEqual(self.job('Competitive salary, based on experience.').salary, '')

    def test_provider_estimate_qualified(self):
        changes, evidence = normalize_salary_row({
            'Salary':'Estimated $93,299', 'Job Description':'Competitive salary.'})
        self.assertEqual(changes.get('Salary'), '$93,299')
        self.assertIn('Provider estimate', changes.get('Notes', ''))


if __name__ == '__main__':
    unittest.main()
