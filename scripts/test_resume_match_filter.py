"""Offline regression checks; synthetic legacy jobs must not invoke live inference."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'job-scout'))

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        'tests.test_resume_match', 'tests.test_salary_ceiling',
        'tests.test_publication_identity', 'tests.test_unified_search',
        'tests.test_firecrawl_discovery',
    ])
    # Match-policy tests explicitly enable/mock their evidence boundaries. Older
    # salary/discovery fixtures remain about those independent concerns.
    with patch('resume_match.settings', return_value={'enabled': False, 'minimum_score': 80}):
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(not result.wasSuccessful())
