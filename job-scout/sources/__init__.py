"""Built-in Job Scout providers."""

from .adzuna import AdzunaProvider
from .base import JobSource, ProviderError
from .indeed import IndeedProvider
from .web import WebCareerProvider

__all__ = ["AdzunaProvider", "IndeedProvider", "JobSource", "ProviderError", "WebCareerProvider"]
