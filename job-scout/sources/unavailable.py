"""Explicit non-scraping provider states for sources without a supported feed."""

from __future__ import annotations

from .base import JobSource, ProviderError, SearchRequest


class UnavailableProvider(JobSource):
    def __init__(self, name: str, reason: str, *, status: str = "unsupported"):
        self.name = name
        self.reason = reason
        self.status = status

    def configured(self) -> bool:
        return False

    def search(self, request: SearchRequest):
        raise ProviderError(self.reason)
