"""Discovery orchestration, deliberately independent of resume generation."""

from __future__ import annotations

from dataclasses import dataclass

from deduplicate import find_duplicate
from enrichment import enrich_and_rescore
from normalize import normalize
from scoring import score_job
from sources.base import JobSource, SearchRequest
from storage import JobStore
from url_resolution import classify_url, resolve_and_store


@dataclass
class SearchSummary:
    fetched: int = 0
    strong: int = 0
    weak: int = 0
    duplicates: int = 0
    provisional: int = 0


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
    summary = SearchSummary()
    known = store.all()
    for request in requests:
        for raw in provider.search(request):
            if not raw.title or not raw.description:
                continue
            summary.fetched += 1
            job = normalize(raw)
            result = score_job(job, preferences, resume_text)
            job.match_score = result.total
            job.match_strengths = result.strengths
            job.match_weaknesses = result.weaknesses
            job.evidence_confidence = result.confidence
            job.provisional = result.provisional
            job.evidence_levels = result.evidence_levels
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
                continue
            retained = job.match_score >= threshold
            job_id = store.save(job, retained=retained)
            job.id = job_id
            known.append(job)
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
