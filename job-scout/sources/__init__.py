"""Built-in Job Scout providers."""

from .adzuna import AdzunaProvider
from .ats import AshbyProvider, GreenhouseProvider, LeverProvider, WorkableProvider
from .base import JobSource, ProviderError
from .jobicy import JobicyProvider
from .indeed import IndeedProvider, ManualIndeedProvider
from .jooble import JoobleProvider
from .remotive import RemotiveProvider
from .remoteok import RemoteOkProvider
from .search_discovery import SearchDiscoveryProvider
from .themuse import TheMuseProvider
from .unavailable import UnavailableProvider
from .usajobs import UsaJobsProvider
from .web import WebCareerProvider
from .weworkremotely import WeWorkRemotelyProvider
from .workingnomads import WorkingNomadsProvider

__all__ = [
    "AdzunaProvider", "AshbyProvider", "GreenhouseProvider", "IndeedProvider",
    "JobicyProvider", "LeverProvider", "ManualIndeedProvider", "JoobleProvider",
    "RemoteOkProvider", "RemotiveProvider", "SearchDiscoveryProvider", "TheMuseProvider",
    "UnavailableProvider", "UsaJobsProvider", "WeWorkRemotelyProvider", "WorkingNomadsProvider",
    "WorkableProvider",
    "JobSource", "ProviderError", "WebCareerProvider",
]
