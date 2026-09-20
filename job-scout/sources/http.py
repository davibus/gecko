"""Minimal JSON/HTML HTTP helpers with bounded reads and clear errors."""

from __future__ import annotations

import json
import ipaddress
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .base import ProviderError


USER_AGENT = "GeckoJobScout/1.0 (+local personal job search)"


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
    try:
        with build_opener(_PublicRedirectHandler()).open(request, timeout=25) as response:
            _validate_public_url(response.geturl())
            return FetchedDocument(
                body=response.read(limit),
                final_url=response.geturl(),
                content_type=response.headers.get_content_type(),
            )
    except (HTTPError, URLError, TimeoutError) as error:
        raise ProviderError(f"Request failed for {url}: {error}") from error


def get_bytes(url: str, headers: dict[str, str] | None = None, limit: int = 5_000_000) -> bytes:
    return get_document(url, headers, limit).body


def get_json(url: str, headers: dict[str, str] | None = None) -> dict:
    try:
        return json.loads(get_bytes(url, headers).decode("utf-8", errors="replace"))
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
