import sys,json,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock,patch

import unified_search
from models import RawListing
from normalize import normalize


class PublicationIdentityTests(unittest.TestCase):
    def test_verified_application_link_is_read_back_after_discovery_redirect(self):
        job=normalize(RawListing('test','123','https://aggregator.example/job/123',
                                 'Digital Marketing Manager','Example',location='Remote',description='Full description'))
        job.id=123;job.authoritative_url='https://employer.example/careers/123'
        job.url_verification_status='verified'
        remote=SimpleNamespace(upsert_scout=Mock(return_value={'readback_verified':True,'skipped':[]}),
                               scout=lambda:SimpleNamespace(rows=[(2,{'ID':123,'Job URL':job.authoritative_url})]))
        with TemporaryDirectory() as folder:
            path=Path(folder)/'pending.json';path.write_text(json.dumps({'job_ids':[123],'reports':[]}),encoding='utf-8')
            with patch.object(unified_search,'PENDING',path),patch.object(unified_search,'flush_pending'),patch('sheet_sync.ensure_frozen_headers'):
                unified_search.deliver(SimpleNamespace(get=lambda key:job),remote=remote)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['job_ids'],[])
        remote.upsert_scout.assert_called_once()
