"""We Work Remotely official RSS provider."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from models import RawListing
from .base import JobSource, ProviderError, SearchRequest
from .http import get_bytes


class WeWorkRemotelyProvider(JobSource):
    name = "weworkremotely"
    endpoint = "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss"

    def __init__(self):
        self._cache: list[RawListing] | None = None

    def configured(self) -> bool:
        return True

    @staticmethod
    def _value(item: ET.Element, *names: str) -> str:
        wanted = {name.casefold() for name in names}
        for child in item:
            if child.tag.rsplit("}", 1)[-1].casefold() in wanted:
                return "".join(child.itertext()).strip()
        return ""

    def full_feed(self):
        if self._cache is None:
            try:
                root = ET.fromstring(get_bytes(self.endpoint, {
                    "Accept": "application/rss+xml, application/xml, text/xml",
                }))
            except ET.ParseError as error:
                raise ProviderError(f"We Work Remotely returned invalid RSS: {error}") from error
            self._cache = []
            for item in root.iter():
                if item.tag.rsplit("}", 1)[-1].casefold() != "item":
                    continue
                url = self._value(item, "link", "guid")
                title = self._value(item, "title")
                company = self._value(item, "company", "creator")
                if not company and ":" in title:
                    company, title = (part.strip() for part in title.split(":", 1))
                identifier = self._value(item, "guid") or url
                source_id = hashlib.sha256(identifier.encode()).hexdigest()[:24]
                posted = self._value(item, "pubDate")
                try:
                    posted = parsedate_to_datetime(posted).isoformat() if posted else ""
                except (TypeError, ValueError, OverflowError):
                    pass
                self._cache.append(RawListing(
                    source=self.name, source_job_id=source_id, url=url, title=title,
                    company=company, location=self._value(item, "region", "location") or "Remote",
                    description=self._value(item, "description", "encoded"),
                    employment_type=self._value(item, "type"), date_posted=posted,
                    remote_type="remote", category="Sales and Marketing",
                    metadata={"feed": "official-rss"},
                ))
        yield from self._cache

    def search(self, request: SearchRequest):
        yield from self.full_feed()
