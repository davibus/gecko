"""Minimal JSON/HTML HTTP helpers with bounded reads and clear errors."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import ProviderError


USER_AGENT = "GeckoJobScout/1.0 (+local personal job search)"


@dataclass
class FetchedDocument:
    body: bytes
    final_url: str
    content_type: str


def get_document(url: str, headers: dict[str, str] | None = None, limit: int = 5_000_000) -> FetchedDocument:
    """Fetch a bounded public document and retain its post-redirect URL."""
    request = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urlopen(request, timeout=25) as response:
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
