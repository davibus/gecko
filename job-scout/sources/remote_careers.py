"""Remote's current public careers system, migrated from its retired Greenhouse board."""
from concurrent.futures import ThreadPoolExecutor
import html
import re

from .base import ProviderError
from .http import get_document
from .search_discovery import SearchDiscoveryProvider


class RemoteCareersProvider(SearchDiscoveryProvider):
    def __init__(self):
        super().__init__("remote-careers", "site:apply.remote.com/jobs")

    def configured(self):
        return True

    def document(self, url):
        if self.firecrawl.configured():
            return self.firecrawl.document(url, wait_for=10000)
        return super().document(url)

    def full_feed(self):
        page = get_document("https://remote.com/openings").body.decode("utf-8", errors="replace")
        urls = sorted(set(re.findall(r'https://apply\.remote\.com/jobs/[a-f0-9-]{36}', html.unescape(page))))
        if not urls:
            raise ProviderError("Remote careers returned no job links; review the public page")
        def fetch(url):
            try:
                # The employer's public pages expose complete JobPosting JSON-LD.
                document = self.document(url)
                jobs = list(self.extract(document, url))
                for job in jobs:
                    job.metadata["_discovered_via"] = "remote.com/openings"
                return jobs
            except ProviderError as exc:
                self.errors.append({"url": url, "error": str(exc)})
                return []
        with ThreadPoolExecutor(max_workers=4) as pool:
            for jobs in pool.map(fetch, urls):
                yield from jobs
