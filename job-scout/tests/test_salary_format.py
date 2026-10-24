import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from salary_format import normalize_salary_row


class SalaryFormattingTests(unittest.TestCase):
    def salary(self,value,**context):
        return normalize_salary_row({'Salary':value,**context})

    def test_requested_formats_and_repeated_bounds_stay_exact(self):
        for text in ('$312,000','$124,800 - $124,800'):
            self.assertEqual(self.salary(text)[0],{})

    def test_annual_variants(self):
        for before,after in [('USD 195000 - 230000 per yearly','$195,000 - $230,000'),
                             ('$120k–$150k','$120,000 - $150,000'),
                             ('$120-150k annually','$120,000 - $150,000'),
                             ('124800 - 124800','$124,800 - $124,800')]:
            self.assertEqual(self.salary(before)[0]['Salary'],after)

    def test_notes_and_description_fallback_do_not_pick_expenses(self):
        changes,evidence=self.salary('',Notes='Laptop reimbursement $500. Annual base salary: $110,000 - $130,000.')
        self.assertEqual(changes['Salary'],'$110,000 - $130,000')
        self.assertEqual(evidence['source'],'Notes')
        self.assertEqual(self.salary('',Notes='Laptop allowance $500 and revenue target $2,000,000.')[0],{})

    def test_hourly_and_monthly_are_annualized_with_visible_assumptions(self):
        changes,_=self.salary('$40 - $48 an hour')
        self.assertEqual(changes['Salary'],'$83,200 - $99,840')
        self.assertIn('40 hours/week',changes['Notes'])
        changes,_=self.salary('$2,000 to $4,000 USD/month')
        self.assertEqual(changes['Salary'],'$24,000 - $48,000')
        self.assertIn('12 months/year',changes['Notes'])

    def test_posted_hours_override_default_and_notes_are_preserved(self):
        changes,_=self.salary('$40/hour',Notes='Part-time: 20 hours per week. Keep my note.')
        self.assertEqual(changes['Salary'],'$41,600')
        self.assertTrue(changes['Notes'].startswith('Part-time: 20 hours per week. Keep my note.'))

    def test_foreign_currency_and_ote_are_not_silently_relabelled(self):
        changes,_=self.salary('$126,000—$133,000 CAD')
        self.assertEqual(changes['Salary'],'$126,000 - $133,000 CAD')
        changes,_=self.salary('OTE $25k - $35k')
        self.assertEqual(changes['Salary'],'$25,000 - $35,000')
        self.assertIn('not base salary',changes['Notes'])

    def test_structured_salary(self):
        value="{'@type': 'QuantitativeValue', 'minValue': 125000, 'maxValue': 160000, 'unitText': 'YEAR'}"
        self.assertEqual(self.salary(value)[0]['Salary'],'$125,000 - $160,000')

    def test_explicit_base_range_beats_provider_estimate(self):
        changes,_=self.salary('$170,021 per year - estimated\nThe base salary range is $124,000 - $223,100 USD annually.')
        self.assertEqual(changes['Salary'],'$124,000 - $223,100')

    def test_unknown_and_task_pay_leave_salary_blank_and_preserve_text(self):
        self.assertEqual(self.salary('Not stated')[0],{'Salary':''})
        text='The rate of pay is $0.2333 per completed task.'
        changes,_=self.salary(text)
        self.assertEqual(changes['Salary'],'')
        self.assertIn(text,changes['Notes'])

    def test_repeated_normalization_is_no_op(self):
        row={'Salary':'$40/hour','Notes':'Original note'}
        changes,_=normalize_salary_row(row);row.update(changes)
        self.assertEqual(normalize_salary_row(row)[0],{})

    def test_benefit_and_unsupported_currency_are_not_usd_salaries(self):
        for notes in ('Competitive Salary Health Insurance 401K with employer match.',
                      'Salary Package: Up to ₱80K/month', 'Salary Package: PHP 63,000 per month'):
            self.assertEqual(self.salary('Not stated',Notes=notes)[0],{'Salary':''})

    def test_hourly_period_can_precede_pay_range(self):
        changes,_=self.salary('The hourly pay range for this position is $35.00 - $39.50.')
        self.assertEqual(changes['Salary'],'$72,800 - $82,160')

    def test_posted_salary_summary_wins_over_alternate_hourly_rates(self):
        text=('| Salary<br> <br>$80k - $150k | Remote<br>Location<br> <br>Worldwide |\n'
              'Sep 18, 2026 - Sanctuary Computer Inc is hiring a remote Senior Shopify Developer. '
              '💸 Salary: $80k - $150k. 📍Location: Worldwide.\n'
              'Our pay scale ranges from $40/hr to $120/hr pending seniority (& team leadership experience), '
              'and our projects are rarely less than 8 full time weeks at 40 hours per week.')
        changes,_=self.salary(text)
        self.assertEqual(changes['Salary'],'$80,000 - $150,000')
        self.assertIn(text,changes['Notes'])

    def test_multiple_posted_ranges_choose_first_and_preserve_others(self):
        text='$196,000 - $230,000USD $166,000 - $195,000USD'
        changes,_=self.salary(text)
        self.assertEqual(changes['Salary'],'$196,000 - $230,000')
        self.assertIn('$166,000 - $195,000USD',changes['Notes'])

    def test_moving_non_salary_text_does_not_make_it_salary_next_time(self):
        row={'Salary':'Bonus: $12,000. Revenue target $1,000,000.'}
        changes,_=normalize_salary_row(row)
        self.assertEqual(changes['Salary'],'')
        row.update(changes)
        self.assertEqual(normalize_salary_row(row)[0],{})


if __name__=='__main__':unittest.main()
