"""Optional Firecrawl public-page retrieval; never accept search snippets as jobs."""
import os
import re
from threading import BoundedSemaphore

from .base import ProviderError
from .http import FetchedDocument, _validate_public_url, post_json

_REQUEST_SLOTS = BoundedSemaphore(2)


class FirecrawlClient:
    def __init__(self):
        self.key = os.getenv("FIRECRAWL_API_KEY", "").strip()
        self.cache = {}
        self.blocked = ""
        self.requests = 0

    def configured(self):
        return bool(self.key)

    def call(self, endpoint, payload):
        if not self.key:
            raise ProviderError("Firecrawl requires FIRECRAWL_API_KEY in .env.local")
        if self.blocked:
            raise ProviderError(self.blocked)
        try:
            self.requests += 1
            with _REQUEST_SLOTS:
                result = post_json(
                    "https://api.firecrawl.dev/v2/" + endpoint, payload,
                    {"Authorization": "Bearer " + self.key}, error_label="Firecrawl " + endpoint)
            if result.get("success") is not True:
                raise ProviderError("Firecrawl returned an unsuccessful response")
            return result.get("data") or {}
        except ProviderError as exc:
            if re.search(r"HTTP (401|402|403|429)\b", str(exc)):
                self.blocked = str(exc) + " (no repeated requests this run)"
            raise

    def document(self, url, *, wait_for=3000):
        _validate_public_url(url)
        if url not in self.cache:
            try:
                data = self.call("scrape", {
                    "url": url, "formats": ["rawHtml", "markdown"], "onlyMainContent": False,
                    "maxAge": 0, "proxy": "basic", "timeout": 20000, "waitFor": wait_for,
                })
                metadata = data.get("metadata") or {}
                status = metadata.get("statusCode", 200)
                if status != 200:
                    raise ProviderError(f"Firecrawl page returned HTTP {status}")
                body = data.get("rawHtml") or ""
                if not body:
                    raise ProviderError("Firecrawl returned no public HTML")
                final_url = metadata.get("url") or url
                _validate_public_url(final_url)
                self.cache[url] = FetchedDocument(body.encode(), final_url, "text/html")
            except ProviderError as exc:
                self.cache[url] = exc
        result = self.cache[url]
        if isinstance(result, ProviderError):
            raise result
        return result
