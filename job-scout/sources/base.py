"""Provider interface used by every job source."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable

from models import RawListing


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchRequest:
    query: str
    location: str = ""
    page: int = 1
    results_per_page: int = 20


class JobSource(ABC):
    """Small interface that keeps discovery independent of Gecko tailoring."""

    name: str

    @abstractmethod
    def configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def search(self, request: SearchRequest) -> Iterable[RawListing]:
        raise NotImplementedError
