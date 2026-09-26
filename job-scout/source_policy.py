"""Discovery source policies shared by Job Scout and Gecko handoffs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit


JOOBLE_HOSTS = ("jooble.org", "jooble.com")


def is_jooble_url(value: object) -> bool:
    """Return True only for URLs whose hostname is Jooble-owned."""
    text = str(value or "").strip()
    if not text:
        return False
    try:
        host = (urlsplit(text).hostname or "").casefold().rstrip(".")
    except ValueError:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in JOOBLE_HOSTS)


def _candidate_urls(metadata: object) -> Iterable[object]:
    if not isinstance(metadata, Mapping):
        return ()
    return (
        value
        for key, value in metadata.items()
        if any(token in str(key).casefold() for token in ("url", "link", "apply"))
    )


def is_jooble_candidate(
    *, source: object = "", urls: Iterable[object] = (), metadata: object = None
) -> bool:
    """Reject Jooble provenance or a Jooble job/application destination."""
    if str(source or "").strip().casefold() == "jooble":
        return True
    return any(is_jooble_url(value) for value in (*urls, *_candidate_urls(metadata)))
