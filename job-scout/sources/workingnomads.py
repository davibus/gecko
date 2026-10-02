"""Working Nomads public JSON feed provider."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_json_value


class WorkingNomadsProvider(JobSource):
    name = "workingnomads"
    endpoint = "https://www.workingnomads.com/api/exposed_jobs/"
    _job_id_pattern = re.compile(r"/job/go/(\d+)(?:/|$)")

    def __init__(self):
        self._cache: list[RawListing] | None = None

    def configured(self) -> bool:
        return True

    @staticmethod
    def _text(value) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise TypeError("Working Nomads text fields must be strings")
        return value

    @classmethod
    def _source_job_id(cls, url: str) -> str:
        match = cls._job_id_pattern.search(urlsplit(url).path)
        if match:
            return match.group(1)
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        return f"url-{digest}"

    @staticmethod
    def _tags(value) -> list[str]:
        if value in (None, ""):
            return []
        if not isinstance(value, str):
            raise TypeError("Working Nomads tags must be comma-separated text")
        tags = []
        seen = set()
        for raw_tag in value.split(","):
            tag = raw_tag.strip()
            key = tag.casefold()
            if tag and key not in seen:
                seen.add(key)
                tags.append(tag)
        return tags

    def full_feed(self):
        if self._cache is None:
            payload = get_json_value(self.endpoint, {"Accept": "application/json"})
            if not isinstance(payload, list):
                raise ProviderError("Working Nomads returned an unexpected response payload; expected a list")
            self._cache = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                try:
                    url = self._text(item.get("url"))
                    title = self._text(item.get("title"))
                    if not url.strip() or not title.strip():
                        continue
                    self._cache.append(RawListing(
                        source=self.name,
                        source_job_id=self._source_job_id(url),
                        url=url,
                        title=title,
                        company=self._text(item.get("company_name")),
                        location=self._text(item.get("location")),
                        description=self._text(item.get("description")),
                        date_posted=self._text(item.get("pub_date")),
                        remote_type="remote",
                        category=self._text(item.get("category_name")),
                        tags=self._tags(item.get("tags")),
                        metadata=item,
                    ))
                except (TypeError, ValueError):
                    continue
        yield from self._cache

    def search(self, request: SearchRequest):
        # Relevance is deliberately handled by Gecko's central role filter.
        yield from self.full_feed()
