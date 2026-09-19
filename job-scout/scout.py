#!/usr/bin/env python
"""Gecko Job Scout command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from enrichment import enrich_and_rescore
from handoff import archive_listing
from preferences import load_preferences
from resume_evidence import extract_resume_text
from review import build_review_queue, format_review_queue, queue_to_json
from scoring import score_job
from service import discover
from sources import AdzunaProvider, IndeedProvider, ProviderError, WebCareerProvider
from sources.base import SearchRequest
from storage import DEFAULT_DB, JobStore
from tracker_sync import sync_job_scout


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MASTER_RESUME = PROJECT_ROOT / "input" / "master-resume" / "dcall-resume-3-15-26.pdf"
DEFAULT_SOURCE = "adzuna"
DEFAULT_TRACKER = PROJECT_ROOT / "output" / "job-tracker.xlsx"


def load_local_environment(path: Path = PROJECT_ROOT / ".env.local") -> None:
    """Load simple KEY=VALUE entries without replacing shell-provided credentials."""
    if not path.is_file():
        return
    for number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"Invalid environment entry at {path.name}:{number}")
        name, value = line.split("=", 1)
        name = name.strip()
        if not name or not name.replace("_", "").isalnum() or name[0].isdigit():
            raise ValueError(f"Invalid environment variable name at {path.name}:{number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(name, value)


def providers():
    return {provider.name: provider for provider in (AdzunaProvider(), IndeedProvider(), WebCareerProvider())}


def get_job(store: JobStore, job_id: int):
    job = store.get(job_id)
    if not job:
        raise ValueError(f"Job {job_id} was not found")
    return job


def sync_tracker(store: JobStore, tracker_path: str | Path):
    summary = sync_job_scout(store.all(), tracker_path)
    print(json.dumps({
        "job_scout_worksheet": {
            "rows": summary.rows,
            "confirmed": summary.confirmed,
            "provisional": summary.provisional,
            "near_matches": summary.near_matches,
            "tracker_preserved": summary.tracker_preserved,
        }
    }, indent=2))
    return summary


def search(args, store, preferences):
    available = providers()
    selected = list(available) if args.source == "all" else [args.source]
    queries = args.query or preferences["target_roles"]
    locations = args.location or ["Utah", "Remote"]
    requests = [SearchRequest(query, location, args.page, args.results)
                for query in queries for location in locations]
    resume_text = extract_resume_text(MASTER_RESUME)
    aggregate = {
        "fetched": 0, "strong": 0, "provisional": 0, "weak": 0, "duplicates": 0,
        "skipped_sources": [], "source_errors": {},
    }
    successful_sources = 0
    for name in selected:
        provider = available[name]
        if not provider.configured():
            aggregate["skipped_sources"].append(name)
            continue
        try:
            summary = discover(provider, requests, store, preferences, resume_text, args.minimum_score)
        except ProviderError as error:
            aggregate["source_errors"][name] = str(error)
            continue
        successful_sources += 1
        for key in ("fetched", "strong", "provisional", "weak", "duplicates"):
            aggregate[key] += getattr(summary, key)
    print(json.dumps(aggregate, indent=2))
    if len(aggregate["skipped_sources"]) == len(selected):
        print("No selected source is configured. See job-scout/README.md.", file=sys.stderr)
        return 2
    if not successful_sources:
        print("All configured sources failed. Review source_errors above.", file=sys.stderr)
        return 1
    sync_tracker(store, args.tracker)
    return 0


def list_jobs(args, store, preferences):
    jobs = [job for job in store.all(retained_only=not args.all)
            if job.match_score >= args.minimum_score and (not args.status or job.status == args.status)]
    jobs.sort(key=lambda job: (-job.match_score, job.date_posted or "9999", job.company.lower()))
    if args.json:
        print(json.dumps([job.to_dict() for job in jobs], indent=2))
    elif not jobs:
        print("No matching saved jobs.")
    else:
        print(f"{'ID':>4}  {'Score':>5}  {'Confidence':>10}  {'Evidence':<12}  {'Status':<14}  Company - Title")
        for job in jobs:
            evidence = "provisional" if job.provisional else "confirmed"
            print(f"{job.id:>4}  {job.match_score:>3}/100  {job.evidence_confidence:>9}%  {evidence:<12}  {job.status:<14}  {job.company} - {job.title}")
    return 0


def show(args, store, _preferences):
    print(json.dumps(get_job(store, args.job_id).to_dict(), indent=2))
    return 0


def select(args, store, _preferences):
    job = get_job(store, args.job_id)
    path = archive_listing(job, PROJECT_ROOT)
    store.update_status(args.job_id, "selected")
    sync_tracker(store, args.tracker)
    print(f"Selected Job Scout #{args.job_id}. Archived listing: {path.relative_to(PROJECT_ROOT)}")
    print(f"Next: use Gecko for the job description at {path.relative_to(PROJECT_ROOT)}")
    print("No resume was generated and no application-tracker row was added.")
    return 0


def set_status(args, store, _preferences):
    store.update_status(args.job_id, args.status)
    sync_tracker(store, args.tracker)
    print(f"Job {args.job_id} status set to {args.status}")
    return 0


def rescore(args, store, preferences):
    """Recalculate saved listings without refetching or changing lifecycle status."""
    resume_text = extract_resume_text(MASTER_RESUME)
    threshold = int(preferences["minimum_score"] if args.minimum_score is None else args.minimum_score)
    changes = []
    for job in store.all():
        old_score = job.match_score
        scoring_job = replace(job, description=job.enriched_description) if job.enriched_description else job
        result = score_job(scoring_job, preferences, resume_text)
        job.match_score = result.total
        job.evidence_confidence = result.confidence
        job.provisional = result.provisional
        job.evidence_levels = result.evidence_levels
        job.match_strengths = result.strengths
        job.match_weaknesses = result.weaknesses
        store.update_scoring(job, retained=job.match_score >= threshold)
        changes.append({
            "id": job.id, "old_score": old_score, "new_score": job.match_score,
            "score_change": job.match_score - old_score,
            "evidence_confidence": job.evidence_confidence,
            "provisional": job.provisional,
        })
    changes.sort(key=lambda item: (-item["new_score"], item["id"]))
    print(json.dumps(changes, indent=2))
    sync_tracker(store, args.tracker)
    return 0


def review_jobs(args, store, _preferences):
    """Display a read-only, prioritized application review queue."""
    queue = build_review_queue(
        store.all(),
        minimum_score=args.minimum_score,
        limit=args.limit,
        confirmed_only=args.confirmed_only,
        include_closed=args.include_closed,
    )
    print(queue_to_json(queue) if args.json else format_review_queue(queue))
    return 0


def enrich_jobs(args, store, preferences):
    """Enrich one or all provisional 80+ Adzuna records and report before/after evidence."""
    if bool(args.job_id) == bool(args.provisional):
        raise ValueError("Specify either a job ID or --provisional")
    if args.provisional:
        targets = [job for job in store.all()
                   if job.source.lower() == "adzuna" and job.match_score >= 80 and job.provisional]
    else:
        job = get_job(store, args.job_id)
        if job.source.lower() != "adzuna" or job.match_score < 80 or not job.provisional:
            raise ValueError("Enrichment is limited to provisional Adzuna jobs scoring 80 or higher")
        targets = [job]
    resume_text = extract_resume_text(MASTER_RESUME)
    report = []
    for job in targets:
        job = enrich_and_rescore(job, store, preferences, resume_text)
        if job.match_score >= 80 and job.evidence_confidence >= 65:
            final_status = "confirmed strong match"
        elif job.match_score >= 80:
            final_status = "80+ provisional — full description recommended"
        else:
            final_status = "below threshold after enrichment"
        report.append({
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "original_score": job.original_match_score,
            "enriched_score": job.enriched_match_score or None,
            "original_confidence": job.original_evidence_confidence,
            "enriched_confidence": job.enriched_evidence_confidence or None,
            "enrichment_status": job.enrichment_status,
            "enrichment_source": job.enriched_source_url,
            "enrichment_error": job.enrichment_error,
            "final_status": final_status,
        })
    print(json.dumps(report, indent=2))
    sync_tracker(store, args.tracker)
    return 0


def daily(args, store, preferences):
    """Run the complete discovery-to-review workflow without creating resumes."""
    search_args = argparse.Namespace(
        source="adzuna", query=None, location=None, page=1, results=args.results,
        minimum_score=None, tracker=args.tracker,
    )
    result = search(search_args, store, preferences)
    if result:
        return result
    review_args = argparse.Namespace(
        minimum_score=args.minimum_score, limit=args.limit,
        confirmed_only=False, include_closed=False, json=False,
    )
    return review_jobs(review_args, store, preferences)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--tracker", default=str(DEFAULT_TRACKER), help="Tracker workbook path")
    parser.add_argument("--preferences", help="Alternate preferences JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    find = sub.add_parser("search", help="Search configured providers and save scored results")
    find.add_argument(
        "--source",
        choices=["all", "adzuna", "indeed", "web-careers"],
        default=DEFAULT_SOURCE,
        help=f"Provider to query (default: {DEFAULT_SOURCE}); web-careers is opt-in",
    )
    find.add_argument("--query", action="append", help="Repeat for multiple role queries; defaults to all target roles")
    find.add_argument("--location", action="append", help="Repeat to search multiple areas; defaults to Utah and Remote")
    find.add_argument("--page", type=int, default=1)
    find.add_argument("--results", type=int, default=20)
    find.add_argument("--minimum-score", type=int)
    find.set_defaults(function=search)
    listing = sub.add_parser("list", help="Show strong saved matches")
    listing.add_argument("--minimum-score", type=int, default=80)
    listing.add_argument("--status", choices=["new", "reviewing", "selected", "resume-created", "applied", "contacted", "interview", "rejected", "offer", "ignored"])
    listing.add_argument("--all", action="store_true", help="Include weak results remembered as seen")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(function=list_jobs)
    detail = sub.add_parser("show", help="Show a complete saved record")
    detail.add_argument("job_id", type=int)
    detail.set_defaults(function=show)
    choose = sub.add_parser("select", help="Archive one job for the existing Gecko workflow")
    choose.add_argument("job_id", type=int)
    choose.set_defaults(function=select)
    status = sub.add_parser("status", help="Change a saved job's lifecycle status")
    status.add_argument("job_id", type=int)
    status.add_argument("status", choices=["new", "reviewing", "selected", "resume-created", "applied", "contacted", "interview", "rejected", "offer", "ignored"])
    status.set_defaults(function=set_status)
    rescore_parser = sub.add_parser("rescore", help="Recalculate all saved jobs with the current scoring model")
    rescore_parser.add_argument("--minimum-score", type=int)
    rescore_parser.set_defaults(function=rescore)
    enrich_parser = sub.add_parser("enrich", help="Enrich provisional 80+ Adzuna matches")
    enrich_parser.add_argument("job_id", nargs="?", type=int)
    enrich_parser.add_argument("--provisional", action="store_true", help="Enrich all provisional 80+ matches")
    enrich_parser.set_defaults(function=enrich_jobs)
    review_parser = sub.add_parser("review", help="Show the prioritized, read-only Job Scout review queue")
    review_parser.add_argument("--confirmed-only", action="store_true")
    review_parser.add_argument("--minimum-score", type=int, default=70)
    review_parser.add_argument("--limit", type=int, default=20)
    review_parser.add_argument("--json", action="store_true")
    review_parser.add_argument(
        "--include-closed", action="store_true",
        help="Include applied, rejected, and ignored jobs",
    )
    review_parser.set_defaults(function=review_jobs)
    daily_parser = sub.add_parser("daily", help="Search, deduplicate, score, enrich, sync, and review")
    daily_parser.add_argument("--results", type=int, default=20)
    daily_parser.add_argument("--minimum-score", type=int, default=70)
    daily_parser.add_argument("--limit", type=int, default=20)
    daily_parser.set_defaults(function=daily)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        load_local_environment()
        preferences = load_preferences(args.preferences)
        with JobStore(args.db) as store:
            return args.function(args, store, preferences)
    except (OSError, RuntimeError, ValueError, ProviderError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
