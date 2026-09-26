"""Discovery orchestration without compatibility scoring or score-based gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re

from deduplicate import find_duplicate
from description_retrieval import description_is_sufficient, retrieve_full_description
from link_validation import DailyLinkValidator
from normalize import normalize
from role_filter import is_relevant_role
from source_policy import is_jooble_candidate
from sources.base import JobSource, SearchRequest
from sources.remotive import RemotiveProvider
from storage import JobStore
from url_resolution import classify_url, resolve_and_store


@dataclass
class SearchSummary:
    raw_retrieved: int = 0
    rss_retrieved: int = 0
    rss_unique: int = 0
    rss_duplicates_removed: int = 0
    successful_feeds: int = 0
    failed_feeds: int = 0
    feed_results: list[dict] = field(default_factory=list)
    api_retrieved: int = 0
    source_backend: str = ""
    fetched: int = 0
    normalized: int = 0
    added: int = 0
    updated: int = 0
    duplicates: int = 0
    cross_provider_duplicates: int = 0
    unique_available: int = 0
    unique_imported: int = 0
    filtered_by_role: int = 0
    jooble_excluded: int = 0
    new_job_ids: list[int] = field(default_factory=list)
    existing_job_ids: list[int] = field(default_factory=list)
    eligibility_includes_usa: int = 0
    eligibility_worldwide: int = 0
    example_jobs: list[dict] = field(default_factory=list)
    backend_qualifying: dict[str, int] = field(default_factory=dict)
    backend_added: dict[str, int] = field(default_factory=dict)


def _capture_full_description(job, store):
    """Persist the fullest legitimate description without evaluating candidate fit."""
    outcome = retrieve_full_description(job, prefer_fuller=True)
    if job.id is not None and job.authoritative_url:
        store.save_url_resolution(job)
    if job.enrichment_status == "not_attempted":
        job.original_description = job.description
        job.original_url = job.url
    job.enriched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    current = max((job.description or "", job.enriched_description or ""), key=len)
    if (outcome.status == "succeeded" and len(outcome.description) > len(current)
            and description_is_sufficient(outcome.description)):
        job.enrichment_status = "succeeded"
        job.enrichment_error = ""
        job.enriched_description = outcome.description
        job.enriched_source_url = outcome.source_url
    elif description_is_sufficient(current):
        job.enrichment_status = "succeeded"
        job.enrichment_error = "Existing stored description remained the fullest reliable source."
    else:
        job.enrichment_status = "failed"
        job.enrichment_error = (outcome.error + " " + " | ".join(
            attempt.summary() for attempt in outcome.attempts
        )).strip()
    store.save_enrichment(job)
    return job


def _eligibility_flags(location: str) -> tuple[bool, bool]:
    value = " ".join(re.findall(r"[a-z0-9]+", (location or "").casefold()))
    worldwide = "worldwide" in value
    includes_usa = worldwide or any(term in value for term in (
        "united states", "usa", "u s", "north america", "northern america",
        "americas", "anywhere", "global",
    ))
    return includes_usa, worldwide


def _same_source_identity_conflicts(candidate, existing) -> bool:
    source = candidate.source.casefold()
    source_job_id = candidate.source_job_id.casefold()
    if not source or not source_job_id:
        return False
    existing_ids = {
        str(link.get("source_job_id") or "").casefold()
        for link in existing.source_links
        if str(link.get("source") or "").casefold() == source
        and str(link.get("source_job_id") or "").strip()
    }
    if existing.source.casefold() == source and existing.source_job_id:
        existing_ids.add(existing.source_job_id.casefold())
    return bool(existing_ids and source_job_id not in existing_ids)


def _discover_listings(
    listings,
    store: JobStore,
    *,
    require_content: bool,
    preserve_existing: bool = False,
    preexisting_ids: set[int] | None = None,
    link_validator: DailyLinkValidator | None = None,
) -> SearchSummary:
    """Normalize, role-filter, deduplicate, and save listings without fit evaluation."""
    summary = SearchSummary()
    known = store.all()
    existing_ids = {job.id for job in known} if preexisting_ids is None else set(preexisting_ids)
    updated_ids: set[int] = set()
    existing_seen_ids: set[int] = set()
    for raw in listings:
        summary.fetched += 1
        if is_jooble_candidate(source=raw.source, urls=(raw.url,), metadata=raw.metadata):
            summary.jooble_excluded += 1
            continue
        if require_content and (not raw.title or not raw.description):
            continue
        if not is_relevant_role(raw.title):
            summary.filtered_by_role += 1
            continue
        discovery_backends = raw.metadata.get("_web_search_backends", [])
        for backend in discovery_backends:
            summary.backend_qualifying[backend] = summary.backend_qualifying.get(backend, 0) + 1
        job = normalize(raw)
        summary.normalized += 1
        if link_validator is not None:
            link_result = link_validator.check(job)
            if link_result.status == "dead":
                link_validator.record_removed(job, link_result)
                continue
        duplicate = find_duplicate(
            job, [item for item in known if not _same_source_identity_conflicts(job, item)]
        )
        should_resolve = (
            raw.source.casefold() in {"adzuna", "web-careers"}
            or classify_url(raw.url) == "official_ats"
        )
        if duplicate:
            was_existing = duplicate.id in existing_ids
            if not (preserve_existing and was_existing):
                store.merge(duplicate.id, job)
                merged = store.get(duplicate.id)
                if merged and should_resolve and merged.url_verification_status == "not_attempted":
                    merged = resolve_and_store(merged, store)
                if merged and (raw.source.casefold() == "adzuna" or not description_is_sufficient(
                        max((merged.description or "", merged.enriched_description or ""), key=len))):
                    _capture_full_description(merged, store)
            summary.duplicates += 1
            duplicate_sources = {duplicate.source.casefold(), *(
                link.get("source", "").casefold() for link in duplicate.source_links
            )}
            if raw.source.casefold() not in duplicate_sources:
                summary.cross_provider_duplicates += 1
            if was_existing:
                if duplicate.id not in existing_seen_ids:
                    existing_seen_ids.add(duplicate.id)
                    summary.existing_job_ids.append(duplicate.id)
                if not preserve_existing and duplicate.id not in updated_ids:
                    updated_ids.add(duplicate.id)
                    summary.updated += 1
            continue
        job_id = store.save(job)
        job.id = job_id
        known.append(job)
        summary.added += 1
        summary.new_job_ids.append(job_id)
        for backend in discovery_backends:
            summary.backend_added[backend] = summary.backend_added.get(backend, 0) + 1
        if should_resolve:
            job = resolve_and_store(job, store)
        if job.source.lower() == "adzuna" or not description_is_sufficient(job.description):
            _capture_full_description(job, store)
    return summary


def discover(
    provider: JobSource,
    requests: list[SearchRequest],
    store: JobStore,
    *,
    preserve_existing: bool = False,
    preexisting_ids: set[int] | None = None,
    link_validator: DailyLinkValidator | None = None,
) -> SearchSummary:
    """Fetch, normalize, role-filter, deduplicate, and persist listings."""
    listings = (raw for request in requests for raw in provider.search(request))
    return _discover_listings(
        listings, store, require_content=True, preserve_existing=preserve_existing,
        preexisting_ids=preexisting_ids, link_validator=link_validator,
    )


def discover_remotive_full_feed(
    provider: RemotiveProvider,
    store: JobStore,
    limit: int = 100,
    *,
    preserve_existing: bool = False,
    preexisting_ids: set[int] | None = None,
    link_validator: DailyLinkValidator | None = None,
) -> SearchSummary:
    """Persist a bounded, role-filtered Remotive feed in newest-first order."""
    if limit < 1:
        raise ValueError("Remotive limit must be at least 1")
    pool = [raw for raw in provider.full_feed() if is_relevant_role(raw.title)]
    if link_validator is not None:
        normalized = [(raw, normalize(raw)) for raw in pool]
        checked = link_validator.check_existing([job for _, job in normalized])
        results = {id(job): result for job, result in checked}
        for raw, job in normalized:
            result = results[id(job)]
            if result.status == "dead":
                link_validator.record_removed(job, result)
        pool = [raw for raw, job in normalized if results[id(job)].status != "dead"]
    pool.sort(key=lambda raw: (raw.date_posted or "", raw.title.casefold()), reverse=True)
    selected = pool[:limit]
    summary = _discover_listings(
        selected, store, require_content=False, preserve_existing=preserve_existing,
        preexisting_ids=preexisting_ids,
    )
    summary.filtered_by_role = max(provider.rss_count - len(pool), 0)
    summary.fetched = len(pool)
    summary.normalized = len(pool)
    summary.unique_available = len(pool)
    summary.unique_imported = len(selected)
    summary.example_jobs = [
        {"title": raw.title, "company": raw.company, "location": raw.location, "url": raw.url}
        for raw in selected[:25]
    ]
    for raw in selected:
        includes_usa, worldwide = _eligibility_flags(raw.location)
        summary.eligibility_includes_usa += int(includes_usa)
        summary.eligibility_worldwide += int(worldwide)
    summary.raw_retrieved = provider.raw_count
    summary.rss_retrieved = provider.rss_raw_count
    summary.rss_unique = provider.rss_count
    summary.rss_duplicates_removed = provider.rss_duplicate_count
    summary.successful_feeds = provider.successful_feed_count
    summary.failed_feeds = provider.failed_feed_count
    summary.feed_results = provider.feed_results
    summary.api_retrieved = provider.api_count
    summary.source_backend = provider.active_source
    return summary
