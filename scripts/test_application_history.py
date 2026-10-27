import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from application_history import previous_blocker
from application_runtime import save
from unittest.mock import patch


class PriorBlockerTests(unittest.TestCase):
    def test_fixed_automation_failure_does_not_remain_cached_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            row={'Company':'Example','Job Title':'Role','Job URL':'https://example.com/1',
                 'Resume Link':'file:///exact.docx','Notes':'Navigation interrupted'}
            item=dict(id=1,company='Example',title='Role',row=row)
            state=dict(category='blocked',company='Example',title='Role',outcome_tracker={'verified':True},
                       blocker='Navigation interrupted',workflow_fingerprint='old')
            save(root/'old/1/packet.json',item)
            save(root/'old/1/state.json',state)
            with patch('application_history.workflow_fingerprint',return_value='old'):
                self.assertIsNotNone(previous_blocker(item,SimpleNamespace(hashes={}),root/'new',root))
            with patch('application_history.workflow_fingerprint',return_value='repaired'):
                self.assertIsNone(previous_blocker(item,SimpleNamespace(hashes={}),root/'new',root))

    def test_unchanged_blocker_is_reused_and_changed_sources_are_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {'Company':'Example', 'Job Title':'Role', 'Job URL':'https://example.com/1',
                   'Resume Link':'file:///exact.docx', 'Notes':'Required answers need confirmation'}
            item = dict(id=1, company='Example', title='Role', row=row)
            sources = SimpleNamespace(hashes={'answers':'old', 'master':'same', 'index':'same'})
            save(root/'old/1/packet.json', dict(item))
            save(root/'old/1/state.json', dict(id=1, company='Example', title='Role',
                category='blocked', outcome_tracker={'verified':True}, blocker='Required answers need confirmation',
                source_hashes=sources.hashes, missing_required=[{'question':'Exact required question'}]))
            prior = previous_blocker(item, sources, root/'new', root)
            self.assertTrue(prior['prior_blocker_not_retried'])
            self.assertEqual(prior['missing_required'][0]['question'], 'Exact required question')
            sources.hashes = dict(sources.hashes, answers='new confirmed answer')
            self.assertIsNone(previous_blocker(item, sources, root/'new', root))
            sources.hashes = dict(sources.hashes, answers='old')
            item['row'] = dict(row, **{'Job URL':'https://example.com/changed'})
            self.assertIsNone(previous_blocker(item, sources, root/'new', root))


if __name__ == '__main__':
    unittest.main()
