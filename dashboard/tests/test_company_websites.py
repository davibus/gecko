import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'job-scout')]
from dashboard import company_websites as websites
from dashboard.server import changes_for, notes_parts

class WebsiteTests(unittest.TestCase):
    def test_company_domain_requires_matching_homepage_branding_and_is_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            client=Mock();client.configured.return_value=True
            client.call.side_effect=[{'web':[{'url':'https://pearmill.com/about','title':'Pearmill - Marketing'}]},
                                     {'metadata':{'title':'Pearmill | Performance Marketing','url':'https://pearmill.com/','statusCode':200}}]
            with patch.object(websites,'CLIENT',client),patch.object(websites,'DIRECTORY',Path(folder)),patch.object(websites,'load_environment'):
                self.assertEqual(websites.lookup('Pearmill')['website'],'https://pearmill.com/')
                self.assertEqual(websites.lookup('Pearmill')['website'],'https://pearmill.com/')
                self.assertEqual(client.call.call_count,2)

    def test_directory_and_short_ambiguous_name_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            client=Mock();client.configured.return_value=True
            client.call.return_value={'web':[{'url':'https://linkedin.com/company/pearmill','title':'Pearmill'}]}
            with patch.object(websites,'CLIENT',client),patch.object(websites,'DIRECTORY',Path(folder)),patch.object(websites,'load_environment'):
                self.assertFalse(websites.lookup('Pearmill')['website'])
                self.assertFalse(websites.lookup('Proof')['website'])

    def test_website_saved_in_notes_history_without_overwriting_notes(self):
        data={'Notes':'Keep my notes','Applied':''}
        changes=changes_for(data,'details',{'notes':'Keep my notes','website':'https://pearmill.com/'})
        notes,meta,history=notes_parts(changes['Notes'])
        self.assertEqual(notes,'Keep my notes')
        self.assertEqual(meta['website'],'https://pearmill.com/')
        for url in ['javascript:alert(1)','https://user:pass@example.com','https://127.0.0.1/']:
            with self.assertRaises(ValueError): websites.validate(url)
