"""Indeed result-page discovery, separate from general web-search indexes."""
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit, parse_qs
import re
import time

from preferences import load_preferences
from .base import JobSource, ProviderError
from .firecrawl import FirecrawlClient
from .indeed import _structured_listings, extract_indeed_job_key, application_method_from_page


def indeed_url(url, path=None):
    parts = urlsplit(url)
    return (parts.scheme == 'https' and parts.hostname in ('www.indeed.com','indeed.com')
            and not parts.username and parts.port in (None,443)
            and (path is None or parts.path == path))


class ResultPage(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.jobs, self.next_url = url, {}, ''

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag != 'a': return
        key = a.get('data-jk','')
        if re.fullmatch(r'[a-fA-F0-9]{16}',key) and ('jcs-JobTitle' in a.get('class','') or a.get('id','').startswith(('job_','sj_'))):
            self.jobs[key.lower()] = a.get('aria-label','').removeprefix('full details of ').strip()
        if a.get('data-testid') == 'pagination-page-next' or a.get('aria-label','').lower() == 'next page':
            target = urljoin(self.url,a.get('href',''))
            if not indeed_url(target,'/jobs'):
                raise ProviderError('Indeed next-page link left the allowed results page')
            self.next_url = target


class IndeedSearchProvider(JobSource):
    name = 'indeed'
    discovery_mode = 'Indeed public search pages via Firecrawl'

    def __init__(self, *, fetch=None, max_pages=5, max_jobs=150, queries=None, locations=None):
        self.firecrawl = FirecrawlClient()
        self.fetch = fetch or self.firecrawl.document
        self.custom_fetch = fetch is not None
        self.max_pages, self.max_jobs = max_pages, max_jobs
        if self.firecrawl.settings.get('usage_unlimited'):
            self.max_pages = self.max_jobs = 2**31 - 1
        self.queries = queries or load_preferences()['target_roles']
        self.locations = locations or ['Utah','Remote']
        self.errors, self.exclusions, self.acquisition_events = [], [], []
        self.seen_jobs, self.seen_pages = set(), set()
        self.limits = []
        self.last_request = 0.0
        self.verified_urls = set()

    def retrieve(self, url):
        if self.custom_fetch:return self.fetch(url)
        # The shared ledger owns pacing, cache reuse and failure reservations.
        # A provider wrapper must never erase its cooldown or retry a paid call.
        return self.fetch(url)

    def configured(self):
        return self.custom_fetch or self.firecrawl.configured()

    def search(self, request):
        raise ProviderError('Indeed result-page collection uses full_feed() with observed pagination links')

    def detail(self, item):
        key,title = item
        url = 'https://www.indeed.com/viewjob?' + urlencode({'jk':key})
        try:
            document = self.retrieve(url)
            if not indeed_url(document.final_url) or extract_indeed_job_key(document.final_url).lower() != key:
                raise ProviderError('Posting redirected to a different job or non-Indeed destination')
            listings = _structured_listings(document)
            matches = [j for j in listings if extract_indeed_job_key(j.url).lower() == key]
            if len(matches) != 1:
                raise ProviderError('Expected one complete JobPosting matching the Indeed job key')
            listing = matches[0]
            clean = lambda value:' '.join(re.findall(r'\w+',value.casefold()))
            if title and clean(title) != clean(listing.title):
                raise ProviderError('Result-card title does not match the posting; needs review')
            page = document.body.decode('utf-8',errors='replace')
            method = application_method_from_page(page)
            if re.search(r'expired|no longer available',method,re.I):
                return None, {'key':key,'reason':'expired posting'}, None
            listing.source='indeed';listing.source_job_id=key;listing.url=url
            listing.metadata.update(_discovered_via='indeed-results-page',_retrieved_via='firecrawl',_indeed_application_method=method)
            self.verified_urls.add(url)
            return listing,None,None
        except (ProviderError,OSError,ValueError) as exc:
            if re.search(r'HTTP(?: Error)? (404|410)\b',str(exc)):
                return None,{'key':key,'reason':'posting no longer available','detail':str(exc)},None
            return None,None,{'key':key,'url':url,'error':str(exc)}

    def full_feed(self):
        if not self.configured(): raise ProviderError('Indeed page search requires FIRECRAWL_API_KEY')
        for query in self.queries:
            for location in self.locations:
                url = 'https://www.indeed.com/jobs?' + urlencode({'q':query,'l':location})
                for number in range(1,self.max_pages+1):
                    event={'query':query,'location':location,'page':number,'url':url,'status':'attempted'}
                    self.acquisition_events.append(event)
                    try:
                        if url in self.seen_pages: raise ProviderError('Repeated Indeed pagination URL')
                        self.seen_pages.add(url)
                        document=self.retrieve(url)
                        if not indeed_url(document.final_url,'/jobs'):raise ProviderError('Search redirected away from Indeed results')
                        parsed=ResultPage(document.final_url)
                        body=document.body.decode('utf-8',errors='replace');parsed.feed(body)
                        if not parsed.jobs:raise ProviderError('No visible job cards found; empty or blocked page requires review')
                        unseen=[(k,t) for k,t in parsed.jobs.items() if k not in self.seen_jobs]
                        remaining=self.max_jobs-len(self.seen_jobs)
                        selected=unseen[:remaining]
                        self.seen_jobs.update(k for k,_ in selected)
                        successes=0
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            for listing,exclusion,error in pool.map(self.detail,selected):
                                if exclusion:self.exclusions.append(exclusion)
                                if error:self.errors.append(error)
                                if listing:
                                    listing.metadata['_query_used_to_find'] = query
                                    successes+=1
                                    yield listing
                        event.update(status='completed',cards=len(parsed.jobs),new_keys=len(selected),retrieved=successes)
                        if len(self.seen_jobs)>=self.max_jobs:
                            self.limits.append({'reason':'posting budget reached','limit':self.max_jobs,'query':query,'location':location})
                            return
                        if not parsed.next_url:break
                        if not unseen:raise ProviderError('Pagination returned only previously seen jobs; stopped instead of looping')
                        next_query=parse_qs(urlsplit(parsed.next_url).query)
                        if next_query.get('q')!=[query] or next_query.get('l')!=[location]:raise ProviderError('Pagination changed the requested query or location')
                        url=parsed.next_url
                        if number==self.max_pages:self.limits.append({'reason':'page budget reached','query':query,'location':location,'next_url':url})
                    except (ProviderError,OSError,ValueError) as exc:
                        event.update(status='failed',error=str(exc))
                        self.errors.append({'url':url,'error':str(exc)})
                        break
                if self.firecrawl.blocked:return


def seed_verified_links(validator, provider, listings):
    """Reuse only this provider instance's fresh, identity-checked HTTP 200 reads."""
    if not isinstance(provider,IndeedSearchProvider) or validator is None:return
    from link_validation import LinkResult, candidate_urls
    from normalize import normalize
    for raw in listings:
        if raw.url not in provider.verified_urls:continue
        job=normalize(raw)
        key='|'.join(candidate_urls(job))
        with validator._lock:
            validator.results[key]=LinkResult('valid',job.url,job.url,
                'Fresh Firecrawl HTTP 200; Indeed job key and title verified',200)
