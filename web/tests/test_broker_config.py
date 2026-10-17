import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from web.broker import Redis


class BrokerConfigurationTests(unittest.TestCase):
    def test_accepts_vercel_generated_and_native_complete_pairs(self):
        for prefix, url_key, token_key in (
            ('native','UPSTASH_REDIS_REST_URL','UPSTASH_REDIS_REST_TOKEN'),
            ('vercel','KV_REST_API_URL','KV_REST_API_TOKEN'),
            ('custom','STORAGE_REST_API_URL','STORAGE_REST_API_TOKEN'),
        ):
            with self.subTest(prefix=prefix), patch.dict(os.environ,{url_key:'https://redis.example/',token_key:'test-token'},clear=True):
                store=Redis()
                self.assertEqual(store.url,'https://redis.example')
                self.assertEqual(store.token,'test-token')

    def test_does_not_mix_incomplete_pairs_or_accept_read_only_tokens(self):
        for environment in (
            {'UPSTASH_REDIS_REST_URL':'https://one.example','KV_REST_API_TOKEN':'test-token'},
            {'KV_REST_API_URL':'https://one.example','KV_REST_API_READ_ONLY_TOKEN':'test-token'},
        ):
            with patch.dict(os.environ,environment,clear=True),self.assertRaises(RuntimeError):
                Redis()

    def test_rejects_non_https_or_non_origin_endpoints(self):
        for url in ('http://redis.example','https://user@redis.example','https://redis.example/path','https://redis.example?token=test'):
            with patch.dict(os.environ,{'KV_REST_API_URL':url,'KV_REST_API_TOKEN':'test-token'},clear=True),self.assertRaises(RuntimeError):
                Redis()


if __name__=='__main__':
    unittest.main()
