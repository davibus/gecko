"""Canada is an allowed remote geography; other restrictions remain effective."""
import unittest
from types import SimpleNamespace
from location_evidence import location_blocker, source_location_blocker


class CanadaEligibilityTests(unittest.TestCase):
    def test_canadian_source_country_codes_and_names_are_allowed(self):
        for country in ('CA', 'CAN', 'Canada'):
            raw = SimpleNamespace(metadata={'country': country, 'workplaceType': 'Remote'}, location='Toronto, ON')
            self.assertEqual('', source_location_blocker(raw))
            job = SimpleNamespace(title='Marketing Analytics - Canada', location='Toronto, ON',
                                  details={'fields': {'remote_eligibility_restrictions': country}})
            self.assertEqual('', location_blocker(job))

    def test_canadian_hybrid_does_not_bypass_remote_requirement(self):
        raw = SimpleNamespace(metadata={'country': 'CA', 'workplaceType': 'Hybrid'}, location='Toronto, ON')
        self.assertIn('hybrid', source_location_blocker(raw))

    def test_other_country_and_residency_restrictions_still_block(self):
        for text in ('Chile', 'You can apply only from Chile', 'Remote. We are only hiring in the Eastern and Central time zones.',
                     'Not hiring in Utah'):
            job = SimpleNamespace(title='Paid Media Manager', location='Remote',
                                  details={'fields': {'remote_eligibility_restrictions': text}})
            self.assertTrue(location_blocker(job), text)


if __name__ == '__main__':
    unittest.main()
