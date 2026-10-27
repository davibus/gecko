import unittest
from pathlib import Path
from manage_job_tracker import extract_title
import gecko_v2 as v2

class ExactQueueTitles(unittest.TestCase):
    def test_canonical_title_preserves_specialization(self):
        self.assertEqual(extract_title('# B2B Growth Marketing Manager – Industrial/SaaS\n- **Scout ID:** 2996\n'),
                         'B2B Growth Marketing Manager – Industrial/SaaS')

    def test_legacy_heading_behavior_is_retained(self):
        self.assertEqual(extract_title('# Marketing Manager – Example Company\n'), 'Marketing Manager')

    def test_explicit_title_still_wins(self):
        self.assertEqual(extract_title('# Other\n- **Job Title:** Director – Growth\n- **Scout ID:** 1\n'), 'Director – Growth')

    def test_generation_preserves_queue_em_dash_title(self):
        text='# Media Buyer — Meta Lead Gen & Creative Strategy\n- **Company:** NEW ERA Digital Marketing\n- **Job Number:** scout-3030\n- **Scout ID:** 3030\n'
        self.assertEqual(v2.listing_metadata(text,Path('test.md'))['title'],'Media Buyer — Meta Lead Gen & Creative Strategy')

    def test_generation_legacy_heading_behavior_retained(self):
        text='# Marketing Manager — Example Company\n- **Job Number:** 123\n'
        result=v2.listing_metadata(text,Path('test.md'))
        self.assertEqual((result['title'],result['company']),('Marketing Manager','Example Company'))

if __name__ == '__main__': unittest.main()
