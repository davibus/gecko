import unittest

from models import RawListing
from normalize import normalize
from hard_filters import deterministic_filter
from preferences import load_preferences


class WorkArrangementTests(unittest.TestCase):
    def listing(self, **values):
        return RawListing(**dict(source='adzuna', source_job_id='test', url='https://example.com/job',
                                 title='Digital Marketing Manager', company='Example', location='US', **values))

    def test_explicit_description_locations_pass_remote_gate(self):
        for description in ('Location: Remote About the Role: Lead campaigns.',
                            'Location: Remote (San Jose, CA) JOB DESCRIPTION: Lead campaigns.',
                            'Work arrangement: Work from home.',
                            'This role is fully remote.'):
            with self.subTest(description=description):
                job = normalize(self.listing(description=description))
                self.assertEqual(job.work_arrangement, 'remote')
                self.assertTrue(deterministic_filter(job, load_preferences())[0])

    def test_remote_benefits_or_experience_do_not_make_role_remote(self):
        for description in ('We support remote employees around the world.',
                            'Experience managing remote teams required.',
                            'Remote work may be available in the future.'):
            self.assertEqual(normalize(self.listing(description=description)).work_arrangement, 'on-site')

    def test_explicit_restrictions_override_description_and_title(self):
        for remote_type, expected in [('on-site', 'on-site'), ('hybrid', 'hybrid')]:
            raw = self.listing(remote_type=remote_type, description='Location: Remote')
            self.assertEqual(normalize(raw).work_arrangement, expected)
        for description, expected in [('Location: Not remote.', 'on-site'),
                                      ('Location: Remote (hybrid).', 'hybrid'),
                                      ('Location: Remote. This role is on-site.', 'on-site')]:
            self.assertEqual(normalize(self.listing(description=description)).work_arrangement, expected)

    def test_explicit_remote_title(self):
        raw = self.listing()
        for title in ('Remote Digital Marketing Manager', 'Digital Marketing Manager (Remote)',
                      'Digital Marketing Manager - Remote (US)'):
            raw.title = title
            self.assertEqual(normalize(raw).work_arrangement, 'remote')

    def test_remote_in_role_subject_is_not_a_location(self):
        raw = self.listing()
        raw.title = 'Digital Marketing Manager for Remote Teams'
        self.assertEqual(normalize(raw).work_arrangement, 'on-site')

    def test_provider_role_headers_and_classification_are_explicit(self):
        for description in ('Digital Marketing Manager \u200b- Remote About the employer',
                            'Digital Marketing Manager Remote As the manager, lead campaigns.',
                            'Position: Digital Marketing Manager Remote Contract: 12 months',
                            'Location: Dearborn Job Classification: Remote FLSA Status: Exempt'):
            self.assertEqual(normalize(self.listing(description=description)).work_arrangement, 'remote')

    def test_remote_country_restrictions_are_not_worldwide_permission(self):
        raw=self.listing(remote_type='remote')
        for location,allowed in [('Remote - Canada',True),('United Kingdom - London',False),
                                 ('Remote - European Union',False),('AU: Melbourne',False),
                                 ('United States / Canada',True),('Worldwide',True)]:
            raw.location=location
            self.assertEqual(deterministic_filter(normalize(raw),load_preferences())[0],allowed)

    def test_sem_does_not_match_foreign_words(self):
        from role_filter import role_filter_reason
        self.assertFalse(role_filter_reason('Vendedor B2B | 20 horas semanais')[0])
        self.assertFalse(role_filter_reason('Criador de Videos | Remoto | 20 horas semana')[0])
        self.assertTrue(role_filter_reason('SEM Manager')[0])


if __name__ == '__main__':
    unittest.main()
