import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sources import firecrawl as f
from sources.base import ProviderError

class PacingTests(unittest.TestCase):
    def setUp(self):
        self.clock=100.0
        self.waits=[]
        self.patches=[patch.dict(os.environ, FIRECRAWL_API_KEY='test'),patch.object(f,'_NEXT_REQUEST',0.0),patch.object(f.time,'monotonic',side_effect=lambda:self.clock),patch.object(f.time,'sleep',side_effect=self.sleep)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def sleep(self,seconds):
        self.waits.append(seconds);self.clock+=seconds
    def limited(self,retry='20'):
        exc=ProviderError('Request failed for Firecrawl scrape: HTTP 429')
        exc.__cause__=HTTPError('https://api.firecrawl.dev',429,'limited',{'Retry-After':retry},None)
        return exc
    @patch.object(f,'post_json')
    def test_retry_after_recovers(self,post):
        post.side_effect=[self.limited(),{'success':True,'data':{'ok':True}}]
        self.assertEqual(f.FirecrawlClient().call('scrape',{}),{'ok':True})
        self.assertEqual(post.call_count,2)
        self.assertGreaterEqual(self.waits[0],20)
    @patch.object(f,'post_json')
    def test_shared_pacing_between_clients(self,post):
        post.return_value={'success':True,'data':{}}
        f.FirecrawlClient().call('search',{})
        f.FirecrawlClient().call('scrape',{})
        self.assertEqual(self.waits,[f.MIN_INTERVAL])
    @patch.object(f,'post_json')
    def test_retries_are_bounded(self,post):
        post.side_effect=self.limited('1')
        c=f.FirecrawlClient()
        for _ in range(2):
            with self.assertRaises(ProviderError):c.call('scrape',{})
        self.assertEqual(post.call_count,3)
    @patch.object(f,'post_json')
    def test_long_cooldown_is_not_shortened(self,post):
        post.side_effect=self.limited('120')
        with self.assertRaises(ProviderError):f.FirecrawlClient().call('scrape',{})
        self.assertEqual(post.call_count,1)
        with self.assertRaises(ProviderError):f.FirecrawlClient().call('search',{})
        self.assertEqual(post.call_count,1)
    @patch.object(f,'post_json')
    def test_auth_errors_do_not_retry(self,post):
        post.side_effect=ProviderError('Firecrawl HTTP 401')
        c=f.FirecrawlClient()
        for _ in range(2):
            with self.assertRaises(ProviderError):c.call('scrape',{})
        self.assertEqual(post.call_count,1)
if __name__=='__main__':unittest.main()
