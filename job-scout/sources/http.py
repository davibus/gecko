"""Minimal JSON/HTML HTTP helpers with bounded reads and clear errors."""

from __future__ import annotations

import json
import ipaddress
import os
import re
import time
import xml.etree.ElementTree as ET
from threading import Lock
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .base import ProviderError


USER_AGENT = "GeckoJobScout/1.0 (+local personal job search)"
REQUEST_EVENTS = []
_EVENT_LOCK = Lock()
_BILLING_FAILURES = {}

def safe_error(value):
    message = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1', str(value))
    for name, secret in os.environ.items():
        if secret and len(secret) > 6 and any(word in name for word in ('KEY', 'TOKEN', 'SECRET')):
            message = message.replace(secret, '[redacted]')
    return message


@dataclass
class FetchedDocument:
    body: bytes
    final_url: str
    content_type: str


def _validate_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ProviderError("Refusing an invalid or non-public HTTP URL")
    host = parts.hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ProviderError("Refusing a local HTTP destination")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ProviderError("Refusing a private or reserved HTTP destination")


class _PublicRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def get_document(url: str, headers: dict[str, str] | None = None, limit: int = 5_000_000) -> FetchedDocument:
    """Fetch a bounded public document and retain its post-redirect URL."""
    _validate_public_url(url)
    request = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    endpoint = urlsplit(url)._replace(query='', fragment='').geturl()
    billing_key = (urlsplit(url).hostname, (headers or {}).get('X-Subscription-Token', ''))
    with _EVENT_LOCK:
        blocked = _BILLING_FAILURES.get(billing_key)
    if blocked:
        raise ProviderError(blocked + ' (cached billing failure; no repeated request)')
    for attempt in range(2):
        started = time.monotonic()
        event = {'endpoint':endpoint, 'attempt':attempt+1}
        try:
            with build_opener(_PublicRedirectHandler()).open(request, timeout=25) as response:
                _validate_public_url(response.geturl())
                body = response.read(limit+1)
                if len(body)>limit:
                    raise ProviderError(f'Response exceeds {limit} byte limit: {endpoint}')
                event.update(status=response.status, bytes=len(body))
                try:
                    if body.lstrip().startswith((b'{',b'[')):
                        payload=json.loads(body)
                        records=payload if isinstance(payload,list) else next(
                            (payload[key] for key in ('jobs','results') if isinstance(payload.get(key),list)),None)
                        if records is None and isinstance(payload,dict):
                            records=payload.get('SearchResult',{}).get('SearchResultItems')
                        if isinstance(records,list):event['raw_records']=len(records)
                    elif b'<rss' in body[:300] or b'<feed' in body[:300]:
                        root=ET.fromstring(body)
                        event['raw_records']=sum(node.tag.rsplit('}',1)[-1] in {'item','entry'} for node in root.iter())
                except (ValueError,ET.ParseError,AttributeError):
                    pass
                return FetchedDocument(body, response.geturl(), response.headers.get_content_type())
        except (HTTPError, URLError, TimeoutError, ConnectionError) as error:
            status = getattr(error, 'code', None)
            event['status'] = status
            detail = safe_error(error)
            if isinstance(error, HTTPError):
                try:
                    payload = json.loads(error.read(8192))
                    if isinstance(payload,dict):
                        detail += ' | ' + safe_error(json.dumps(payload))
                except (ValueError, OSError):
                    pass
            message = f'Request failed for {endpoint}: {detail}'
            event['error'] = message
            if status == 402:
                with _EVENT_LOCK:
                    _BILLING_FAILURES[billing_key] = message
            transient = status in {429,500,502,503,504} or status is None
            delay = 1.0
            if status==429:
                retry_after = error.headers.get('Retry-After','')
                try: delay = max(float(retry_after), 1.0)
                except ValueError: delay = 2.0
            if attempt==0 and transient and delay<=60:
                time.sleep(delay)
                continue
            raise ProviderError(message) from error
        finally:
            event['seconds'] = round(time.monotonic()-started,3)
            with _EVENT_LOCK:
                REQUEST_EVENTS.append(event)


def get_bytes(url: str, headers: dict[str, str] | None = None, limit: int = 5_000_000) -> bytes:
    return get_document(url, headers, limit).body


def get_json(url: str, headers: dict[str, str] | None = None) -> dict:
    try:
        return json.loads(get_bytes(url, headers, limit=32_000_000).decode("utf-8", errors="replace"))
    except json.JSONDecodeError as error:
        raise ProviderError(f"Source returned invalid JSON: {safe_error(url)}") from error


def get_json_value(url: str, headers: dict[str, str] | None = None):
    """Return a JSON object or array for public feeds whose root is not an object."""
    try:
        return json.loads(get_bytes(url, headers, limit=32_000_000).decode("utf-8", errors="replace"))
    except json.JSONDecodeError as error:
        raise ProviderError(f"Source returned invalid JSON: {url}") from error


def post_json(
    url: str,
    payload: dict,
    headers: dict[str, str] | None = None,
    *,
    error_label: str = "provider endpoint",
) -> dict:
    """POST JSON without including a credential-bearing URL in errors."""
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
            **(headers or {}),
        },
    )
    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read(5_000_000)
    except HTTPError as error:
        raise ProviderError(f"Request failed for {error_label}: HTTP {error.code}") from error
    except (URLError, TimeoutError) as error:
        reason = getattr(error, "reason", type(error).__name__)
        raise ProviderError(f"Request failed for {error_label}: {reason}") from error
    try:
        value = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as error:
        raise ProviderError(f"Source returned invalid JSON from {error_label}") from error
    if not isinstance(value, dict):
        raise ProviderError(f"Source returned an unexpected response from {error_label}")
    return value
