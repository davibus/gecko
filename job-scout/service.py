"""Discovery orchestration, deliberately independent of resume generation."""

from __future__ import annotations

from dataclasses import dataclass, field

from deduplicate import find_duplicate
from enrichment import enrich_and_rescore
from normalize import normalize
from scoring import score_job
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
    scored: int = 0
    added: int = 0
    updated: int = 0
    strong: int = 0
    weak: int = 0
    duplicates: int = 0
    cross_provider_duplicates: int = 0
    provisional: int = 0
    score_80_plus: int = 0
    score_70_79: int = 0
    score_below_70: int = 0


def _discover_listings(
    listings,
    store: JobStore,
    preferences: dict,
    resume_text: str,
    threshold: int,
    *,
    require_content: bool,
) -> SearchSummary:
    """Normalize, score, deduplicate, and save a stream of raw listings."""
    summary = SearchSummary()
    known = store.all()
    existing_ids = {job.id for job in known}
    updated_ids: set[int] = set()
    for raw in listings:
        if require_content and (not raw.title or not raw.description):
            continue
        summary.fetched += 1
        job = normalize(raw)
        summary.normalized += 1
        result = score_job(job, preferences, resume_text)
        summary.scored += 1
        job.match_score = result.total
        job.match_strengths = result.strengths
        job.match_weaknesses = result.weaknesses
        job.evidence_confidence = result.confidence
        job.provisional = result.provisional
        job.evidence_levels = result.evidence_levels
        if job.match_score >= 80:
            summary.score_80_plus += 1
        elif job.match_score >= 70:
            summary.score_70_79 += 1
        else:
            summary.score_below_70 += 1
        duplicate = find_duplicate(job, known)
        should_resolve = (
            raw.source.casefold() in {"jooble", "web-careers"}
            or classify_url(raw.url) == "official_ats"
        )
        if duplicate:
            retained = job.match_score >= threshold
            store.merge(duplicate.id, job, retained=retained)
            if retained and should_resolve:
                merged = store.get(duplicate.id)
                if merged and merged.url_verification_status == "not_attempted":
                    resolve_and_store(merged, store)
            summary.duplicates += 1
            duplicate_sources = {duplicate.source.casefold(), *(
                link.get("source", "").casefold() for link in duplicate.source_links
            )}
            if raw.source.casefold() not in duplicate_sources:
                summary.cross_provider_duplicates += 1
            if duplicate.id in existing_ids and duplicate.id not in updated_ids:
                updated_ids.add(duplicate.id)
                summary.updated += 1
            continue
        retained = job.match_score >= threshold
        job_id = store.save(job, retained=retained)
        job.id = job_id
        known.append(job)
        summary.added += 1
        if retained and should_resolve:
            job = resolve_and_store(job, store)
        if retained and job.provisional and job.source.lower() == "adzuna":
            job = enrich_and_rescore(job, store, preferences, resume_text)
            retained = job.match_score >= threshold
        if retained and job.provisional:
            summary.provisional += 1
        elif retained:
            summary.strong += 1
        else:
            summary.weak += 1
    return summary


def discover(
    provider: JobSource,
    requests: list[SearchRequest],
    store: JobStore,
    preferences: dict,
    resume_text: str,
    minimum_score: int | None = None,
) -> SearchSummary:
    """Fetch, normalize, score, dedupe, and persist listings from one provider."""
    threshold = int(preferences["minimum_score"] if minimum_score is None else minimum_score)
    listings = (raw for request in requests for raw in provider.search(request))
    return _discover_listings(
        listings, store, preferences, resume_text, threshold, require_content=True,
    )


def discover_remotive_full_feed(
    provider: RemotiveProvider,
    store: JobStore,
    preferences: dict,
    resume_text: str,
) -> SearchSummary:
    """Score and retain the complete cached Remotive feed without query filtering."""
    summary = _discover_listings(
        provider.full_feed(), store, preferences, resume_text, 0, require_content=False,
    )
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
