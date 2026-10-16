import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'job-scout'))
from sources.indeed_search import IndeedSearchProvider, ResultPage, seed_verified_links
from sources.http import FetchedDocument
from sources.base import ProviderError
from models import RawListing
from test_sqlite_tracker import SQLiteTrackerTests
from search_indeed import import_new


def doc(url, body):return FetchedDocument(body.encode(),url,'text/html')
def card(key,title='Digital Marketing Manager'):
    return f'<a data-jk="{key}" class="jcs-JobTitle" aria-label="full details of {title}"></a>'
def detail(url,title='Digital Marketing Manager'):
    return doc(url,'<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','url':url,'title':title,'hiringOrganization':{'name':'Example'},'description':'Complete description','jobLocation':{'address':{'addressRegion':'UT','addressCountry':'US'}}})+'</script>')


class ProviderTests(unittest.TestCase):
    def test_observed_pagination_and_job_identity(self):
        def fetch(url):
            if '/viewjob?' in url:return detail(url)
            if 'start=10' in url:return doc(url,card('2222222222222222'))
            return doc(url,card('1111111111111111')+'<a aria-label="Next Page" href="/jobs?q=marketing&amp;l=Utah&amp;start=10">Next</a>')
        p=IndeedSearchProvider(fetch=fetch,queries=['marketing'],locations=['Utah'])
        rows=list(p.full_feed())
        self.assertEqual([j.source_job_id for j in rows],['1111111111111111','2222222222222222'])
        self.assertEqual(len(p.acquisition_events),2)
        self.assertEqual(p.errors,[])

    def test_one_bad_detail_does_not_discard_other_jobs(self):
        def fetch(url):
            if '/jobs?' in url:return doc(url,card('1111111111111111')+card('2222222222222222'))
            if '1111111111111111' in url:raise ProviderError('HTTP 404')
            return detail(url)
        p=IndeedSearchProvider(fetch=fetch,queries=['marketing'],locations=['Utah'])
        self.assertEqual(len(list(p.full_feed())),1)
        self.assertEqual(len(p.exclusions),1)

    def test_rate_limit_waits_and_retries_only_twice(self):
        p=IndeedSearchProvider()
        p.fetch=__import__('unittest.mock',fromlist=['Mock']).Mock(side_effect=ProviderError('HTTP 429'))
        with patch('sources.indeed_search.time.sleep') as sleep:
            with self.assertRaises(ProviderError):p.retrieve('https://www.indeed.com/jobs?q=marketing')
        self.assertEqual(p.fetch.call_count,3)
        self.assertEqual(sum(call.args==(60,) for call in sleep.call_args_list),2)

    def test_access_denial_is_not_retried(self):
        p=IndeedSearchProvider()
        p.fetch=__import__('unittest.mock',fromlist=['Mock']).Mock(side_effect=ProviderError('HTTP 403'))
        with patch('sources.indeed_search.time.sleep'):
            with self.assertRaises(ProviderError):p.retrieve('https://www.indeed.com/jobs?q=marketing')
        self.assertEqual(p.fetch.call_count,1)

    def test_mismatched_detail_title_rejected(self):
        p=IndeedSearchProvider(fetch=lambda url:detail(url,'Different role'))
        listing,_,error=p.detail(('1111111111111111','Expected role'))
        self.assertIsNone(listing);self.assertIn('title',error['error'])

    def test_budget_reports_partial_not_exhausted(self):
        def fetch(url):
            return detail(url) if '/viewjob?' in url else doc(url,card('1111111111111111')+card('2222222222222222'))
        p=IndeedSearchProvider(fetch=fetch,max_jobs=1,queries=['marketing'],locations=['Utah'])
        self.assertEqual(len(list(p.full_feed())),1)
        self.assertEqual(p.limits[0]['reason'],'posting budget reached')

    def test_off_domain_pagination_rejected(self):
        p=ResultPage('https://www.indeed.com/jobs?q=marketing&l=Utah')
        with self.assertRaises(ProviderError):p.feed('<a aria-label="Next Page" href="https://other.example/jobs">Next</a>')

    def test_daily_validator_reuses_fresh_verified_posting(self):
        from link_validation import DailyLinkValidator
        from normalize import normalize
        p=IndeedSearchProvider(fetch=lambda url:detail(url))
        raw,_,_=p.detail(('1111111111111111','Digital Marketing Manager'))
        validator=DailyLinkValidator()
        seed_verified_links(validator,p,[raw])
        with patch('link_validation.validate_job',side_effect=AssertionError('duplicate network read')):
            self.assertEqual(validator.check(normalize(raw)).status,'valid')


class ImportTests(SQLiteTrackerTests):
    def test_archived_job_is_not_restored(self):
        raw=RawListing(source='indeed',source_job_id='1111111111111111',url='https://www.indeed.com/viewjob?jk=1111111111111111',title='Digital Marketing Manager',company='Different Employer',location='Lehi, Utah',employment_type='full-time',description='Detailed verified description')
        with patch('search_indeed.description_is_sufficient',return_value=True):
            first=import_new([raw],self.tracker,Path(self.temp.name))
            with self.tracker.connection() as con, con:
                con.execute("UPDATE workspace_records SET archived=1 WHERE dataset='Job List' AND CAST(json_extract(values_json,'$.ID') AS INTEGER)=?",(first['added_ids'][0],))
            second=import_new([raw],self.tracker,Path(self.temp.name))
        self.assertEqual(second['added_ids'],[])
        self.assertEqual(second['excluded'][0]['reason'],'previously archived job')

    def test_append_and_rerun_preserve_original_rows(self):
        before=dict(self.tracker.scout().rows)
        raw=RawListing(source='indeed',source_job_id='1111111111111111',url='https://www.indeed.com/viewjob?jk=1111111111111111',title='Digital Marketing Manager',company='Different Employer',location='Lehi, Utah',employment_type='full-time',description='Detailed verified description')
        with patch('search_indeed.description_is_sufficient',return_value=True):
            first=import_new([raw],self.tracker,Path(self.temp.name))
            second=import_new([raw],self.tracker,Path(self.temp.name))
        self.assertEqual(len(first['added_ids']),1)
        self.assertEqual(second['added_ids'],[])
        self.assertTrue(first['readback_verified'])
        for row,data in before.items():self.assertEqual(dict(self.tracker.scout().rows)[row],data)


if __name__=='__main__':unittest.main()
