"""Discovery orchestration, deliberately independent of resume generation."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from deduplicate import find_duplicate
from enrichment import enrich_and_rescore
from normalize import normalize
from role_filter import is_relevant_role
from scoring import score_job
from sources.base import JobSource, SearchRequest
from sources.remotive import RemotiveProvider
from storage import JobStore
from url_resolution import classify_url, resolve_and_store
from link_validation import DailyLinkValidator


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
    unique_available: int = 0
    unique_imported: int = 0
    filtered_before_scoring: int = 0
    new_job_ids: list[int] = field(default_factory=list)
    existing_job_ids: list[int] = field(default_factory=list)
    eligibility_includes_usa: int = 0
    eligibility_worldwide: int = 0
    top_jobs: list[dict] = field(default_factory=list)
    backend_qualifying: dict[str, int] = field(default_factory=dict)
    backend_added: dict[str, int] = field(default_factory=dict)


REMOTIVE_RELEVANCE_TERMS = (
    "digital marketing", "paid search", "ppc", "sem", "performance marketing",
    "marketing analytics", "e-commerce", "ecommerce", "seo", "growth marketing",
    "marketing operations", "martech", "marketing automation", "product marketing",
    "business intelligence", "digital strategy", "account marketing", "client marketing",
)


def _remotive_relevance(raw) -> int:
    text = " ".join((raw.title, raw.category, " ".join(raw.tags), raw.description)).casefold()
    return sum(1 for term in REMOTIVE_RELEVANCE_TERMS if term in text)


def _eligibility_flags(location: str) -> tuple[bool, bool]:
    value = " ".join(re.findall(r"[a-z0-9]+", (location or "").casefold()))
    worldwide = "worldwide" in value
    includes_usa = worldwide or any(term in value for term in (
        "united states", "usa", "u s", "north america", "northern america",
        "americas", "anywhere", "global",
    ))
    return includes_usa, worldwide


def _same_source_identity_conflicts(candidate, existing) -> bool:
    """Do not fuzzy-merge two authoritative IDs from the same provider."""
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
    preferences: dict,
    resume_text: str,
    threshold: int,
    *,
    require_content: bool,
    preserve_existing: bool = False,
    preexisting_ids: set[int] | None = None,
    link_validator: DailyLinkValidator | None = None,
) -> SearchSummary:
    """Normalize, score, deduplicate, and save a stream of raw listings."""
    summary = SearchSummary()
    known = store.all()
    existing_ids = (
        {job.id for job in known} if preexisting_ids is None else set(preexisting_ids)
    )
    updated_ids: set[int] = set()
    existing_seen_ids: set[int] = set()
    for raw in listings:
        if require_content and (not raw.title or not raw.description):
            continue
        summary.fetched += 1
        if not is_relevant_role(raw.title):
            summary.filtered_before_scoring += 1
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
        duplicate = find_duplicate(
            job, [item for item in known if not _same_source_identity_conflicts(job, item)]
        )
        should_resolve = (
            raw.source.casefold() in {"jooble", "web-careers"}
            or classify_url(raw.url) == "official_ats"
        )
        if duplicate:
            retained = job.match_score >= threshold
            was_existing = duplicate.id in existing_ids
            if not (preserve_existing and was_existing):
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
            if was_existing:
                if duplicate.id not in existing_seen_ids:
                    existing_seen_ids.add(duplicate.id)
                    summary.existing_job_ids.append(duplicate.id)
                if not preserve_existing and duplicate.id not in updated_ids:
                    updated_ids.add(duplicate.id)
                    summary.updated += 1
            continue
        retained = job.match_score >= threshold
        job_id = store.save(job, retained=retained)
        job.id = job_id
        known.append(job)
        summary.added += 1
        for backend in discovery_backends:
            summary.backend_added[backend] = summary.backend_added.get(backend, 0) + 1
        summary.new_job_ids.append(job_id)
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
    *,
    preserve_existing: bool = False,
    preexisting_ids: set[int] | None = None,
    link_validator: DailyLinkValidator | None = None,
) -> SearchSummary:
    """Fetch, normalize, score, dedupe, and persist listings from one provider."""
    threshold = int(preferences["minimum_score"] if minimum_score is None else minimum_score)
    listings = (raw for request in requests for raw in provider.search(request))
    return _discover_listings(
        listings, store, preferences, resume_text, threshold, require_content=True,
        preserve_existing=preserve_existing, preexisting_ids=preexisting_ids,
        link_validator=link_validator,
    )


def discover_remotive_full_feed(
    provider: RemotiveProvider,
    store: JobStore,
    preferences: dict,
    resume_text: str,
    limit: int = 100,
    *,
    preserve_existing: bool = False,
    preexisting_ids: set[int] | None = None,
    link_validator: DailyLinkValidator | None = None,
) -> SearchSummary:
    """Score the unique RSS pool, then persist its most relevant bounded subset."""
    if limit < 1:
        raise ValueError("Remotive limit must be at least 1")
    # Apply the title-family gate before normalization or Gecko scoring. The
    # import limit is a limit on relevant candidates, not unrelated feed rows.
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
    ranked = []
    for raw in pool:
        job = normalize(raw)
        result = score_job(job, preferences, resume_text)
        ranked.append((result.total, _remotive_relevance(raw), raw.date_posted, raw, job))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    selected = ranked[:limit]
    summary = _discover_listings(
        (item[3] for item in selected), store, preferences, resume_text, 0,
        require_content=False, preserve_existing=preserve_existing,
        preexisting_ids=preexisting_ids,
    )
    summary.filtered_before_scoring = max(provider.rss_count - len(pool), 0)
    summary.fetched = len(pool)
    summary.normalized = len(pool)
    summary.scored = len(pool)
    summary.unique_available = len(pool)
    summary.unique_imported = len(selected)
    summary.top_jobs = [
        {
            "title": item[4].title,
            "company": item[4].company,
            "match_score": item[0],
            "location": item[4].location,
            "url": item[4].url,
        }
        for item in selected[:25]
    ]
    for item in selected:
        includes_usa, worldwide = _eligibility_flags(item[4].location)
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
