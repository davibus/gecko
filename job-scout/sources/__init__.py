"""Built-in Job Scout providers."""

from .adzuna import AdzunaProvider
from .base import JobSource, ProviderError
from .indeed import IndeedProvider
from .jooble import JoobleProvider
from .remotive import RemotiveProvider
from .web import WebCareerProvider

__all__ = [
    "AdzunaProvider", "IndeedProvider", "JoobleProvider", "RemotiveProvider",
    "JobSource", "ProviderError", "WebCareerProvider",
]
