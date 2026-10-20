"""Optional Firecrawl public-page retrieval; never accept search snippets as jobs."""
import os
import re
import time
from email.utils import parsedate_to_datetime
from threading import BoundedSemaphore

from .base import ProviderError
from .http import FetchedDocument, _validate_public_url, post_json

_REQUEST_SLOTS = BoundedSemaphore(1)
_NEXT_REQUEST = 0.0
# Conservative defaults fit the published free-tier scrape request rate.
MIN_INTERVAL = 6.5
MAX_RETRIES = 2
MAX_RETRY_WAIT = 60.0


def retry_delay(error, attempt):
    headers = getattr(error.__cause__, 'headers', None)
    raw = headers.get('Retry-After') if headers else None
    fallback = 15.0 * (2 ** attempt)
    if not raw:
        return fallback
    try:
        return max(0.0, float(raw))
    except (ValueError, TypeError):
        try:
            return max(0.0, parsedate_to_datetime(raw).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return fallback


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
        global _NEXT_REQUEST
        with _REQUEST_SLOTS:
            if self.blocked:
                raise ProviderError(self.blocked)
            for attempt in range(MAX_RETRIES + 1):
                delay = max(0.0, _NEXT_REQUEST - time.monotonic())
                if delay > MAX_RETRY_WAIT:
                    raise ProviderError('Firecrawl cooldown is active; retry in a later run.')
                if delay:
                    time.sleep(delay)
                self.requests += 1
                try:
                    result = post_json(
                        "https://api.firecrawl.dev/v2/" + endpoint, payload,
                        {"Authorization": "Bearer " + self.key}, error_label="Firecrawl " + endpoint)
                    if result.get("success") is not True:
                        raise ProviderError("Firecrawl returned an unsuccessful response")
                    return result.get("data") or {}
                except ProviderError as exc:
                    if re.search(r"HTTP 429\b", str(exc)):
                        delay = retry_delay(exc, attempt)
                        _NEXT_REQUEST = max(_NEXT_REQUEST, time.monotonic() + delay)
                        if attempt < MAX_RETRIES and delay <= MAX_RETRY_WAIT:
                            continue
                        self.blocked = 'Firecrawl rate limit persisted after bounded retries; remaining requests skipped this run.'
                    elif re.search(r"HTTP (401|402|403)\b", str(exc)):
                        self.blocked = str(exc) + " (no repeated requests this run)"
                    raise
                finally:
                    _NEXT_REQUEST = max(_NEXT_REQUEST, time.monotonic() + MIN_INTERVAL)

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
