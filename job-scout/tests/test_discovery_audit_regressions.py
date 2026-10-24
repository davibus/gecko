"""Offline regressions for defects demonstrated by the discovery volume audit."""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scout
from models import RawListing
from sources.base import ProviderError, SearchRequest
from sources.acquisition import acquire, search_pages
from sources.adzuna import AdzunaProvider
from sources.ats import LeverProvider
from sources.search_discovery import SearchDiscoveryProvider
from sources.themuse import TheMuseProvider
from service import SearchSummary
from preferences import load_preferences

def raw(number):
    return RawListing('test', str(number), f'https://example.test/jobs/{number}',
                      'Paid Search Manager', 'Example', location='Remote', description='Detailed job')

class DiscoveryAuditRegressions(unittest.TestCase):
    def test_remotive_dead_urls_have_their_own_reconciled_reason(self):
        from service import discover_remotive_full_feed
        from sources.remotive import RemotiveProvider
        rows=[raw(1),raw(2)];rows[1].title='Software Engineer'
        provider=RemotiveProvider();provider.full_feed=lambda:rows
        store=Mock();store.all.return_value=[]
        validator=Mock()
        validator.check_existing.side_effect=lambda jobs:[(j,SimpleNamespace(status='dead')) for j in jobs]
        result=discover_remotive_full_feed(provider,store,preferences=load_preferences(),link_validator=validator)
        self.assertEqual(result.fetched,2)
        self.assertEqual(result.deterministic_rejects,1)
        self.assertEqual(sum(result.deterministic_reject_reasons.values()),1)
        self.assertEqual(result.dead_url_excluded,1)
        self.assertEqual(result.added,0)
    def test_partial_source_errors_cannot_be_labeled_success(self):
        class Feed:
            name='test';board_errors=[{'company':'bad','error':'404'}]
            def configured(self):return True
            def full_feed(self):return [raw(1)]
        args=SimpleNamespace(source='test',query=None,location=None,page=1,results=20,dry_run=True)
        store=Mock();store.all.return_value=[]
        config={'providers':{'test':{}},'max_workers':1,'max_results_per_source':0}
        with (patch('scout.providers',return_value={'test':Feed()}),
              patch('scout.load_source_config',return_value=config),
              patch('scout.discover_listings',return_value=SearchSummary(fetched=1)),
              redirect_stdout(io.StringIO())):
            scout.search(args,store,load_preferences())
        self.assertEqual(args.run_result['source_health']['test']['status'],'partial failure')
        self.assertIn('test',args.run_result['source_errors'])
    def test_all_13_phrases_and_8_locations_reach_search_adapter(self):
        class Provider:
            name='test';broad_queries=['marketing']
            def configured(self):return True
            def search(self,request):return []
        args=SimpleNamespace(source='test',query=None,location=None,page=1,results=20,dry_run=True)
        store=Mock();store.all.return_value=[]
        config={'providers':{'test':{}},'max_workers':1,'max_results_per_source':0}
        with (patch('scout.providers',return_value={'test':Provider()}),
              patch('scout.load_source_config',return_value=config),
              patch('scout.acquire_source',return_value=([],[])) as acquire,
              patch('scout.discover_listings',return_value=SearchSummary()),
              redirect_stdout(io.StringIO())):
            scout.search(args,store,load_preferences())
        requests=acquire.call_args.args[1]
        self.assertEqual(len(requests),104)
        self.assertEqual({r.query for r in requests},set(load_preferences()['target_roles']))
        self.assertEqual({r.location for r in requests},set(load_preferences()['preferred_locations']))

    def test_broad_phrases_reach_indeed_and_firecrawl(self):
        from firecrawl_discovery import build_queries
        from sources.indeed_search import IndeedSearchProvider
        expected = ['Paid media', 'Paid search', 'PPC', 'SEM', 'Digital marketing',
                    'Performance marketing', 'Growth marketing', 'Marketing analytics',
                    'E-commerce marketing', 'Demand generation', 'Marketing operations',
                    'Marketing technology', 'Google Ads']
        preferences = load_preferences()
        self.assertEqual(preferences['target_roles'], expected)
        self.assertEqual(IndeedSearchProvider().queries, expected)
        self.assertEqual(IndeedSearchProvider(queries=['custom phrase']).queries, ['custom phrase'])
        queries = build_queries(preferences)
        for location in ('Utah', 'remote'):
            text = ' '.join(q['query'] for q in queries if q['location'] == location)
            for phrase in expected:
                self.assertIn('"' + phrase + '"', text)
            for title in ('Manager', 'Strategist', 'Director'):
                self.assertNotIn(title, text)

    def test_remotive_count_is_fetched_and_not_imported_or_daily_review_limit(self):
        provider=SimpleNamespace(name='remotive',configured=lambda:True)
        args=SimpleNamespace(source='remotive',query=None,location=None,page=1,results=20,
                             dry_run=True,limit=1)
        store=Mock();store.all.return_value=[]
        config={'providers':{'remotive':{}},'max_workers':1,'max_results_per_source':0}
        with (patch('scout.providers',return_value={'remotive':provider}),
              patch('scout.load_source_config',return_value=config),
              patch('scout.discover_remotive_full_feed',return_value=SearchSummary(fetched=7,unique_imported=2)) as discover,
              redirect_stdout(io.StringIO())):
            scout.search(args,store,load_preferences())
        self.assertIsNone(discover.call_args.kwargs['limit'])
        self.assertEqual(args.run_result['source_counts']['remotive'],7)

    def test_ashby_fulltime_and_contract_follow_current_employment_filter(self):
        from normalize import normalize
        from hard_filters import deterministic_filter
        listing=raw(1);listing.employment_type='FullTime'
        self.assertTrue(deterministic_filter(normalize(listing),load_preferences())[0])
        listing.employment_type='Contract'
        self.assertTrue(deterministic_filter(normalize(listing),load_preferences())[0])
        listing.employment_type='Internship'
        self.assertEqual(deterministic_filter(normalize(listing),load_preferences())[1],
                         'excluded employment type')
    def test_unrelated_companies_do_not_compare_large_descriptions(self):
        from normalize import normalize
        from deduplicate import duplicate_confidence
        left,right=normalize(raw(1)),normalize(raw(2))
        left.company='Alpha';right.company='Zzzzz'
        with patch('deduplicate.description_similarity',side_effect=AssertionError('unnecessary comparison')):
            self.assertEqual(duplicate_confidence(left,right),0)

    def test_blank_cost_allows_eligible_job_and_x_still_blocks(self):
        from google_tracker import resume_approval_value
        self.assertEqual(resume_approval_value('Utah','on-site',''),'Yes')
        self.assertEqual(resume_approval_value('Utah','on-site',' x '),'No')
    def test_continues_pages_and_detects_repeating_page(self):
        provider = SimpleNamespace(name='test', has_more=True)
        provider.search = lambda request: [raw(1)]
        with self.assertRaisesRegex(ProviderError, 'repeated page'):
            list(search_pages(provider, SearchRequest('paid search')))

    def test_keeps_successful_query_when_next_query_fails(self):
        provider = SimpleNamespace(name='test', has_more=False)
        def search(request):
            if request.query == 'bad':
                raise ProviderError('temporary failure')
            return [raw(request.query)]
        provider.search = search
        rows, errors = acquire(provider, [SearchRequest('good'), SearchRequest('bad'), SearchRequest('later')])
        self.assertEqual([r.source_job_id for r in rows], ['good', 'later'])
        self.assertEqual(len(errors), 1)

    def test_partial_board_failure_is_reported(self):
        class Feed:
            board_errors = [{'company':'Failed', 'error':'HTTP 404'}]
            def full_feed(self): return [raw(1)]
        rows, errors = acquire(Feed(), [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(errors), 1)

    def test_default_acquisition_has_no_50_record_cap_and_keeps_all_roles_locations(self):
        class Feed:
            name = 'test'
            def configured(self): return True
            def full_feed(self): return [raw(n) for n in range(301)]
        args = SimpleNamespace(source='test', query=None, location=None, page=1,
                               results=20, dry_run=True, daily_mode=False)
        store = Mock(); store.all.return_value=[]
        config = {'providers':{'test':{}}, 'max_workers':1, 'max_results_per_source':0}
        with (patch('scout.providers',return_value={'test':Feed()}),
              patch('scout.load_source_config',return_value=config),
              patch('scout.discover_listings',return_value=SearchSummary(fetched=301)) as discover,
              patch('scout.sync_tracker') as sync,
              redirect_stdout(io.StringIO())):
            self.assertEqual(scout.search(args,store,load_preferences()),0)
            self.assertEqual(len(discover.call_args.args[0]),301)
            sync.assert_not_called()

    @patch('sources.adzuna.get_json')
    def test_adzuna_uses_total_for_pagination_and_explicit_window(self, get):
        get.return_value={'count':3,'results':[{'id':'a'},{'id':'b'}]}
        provider=AdzunaProvider('id','key')
        list(provider.search(SearchRequest('marketing','Utah',1,2,7)))
        self.assertTrue(provider.has_more)
        self.assertIn('max_days_old=7',get.call_args.args[0])

    @patch('sources.adzuna.get_json')
    def test_adzuna_remote_is_a_search_term_not_a_geographic_place(self,get):
        get.return_value={'results':[]}
        list(AdzunaProvider('id','key').search(SearchRequest('Paid Search Manager','Remote')))
        from urllib.parse import parse_qs, urlsplit
        params=parse_qs(urlsplit(get.call_args.args[0]).query)
        self.assertEqual(params['what'],['Paid Search Manager remote'])
        self.assertNotIn('where',params)

    @patch('sources.ats.get_json')
    def test_lever_fetches_more_than_200(self,get):
        get.side_effect=[[{'id':str(n)} for n in range(200)],[{'id':'201'}]]
        rows=LeverProvider().fetch_company({'site':'test'})
        self.assertEqual(len(rows),201)
        self.assertIn('skip=200',get.call_args.args[0])

    @patch('sources.themuse.get_json')
    def test_muse_starts_at_zero_and_does_not_slice_api_page(self,get):
        get.return_value={'page_count':2,'results':[{'id':str(n),'name':'Marketing'} for n in range(30)]}
        provider=TheMuseProvider('test')
        self.assertEqual(len(list(provider.search(SearchRequest('Marketing','',1,20)))),30)
        self.assertIn('page=0',get.call_args.args[0]); self.assertTrue(provider.has_more)

    @patch('sources.search_discovery.get_json')
    def test_brave_default_has_no_30_day_filter_and_window_is_explicit(self,get):
        get.return_value={'web':{'results':[]}}
        provider=SearchDiscoveryProvider('indeed','site:indeed.com/viewjob','key')
        list(provider.search(SearchRequest('marketing')))
        self.assertNotIn('freshness',get.call_args.args[0])
        list(provider.search(SearchRequest('marketing',days=1)))
        self.assertIn('freshness=pd',get.call_args.args[0])

if __name__ == '__main__': unittest.main()
