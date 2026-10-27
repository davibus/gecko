import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'job-scout'))
import resume_delivery as d


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name, value in [('ROOT', root), ('CONFIG', root / 'config.json'), ('MANIFEST', root / 'manifest.json')]:
            p = patch.object(d, name, value)
            p.start()
            self.addCleanup(p.stop)
        d.CONFIG.write_text(json.dumps({'mode': 'private_google_drive', 'folder_id': 'private-folder'}))
        self.path = root / 'output/resumes/test.docx'
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b'unchanged validated artifact')
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.meta = {'id': 'file123', 'url': 'https://drive.google.com/file/d/file123/view',
                     'shared': False, 'permissions': [{'type': 'user', 'role': 'owner'}],
                     'title': self.path.name, 'size': self.path.stat().st_size,
                     'mime_type': d.MIME, 'parent_ids': ['private-folder']}

    def test_registered_private_url_resolves_to_exact_local_attachment(self):
        url = d.register(self.path, self.meta, self.sha)
        self.assertEqual(d.publish(self.path), url)
        self.assertEqual(d.local_path(url), self.path)
        self.assertEqual(d.verified_target(url), url)

    def test_unpublished_resume_cannot_fall_back_to_file_link(self):
        with self.assertRaisesRegex(RuntimeError, 'publication pending'):
            d.publish(self.path)

    def test_changed_local_resume_invalidates_delivery(self):
        url = d.register(self.path, self.meta, self.sha)
        self.path.write_bytes(b'changed')
        self.assertIsNone(d.local_path(url))
        with self.assertRaises(RuntimeError):
            d.publish(self.path)

    def test_public_file_and_wrong_download_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'bytes differ'):
            d.register(self.path, self.meta, 'wrong')
        self.meta['permissions'].append({'type': 'anyone', 'role': 'reader'})
        with self.assertRaisesRegex(ValueError, 'private'):
            d.register(self.path, self.meta, self.sha)

    def test_receipt_cannot_point_to_an_unrelated_url_or_outside_folder(self):
        self.meta['url'] = 'https://example.com/file/d/file123/view'
        with self.assertRaises(ValueError):
            d.register(self.path, self.meta, self.sha)

    def test_sheet_cell_requires_the_actual_hyperlink_property(self):
        url = d.register(self.path, self.meta, self.sha)
        tracker = Mock()
        tracker.config.spreadsheet_id = 'sheet'
        tab = SimpleNamespace(title='Job List', sheet_id=7, headers={'Resume Link': 4})
        tracker.api.get.return_value.execute.return_value = {
            'sheets': [{'data': [{'rowData': [{'values': [{'hyperlink': url}]}]}]}]}
        d.ensure_sheet_hyperlinks(tracker, tab, [(3, url)])
        request = tracker.api.batchUpdate.call_args.kwargs['body']['requests'][0]['repeatCell']
        self.assertEqual(request['fields'], 'userEnteredFormat.textFormat.link')
        self.assertEqual(request['cell']['userEnteredFormat']['textFormat']['link']['uri'], url)
        tracker.api.get.return_value.execute.return_value = {
            'sheets': [{'data': [{'rowData': [{'values': [{}]}]}]}]}
        with self.assertRaises(RuntimeError):
            d.ensure_sheet_hyperlinks(tracker, tab, [(3, url)])


if __name__ == '__main__':
    unittest.main()
