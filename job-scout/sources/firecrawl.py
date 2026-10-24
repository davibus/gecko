"""Optional Firecrawl public-page retrieval; never accept search snippets as jobs."""
import os
import re
import time
from threading import BoundedSemaphore

from .base import ProviderError
from .http import FetchedDocument, _validate_public_url, post_json, get_json

_REQUEST_SLOTS = BoundedSemaphore(1)
_NEXT_REQUEST = 0.0
# Conservative defaults fit the published free-tier scrape request rate.
MIN_INTERVAL = 6.5
MAX_RETRY_WAIT = 60.0


def target_failure(exc, endpoint):
    """Only explicit target restrictions are local; unknown 403s fail closed."""
    if endpoint != 'scrape' or getattr(exc, 'http_status', None) != 403:
        return False
    code = getattr(exc, 'provider_code', '').upper()
    detail = getattr(exc, 'provider_detail', '').casefold()
    return code in {'SCRAPE_NOT_ALLOWED', 'SCRAPING_NOT_ALLOWED', 'UNSUPPORTED_WEBSITE',
                    'WEBSITE_NOT_SUPPORTED', 'ROBOTS_TXT_BLOCKED'} or any(
        phrase in detail for phrase in ('website is not supported', 'site is not supported',
                                        'do not support scraping this', 'website is blocked',
                                        'scraping this website is not allowed'))


class FirecrawlClient:
    def __init__(self, *, history=None, settings=None):
        from firecrawl_state import config
        self.key = os.getenv("FIRECRAWL_API_KEY", "").strip()
        self.settings = settings or config()
        self._settings_override = settings is not None
        self._history = history
        self.cache = {}
        self.blocked = ""
        self.requests = 0

    def configured(self):
        self.refresh_settings()
        return bool(self.key) and self.settings["enabled"]

    def refresh_settings(self):
        if not self._settings_override:
            from firecrawl_state import config
            self.settings = config()
            if self._history is not None:
                self._history.settings = self.settings

    @property
    def history(self):
        if self._history is None:
            from firecrawl_state import History
            self._history = History(settings=self.settings)
        return self._history

    def reconcile_balance(self):
        """GET-only reconciliation, called at runtime only after paid use is enabled."""
        from firecrawl_state import utcnow
        from datetime import datetime
        with self.history.connect() as con:
            latest = con.execute('SELECT at FROM balances ORDER BY id DESC LIMIT 1').fetchone()
            settled = con.execute('SELECT COALESCE(SUM(confirmed),0) FROM requests').fetchone()[0]
        now = utcnow()
        if latest and (now - datetime.fromisoformat(latest['at'])).total_seconds() <= self.settings['balance_max_age_seconds']:
            return
        try:
            result = get_json('https://api.firecrawl.dev/v2/team/credit-usage',
                              {'Authorization': 'Bearer ' + self.key})
            if result.get('success') is not True:
                raise ProviderError('Firecrawl account balance is unavailable')
            self.history.record_balance(result.get('data') or {}, now=now, settled_before=settled)
        except Exception as exc:
            raise ProviderError('Firecrawl account balance reconciliation failed; paid requests stopped') from exc

    def call(self, endpoint, payload):
        from firecrawl_state import request_key, utcnow, estimated_cost
        self.refresh_settings()
        if not self.settings['enabled']:
            raise ProviderError('Paid Firecrawl usage is disabled in preferences/firecrawl.json')
        if not self.key:
            raise ProviderError("Firecrawl requires FIRECRAWL_API_KEY in .env.local")
        if self.blocked:
            raise ProviderError(self.blocked)
        estimated_cost(endpoint, payload, self.settings)
        cached = self.history.cached(request_key(endpoint, payload), utcnow())
        if cached is not None:
            return cached.get('data') or {}
        global _NEXT_REQUEST
        with _REQUEST_SLOTS:
            if self.blocked:
                raise ProviderError(self.blocked)
            # Recheck after waiting for another worker's durable response cache.
            cached = self.history.cached(request_key(endpoint, payload), utcnow())
            if cached is not None:
                return cached.get('data') or {}
            delay = max(0.0, _NEXT_REQUEST - time.monotonic())
            if delay > MAX_RETRY_WAIT:
                raise ProviderError('Firecrawl cooldown is active; retry in a later run.')
            if delay:
                time.sleep(delay)
            self.reconcile_balance()
            reservation = self.history.reserve(endpoint, payload)
            self.requests += 1
            try:
                result = post_json(
                    "https://api.firecrawl.dev/v2/" + endpoint, payload,
                    {"Authorization": "Bearer " + self.key}, error_label="Firecrawl " + endpoint)
            except Exception as exc:
                from .http import safe_error
                self.history.settle(reservation, error=safe_error(exc))
                if re.search(r"HTTP (401|402|403|429)\b", str(exc)) and not target_failure(exc, endpoint):
                    self.blocked = 'Firecrawl access/rate/billing error; automatic retries stopped'
                raise
            else:
                self.history.settle(reservation, response=result)
                if result.get("success") is not True:
                    raise ProviderError("Firecrawl returned an unsuccessful response; retry blocked")
                return result.get("data") or {}
            finally:
                _NEXT_REQUEST = max(_NEXT_REQUEST, time.monotonic() + MIN_INTERVAL)

    def document(self, url, *, wait_for=3000):
        _validate_public_url(url)
        if url not in self.cache:
            try:
                data = self.call("scrape", {
                    "url": url, "formats": ["rawHtml", "markdown"], "onlyMainContent": False,
                    "maxAge": 86400000, "proxy": "basic", "timeout": 20000, "waitFor": wait_for,
                    "parsers": [],
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
