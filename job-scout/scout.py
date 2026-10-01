#!/usr/bin/env python
"""Gecko Job Scout command line interface."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

from enrichment import enrich_and_store
from ai_evaluation import JobEvaluator
from deduplicate import find_duplicate
from google_tracker import GoogleTracker, marked
from handoff import archive_listing
from link_validation import DailyLinkValidator
from manual_indeed import ManualIndeedSummary, process_manual_indeed_rows
from models import RawListing
from normalize import normalize
from normalize import canonicalize_url
from preferences import load_preferences
from review import build_review_queue, format_review_queue, queue_to_json
from role_filter import is_relevant_role
from service import discover, discover_feed, discover_listings, discover_remotive_full_feed
from sources import (
    AdzunaProvider, AshbyProvider, GreenhouseProvider, IndeedProvider,
    JobicyProvider, LeverProvider, ProviderError, RemoteOkProvider, RemotiveProvider,
    SearchDiscoveryProvider, TheMuseProvider, UnavailableProvider, UsaJobsProvider,
    WeWorkRemotelyProvider, WebCareerProvider, WorkableProvider,
)
from sources.base import SearchRequest
from sources.config import load_source_config
from storage import DEFAULT_DB, JobStore
from url_resolution import resolve_and_store, url_status_label


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MASTER_RESUME = PROJECT_ROOT / "input" / "master-resume" / "Dave-Call-Resume.txt"
DEFAULT_SOURCE = "adzuna"
CORE_PROVIDERS = (
    "adzuna", "remotive", "web-careers", "jobicy", "remoteok", "usajobs",
    "greenhouse", "lever", "ashby", "workable", "weworkremotely",
    "workingnomads", "themuse", "indeed", "linkedin", "glassdoor",
    "ziprecruiter",
)


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


def providers(config_path=None):
    config = load_source_config(config_path)
    settings = config["providers"]
    indeed_api = IndeedProvider()
    result = {
        "adzuna": AdzunaProvider(),
        "remotive": RemotiveProvider(),
        "web-careers": WebCareerProvider(),
        "jobicy": JobicyProvider(),
        "remoteok": RemoteOkProvider(),
        "usajobs": UsaJobsProvider(),
        "greenhouse": GreenhouseProvider(settings["greenhouse"].get("companies")),
        "lever": LeverProvider(settings["lever"].get("companies")),
        "ashby": AshbyProvider(settings["ashby"].get("companies")),
        "workable": WorkableProvider(settings["workable"].get("companies")),
        "weworkremotely": WeWorkRemotelyProvider(),
        "workingnomads": UnavailableProvider(
            "workingnomads",
            "No supported public API or feed is currently documented; scraping is disabled",
        ),
        "themuse": TheMuseProvider(),
        "indeed": (indeed_api if indeed_api.configured() else SearchDiscoveryProvider(
            "indeed", "site:indeed.com/viewjob",
        )),
        "linkedin": SearchDiscoveryProvider("linkedin", "site:linkedin.com/jobs/view"),
        "glassdoor": SearchDiscoveryProvider("glassdoor", "site:glassdoor.com/job-listing"),
        "ziprecruiter": SearchDiscoveryProvider("ziprecruiter", "site:ziprecruiter.com/jobs"),
    }
    for name, provider in list(result.items()):
        if not settings.get(name, {}).get("enabled", True):
            result[name] = UnavailableProvider(name, "Disabled in job-sources.json", status="disabled")
    return result


def get_job(store: JobStore, job_id: int):
    job = store.get(job_id)
    if not job:
        raise ValueError(f"Job {job_id} was not found")
    return job


def sync_tracker(
    store: JobStore,
    tracker_path=None,
    *,
    force_google: bool = False,
    jobs=None,
    append_only: bool = False,
    remove_scout_ids: set[int] | None = None,
    highlight_found_on: str | None = None,
):
    tracker = GoogleTracker()
    if remove_scout_ids:
        tracker.remove_dead_scout(remove_scout_ids)
    summary = tracker.upsert_scout(store.all() if jobs is None else jobs, append_only=append_only)
    if highlight_found_on:
        summary["highlighted_scout_ids"] = tracker.highlight_scout_found_on(highlight_found_on)
    result = {
        "job_scout_worksheet": {
            "rows": summary["rows"], "added": summary["added"], "updated": summary["updated"],
        }
    }
    if highlight_found_on:
        result["job_scout_worksheet"]["highlighted_scout_ids"] = summary["highlighted_scout_ids"]
    result["google_sheets"] = {"spreadsheet_id": tracker.config.spreadsheet_id}
    print(json.dumps(result, indent=2))
    return summary


def sync_sheets(args, store, _preferences):
    """Synchronize Job Scout datastore values to the canonical Google Sheet."""
    sync_tracker(store, force_google=True)
    return 0


def protected_job_ids(jobs, tracker_path=None) -> set[int]:
    """Preserve application history even if a Scout lifecycle flag is stale."""
    protected = {job.id for job in jobs if job.id is not None and job.status not in {"new", "reviewing"}}
    tracker = GoogleTracker()
    for _, row in tracker.scout().rows:
        try:
            scout_id = int(row.get("Scout ID"))
        except (TypeError, ValueError):
            continue
        if any(marked(row.get(field)) for field in ("Apply?", "Applied", "Contacted", "Resume Created", "Response")) or str(row.get("Gecko Status") or "").lower() not in {"", "new", "reviewing"}:
            protected.add(scout_id)
    try:
        application_rows = tracker.application().rows
    except RuntimeError as error:
        if "not found" not in str(error).casefold():
            raise
        application_rows = []
    for _, row in application_rows:
        link = canonicalize_url(str(row.get("Job Link") or ""))
        company = str(row.get("Company") or "").casefold().strip()
        title = str(row.get("Job Title") or "").casefold().strip()
        number = str(row.get("Job Number") or "").casefold().strip()
        for job in jobs:
            if job.id is None:
                continue
            urls = {canonicalize_url(url) for url in (job.url, job.canonical_url, job.authoritative_url) if url}
            if (link and link in urls) or (number and number == job.source_job_id.casefold()) or (company and title and company == job.company.casefold().strip() and title == job.title.casefold().strip()):
                protected.add(job.id)
    return protected


def scout_row_ids(tracker_path=None) -> set[int]:
    return {int(row["Scout ID"]) for _, row in GoogleTracker().scout().rows
            if str(row.get("Scout ID") or "").isdigit()}


def sheet_only_active_jobs(tracker_path, known_ids: set[int]):
    """Include active worksheet rows that have no matching local SQLite record."""
    result = []
    for _, row in GoogleTracker().scout().rows:
            def value(header):
                return row.get(header)
            try:
                scout_id = int(value("Scout ID"))
            except (TypeError, ValueError):
                continue
            if scout_id in known_ids:
                continue
            status = str(value("Gecko Status") or "new").strip().lower().replace(" ", "-")
            if status in {"ignored", "rejected"}:
                continue
            url = str(value("Job URL") or "")
            item = normalize(RawListing(source="worksheet", source_job_id=str(scout_id), url=url,
                                        title=str(value("Job Title") or ""),
                                        company=str(value("Company") or "")))
            item.id = scout_id
            item.status = status
            result.append(item)
    return result


def search(args, store, preferences):
    daily_mode = bool(getattr(args, "daily_mode", False))
    link_validator = getattr(args, "link_validator", None) if daily_mode else None
    preexisting_ids = {job.id for job in store.all()}
    source_config = load_source_config(getattr(args, "sources_config", None))
    available = providers(getattr(args, "sources_config", None))
    if args.source == "all":
        selected = list(available)
    elif args.source == "core":
        selected = list(CORE_PROVIDERS)
    else:
        selected = [args.source]
    queries = args.query or preferences["target_roles"]
    locations = args.location or ["Utah", "Remote"]
    # Remotive is globally remote and uses category RSS, never Utah/title discovery.
    requests = (
        [SearchRequest(query, location, args.page, args.results)
         for query in queries for location in locations]
        if any(name != "remotive" for name in selected) else []
    )
    aggregate = {
        "raw_retrieved": 0, "rss_retrieved": 0, "rss_unique": 0,
        "rss_duplicates_removed": 0, "successful_feeds": 0, "failed_feeds": 0,
        "api_retrieved": 0,
        "fetched": 0, "normalized": 0,
        "added": 0, "updated": 0,
        "duplicates": 0, "cross_provider_duplicates": 0,
        "filtered_by_role": 0, "deterministic_rejects": 0, "jooble_excluded": 0,
        "source_results_limited": 0,
        "newly_discovered": 0, "already_existed": 0,
        "new_job_ids": [], "existing_job_ids": [], "changed_job_ids": [],
        "unique_remotive_jobs_available": 0, "unique_jobs_imported": 0,
        "eligibility_includes_usa": 0, "eligibility_worldwide": 0,
        "example_jobs": [],
        "source_counts": {name: 0 for name in selected}, "source_backends": {},
        "source_diagnostics": {},
        "google_cse": {},
        "skipped_sources": [], "source_errors": {}, "source_health": {},
    }
    successful_sources = 0
    configured = {
        name: available[name] for name in selected
        if name != "remotive" and available[name].configured()
        and (callable(getattr(type(available[name]), "full_feed", None))
             or callable(getattr(type(available[name]), "search", None)))
    }

    def acquire(name_provider):
        name, provider = name_provider
        if callable(getattr(type(provider), "full_feed", None)):
            listings = list(provider.full_feed())
            require_content = False
        else:
            provider_queries = getattr(provider, "broad_queries", queries)
            provider_requests = [
                SearchRequest(query, location, args.page, args.results)
                for query in provider_queries for location in locations
            ]
            listings = [raw for request in provider_requests for raw in provider.search(request)]
            require_content = True
        listings.sort(
            key=lambda raw: (raw.date_posted or "", raw.title.casefold()), reverse=True
        )
        provider_settings = source_config["providers"].get(name, {})
        limit = int(provider_settings.get(
            "max_results_per_run", source_config.get("max_results_per_source", 50)
        ))
        if limit < 1:
            raise ValueError(f"Source result limit for {name} must be at least 1")
        return listings[:limit], require_content, max(len(listings) - limit, 0)

    workers = min(max(int(source_config.get("max_workers", 6)), 1), 16, max(len(configured), 1))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job-source") as executor:
        futures = {name: executor.submit(acquire, (name, provider))
                   for name, provider in configured.items()}
        for name in selected:
            provider = available[name]
            if name == "web-careers" and callable(getattr(provider, "diagnostics", None)):
                web_diagnostics = provider.diagnostics()
                aggregate["source_diagnostics"][name] = web_diagnostics
                aggregate["google_cse"] = web_diagnostics["google_cse"]
                if provider.backend:
                    aggregate["source_backends"][name] = provider.backend
            if not provider.configured():
                aggregate["skipped_sources"].append(name)
                status = getattr(provider, "status", "")
                if not status:
                    status = ("disabled" if name in {"greenhouse", "lever", "ashby", "workable"}
                              else "missing credentials")
                aggregate["source_health"][name] = {
                    "status": status,
                    "found": 0,
                    "detail": getattr(provider, "reason", "") or
                              ("No employers configured" if status == "disabled" else "Not configured"),
                }
                continue
            try:
                if name == "remotive":
                    source_limit = int(source_config["providers"].get(name, {}).get(
                        "max_results_per_run", source_config.get("max_results_per_source", 50)
                    ))
                    summary = discover_remotive_full_feed(
                        provider, store, limit=min(getattr(args, "limit", 100), source_limit),
                        preserve_existing=daily_mode, preexisting_ids=preexisting_ids,
                        link_validator=link_validator, preferences=preferences,
                    )
                elif name in futures:
                    listings, require_content, limited = futures[name].result()
                    aggregate["source_results_limited"] += limited
                    summary = discover_listings(
                        listings, store, require_content=require_content,
                        preserve_existing=daily_mode, preexisting_ids=preexisting_ids,
                        link_validator=link_validator, preferences=preferences,
                    )
                else:
                    summary = discover(
                        provider, requests, store,
                        preserve_existing=daily_mode, preexisting_ids=preexisting_ids,
                        link_validator=link_validator, preferences=preferences,
                    )
            except (ProviderError, OSError, ValueError) as error:
                aggregate["source_errors"][name] = str(error)
                error_status = "rate limited" if "429" in str(error) else "api error"
                aggregate["source_health"][name] = {
                    "status": error_status, "found": 0, "detail": str(error),
                }
                print(f"Warning: {name} provider failed: {error}", file=sys.stderr)
                continue
            successful_sources += 1
            aggregate["source_counts"][name] = (
                (summary.unique_imported or summary.fetched)
                if name == "remotive" else summary.fetched
            )
            discovery_mode = getattr(provider, "discovery_mode", "")
            if not isinstance(discovery_mode, str):
                discovery_mode = ""
            aggregate["source_health"][name] = {
                "status": (discovery_mode or
                           ("success" if aggregate["source_counts"][name] else "no results")),
                "found": aggregate["source_counts"][name],
                "detail": "",
            }
            if summary.source_backend:
                aggregate["source_backends"][name] = summary.source_backend
            if name == "web-careers" and callable(getattr(provider, "diagnostics", None)):
                web_diagnostics = provider.diagnostics(
                    jobs_added=summary.added,
                    backend_qualifying=summary.backend_qualifying,
                    backend_added=summary.backend_added,
                )
                aggregate["source_diagnostics"][name] = web_diagnostics
                aggregate["google_cse"] = web_diagnostics["google_cse"]
            if name == "remotive":
                aggregate["source_diagnostics"][name] = {
                    "api_endpoint": getattr(provider, "api_endpoint", ""),
                    "rss_error": getattr(provider, "rss_error", ""),
                    "discovery_location": "Remote",
                    "feeds_attempted": summary.successful_feeds + summary.failed_feeds,
                    "category_feeds": summary.feed_results,
                }
                aggregate["unique_remotive_jobs_available"] = summary.unique_available
                aggregate["unique_jobs_imported"] = summary.unique_imported
                aggregate["eligibility_includes_usa"] = summary.eligibility_includes_usa
                aggregate["eligibility_worldwide"] = summary.eligibility_worldwide
                aggregate["example_jobs"] = summary.example_jobs
            for key in (
                "raw_retrieved", "rss_retrieved", "rss_unique",
                "rss_duplicates_removed", "successful_feeds", "failed_feeds",
                "api_retrieved", "fetched",
                "normalized", "added", "updated", "duplicates", "cross_provider_duplicates",
                "filtered_by_role", "deterministic_rejects", "jooble_excluded",
            ):
                aggregate[key] += getattr(summary, key)
            for job_id in summary.new_job_ids:
                if job_id not in aggregate["new_job_ids"]:
                    aggregate["new_job_ids"].append(job_id)
            for job_id in summary.existing_job_ids:
                if job_id not in aggregate["existing_job_ids"]:
                    aggregate["existing_job_ids"].append(job_id)
            for job_id in summary.changed_job_ids:
                if job_id not in aggregate["changed_job_ids"]:
                    aggregate["changed_job_ids"].append(job_id)
    aggregate["newly_discovered"] = len(aggregate["new_job_ids"])
    aggregate["already_existed"] = len(aggregate["existing_job_ids"])
    aggregate["sources_searched"] = successful_sources + len(aggregate["source_errors"])
    args.run_result = aggregate
    print(json.dumps(aggregate, indent=2))
    print("\nJob Scout source summary", file=sys.stderr)
    for name in selected:
        health = aggregate["source_health"].get(name, {"status": "unknown", "found": 0})
        detail = f" - {health.get('detail')}" if health.get("detail") else ""
        print(f"{name}: {health.get('status')} ({health.get('found', 0)} found){detail}",
              file=sys.stderr)
    if "web-careers" in selected:
        backend = aggregate["source_backends"].get("web-careers") or "disabled"
        print(f"brave: {backend} backend for web-careers", file=sys.stderr)
    print(f"Duplicates removed: {aggregate['duplicates']}", file=sys.stderr)
    print(f"Previously seen: {aggregate['already_existed']}", file=sys.stderr)
    print(f"Rejected by Gecko filters: {aggregate['filtered_by_role']}", file=sys.stderr)
    print(f"New qualified jobs written: {aggregate['newly_discovered']}", file=sys.stderr)
    if len(aggregate["skipped_sources"]) == len(selected):
        print("No selected source is configured. See job-scout/README.md.", file=sys.stderr)
        return 2
    if not successful_sources:
        print("All configured sources failed. Review source_errors above.", file=sys.stderr)
        return 1
    if daily_mode:
        if not getattr(args, "dry_run", False):
            new_jobs = [store.get(job_id) for job_id in aggregate["new_job_ids"]]
            args.tracker_summary = sync_tracker(
                store, jobs=[job for job in new_jobs if job], append_only=True,
                highlight_found_on=date.today().isoformat(),
            )
    else:
        sync_tracker(store)
    return 0


def diagnose_remotive(args, store, preferences):
    """Exercise only Remotive and report each stage without changing saved jobs."""
    provider = RemotiveProvider()
    queries = args.query or [
        "digital marketing", "paid search", "PPC", "marketing analytics",
    ]
    unique: dict[str, RawListing] = {}
    try:
        for query in queries:
            request = SearchRequest(query=query, location="Remote", results_per_page=args.results)
            for raw in provider.search(request):
                key = raw.source_job_id or raw.url
                unique.setdefault(key, raw)
    except ProviderError as error:
        print(f"Error: remotive provider failed: {error}", file=sys.stderr)
        return 1

    candidates = []
    for raw in unique.values():
        if not raw.source_job_id or not raw.url or not raw.title or not raw.description:
            continue
        if is_relevant_role(raw.title):
            candidates.append(normalize(raw))

    other_source_jobs = [job for job in store.all() if job.source.casefold() != "remotive"]
    survivors = [job for job in candidates if find_duplicate(job, other_source_jobs) is None]
    examples = sorted(candidates, key=lambda job: (job.date_posted, job.title.casefold()), reverse=True)[:args.examples]
    report = {
        "provider": "remotive",
        "endpoint": getattr(provider, "api_endpoint", provider.endpoint),
        "queries": queries,
        "raw_retrieved": provider.raw_count,
        "query_matches": len(unique),
        "matched_role_filter": len(candidates),
        "survived_deduplication": len(survivors),
        "source_counts": {"remotive": len(unique)},
        "examples": [
            {
                "title": job.title,
                "company": job.company,
                "url": job.url,
            }
            for job in examples
        ],
    }
    print(json.dumps(report, indent=2))
    return 0


def verify_sources(args, _store, _preferences):
    """Read-only live health check for every configured provider."""
    available = providers(getattr(args, "sources_config", None))

    def check(item):
        name, provider = item
        if not provider.configured():
            status = getattr(provider, "status", "") or (
                "disabled" if name in {"greenhouse", "lever", "ashby", "workable"}
                else "missing credentials"
            )
            return name, {"status": status, "count": 0,
                          "detail": getattr(provider, "reason", "")}
        try:
            if name == "remotive":
                jobs = list(provider.full_feed(unique_limit=args.results))
            elif hasattr(provider, "full_feed"):
                jobs = list(provider.full_feed())[:args.results]
            else:
                jobs = list(provider.search(SearchRequest(
                    "digital marketing", "Remote", 1, args.results,
                )))[:args.results]
            return name, {
                "status": getattr(provider, "discovery_mode", "") or
                          ("success" if jobs else "no results"),
                "count": len(jobs), "detail": "",
            }
        except (ProviderError, OSError, ValueError) as error:
            return name, {"status": "rate limited" if "429" in str(error) else "api error",
                          "count": 0, "detail": str(error)}

    workers = min(6, len(available))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="verify-source") as executor:
        report = dict(executor.map(check, available.items()))
    print(json.dumps(report, indent=2))
    failures = 0
    print("\nJob Scout provider verification (read-only)")
    for name, result in report.items():
        detail = f" - {result['detail']}" if result["detail"] else ""
        print(f"{name}: {result['status']} ({result['count']} sampled){detail}")
        failures += int(result["status"] in {"api error", "rate limited"})
    return 1 if failures else 0


def diagnose_remotive_feeds(args, _store, preferences):
    """Dry-run the bounded RSS import and report acquisition diagnostics."""
    provider = RemotiveProvider()
    with tempfile.TemporaryDirectory() as directory:
        with JobStore(Path(directory) / "remotive-diagnostic.sqlite3") as diagnostic_store:
            summary = discover_remotive_full_feed(
                provider, diagnostic_store, limit=getattr(args, "limit", 100),
            )
    report = {
        "provider": "remotive",
        "discovery_location": "Remote",
        "feeds_attempted": summary.successful_feeds + summary.failed_feeds,
        "category_feeds": provider.feed_results,
        "successful_category_feeds": provider.successful_feed_count,
        "failed_category_feeds": provider.failed_feed_count,
        "raw_rss_records": provider.rss_raw_count,
        "unique_rss_jobs": summary.unique_available,
        "rss_duplicates_removed": provider.rss_duplicate_count,
        "unique_jobs_imported": summary.unique_imported,
    }
    print(json.dumps(report, indent=2))
    return 0 if summary.unique_available else 1


def list_jobs(args, store, preferences):
    jobs = [job for job in store.all() if not args.status or job.status == args.status]
    jobs.sort(key=lambda job: (job.date_posted or "", job.company.lower()), reverse=True)
    if args.json:
        print(json.dumps([job.to_dict() for job in jobs], indent=2))
    elif not jobs:
        print("No matching saved jobs.")
    else:
        print(f"{'ID':>4}  {'Status':<14}  Company - Title")
        for job in jobs:
            print(f"{job.id:>4}  {job.status:<14}  {job.company} - {job.title}")
    return 0


def show(args, store, _preferences):
    record = get_job(store, args.job_id).to_dict()
    evaluation = store.get_job_evaluation(args.job_id)
    if evaluation:
        record["ai_evaluation"] = evaluation
    print(json.dumps(record, indent=2))
    return 0


def select(args, store, _preferences):
    job = get_job(store, args.job_id)
    path = archive_listing(job, PROJECT_ROOT)
    store.update_status(args.job_id, "selected")
    sync_tracker(store)
    print(f"Selected Job Scout #{args.job_id}. Archived listing: {path.relative_to(PROJECT_ROOT)}")
    print(f"Next: use Gecko for the job description at {path.relative_to(PROJECT_ROOT)}")
    print("No resume was generated and no application-tracker row was added.")
    return 0


def set_status(args, store, _preferences):
    store.update_status(args.job_id, args.status)
    sync_tracker(store)
    print(f"Job {args.job_id} status set to {args.status}")
    return 0


def review_jobs(args, store, _preferences):
    """Display a read-only, prioritized application review queue."""
    queue = build_review_queue(
        store.all(),
        limit=args.limit,
        include_closed=args.include_closed,
    )
    print(queue_to_json(queue) if args.json else format_review_queue(queue))
    return 0


def enrich_jobs(args, store, preferences):
    """Enrich one job or every Adzuna job."""
    if bool(args.job_id) == bool(args.all):
        raise ValueError("Specify either a job ID or --all")
    targets = ([job for job in store.all() if job.source.lower() == "adzuna"]
               if args.all else [get_job(store, args.job_id)])
    report = []
    for job in targets:
        job = enrich_and_store(job, store)
        report.append({
            "id": job.id, "title": job.title, "company": job.company,
            "enrichment_status": job.enrichment_status,
            "enrichment_source": job.enriched_source_url,
            "enrichment_error": job.enrichment_error,
        })
    print(json.dumps(report, indent=2))
    sync_tracker(store)
    return 0


def resolve_urls(args, store, _preferences):
    """Resolve one job or a bounded set of Jooble-sourced jobs."""
    if bool(args.job_id) == bool(args.jooble):
        raise ValueError("Specify either a job ID or --jooble")
    if args.jooble:
        targets = [
            job for job in store.all()
            if any(link.get("source", "").casefold() == "jooble" for link in job.source_links)
            and (args.force or job.url_verification_status == "not_attempted")
        ][:args.limit]
    else:
        targets = [get_job(store, args.job_id)]
    report = []
    for job in targets:
        resolved = resolve_and_store(job, store)
        report.append({
            "id": resolved.id,
            "company": resolved.company,
            "title": resolved.title,
            "url_status": url_status_label(resolved),
            "authoritative_url": resolved.authoritative_url,
            "confidence": resolved.authoritative_url_confidence,
            "redirect_url": resolved.url_redirect_url,
            "error": resolved.url_resolution_error,
        })
    print(json.dumps(report, indent=2))
    sync_tracker(store)
    return 0


def _daily_resume_runner(new_job_ids, store, *, dry_run=False):
    """Run the canonical Gecko queue with daily all-source geographic approval."""
    new_job_ids = tuple(new_job_ids)
    scripts = PROJECT_ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import generate_apply_queue

    generate_apply_queue._append_run_log(
        f"DAILY RESUME START dry_run={dry_run} new_job_ids={','.join(map(str, new_job_ids)) or 'none'}"
    )
    result = generate_apply_queue.run_queue(
        GoogleTracker(), store.path.resolve(), dry_run=dry_run,
        auto_approve_geographic=True,
        print_summary=False,
        logger=generate_apply_queue._append_run_log,
    )
    generate_apply_queue._append_run_log(f"DAILY RESUME END exit_code={result.exit_code}")
    return result


def _daily_gmail_response_runner():
    """Run Gmail tracking without allowing it to fail the daily workflow."""
    try:
        from gmail_response_tracker import append_log, run_live_check

        result = run_live_check()
        rows = ",".join(map(str, result.updated_rows)) or "none"
        append_log(
            f"GMAIL RESPONSE CHECK checked={result.emails_checked} "
            f"matched={result.emails_matched} updated={result.tracker_rows_updated} "
            f"rows={rows} skipped_processed={result.skipped_processed}"
        )
        return result, ""
    except Exception as error:
        message = str(error)
        try:
            from gmail_response_tracker import append_log
            append_log(f"GMAIL RESPONSE CHECK FAILED error={message}")
        except Exception:
            pass
        print(f"Gmail response tracking warning: {message}", file=sys.stderr)
        return None, message


def _print_daily_summary(run_result, queue_result, tracker_summary, *, dry_run=False,
                         gmail_result=None, gmail_error="", manual_indeed=None):
    manual_indeed = manual_indeed or ManualIndeedSummary()
    print("\nDaily Job Scout complete" + (" (dry run)" if dry_run else ""))
    print(f"Sources searched: {run_result.get('sources_searched', 0)}")
    print(f"Jobs discovered: {run_result.get('fetched', 0)}")
    print(f"Jooble jobs excluded: {run_result.get('jooble_excluded', 0)}")
    print(f"Duplicates skipped: {run_result.get('duplicates', 0)}")
    print(f"New jobs added: {tracker_summary.get('added', 0)}")
    print(f"Manual Indeed rows processed: {manual_indeed.processed}")
    print(f"Manual Indeed duplicates flagged: {manual_indeed.duplicates}")
    print(f"Manual Indeed retrieval failures: {manual_indeed.failures}")
    print(f"Job Scout declined rows removed: {manual_indeed.removed}")
    print(f"Jobs marked Apply = Yes: {len(queue_result.snapshot.pending) + len(queue_result.snapshot.already_created)}")
    print(f"Resumes already existing: {len(queue_result.snapshot.already_created) + queue_result.recovered}")
    print(f"New Gecko resumes created: {queue_result.created}")
    print(f"Resume failures: {len(queue_result.failures)}")
    print(f"AI triage calls: {run_result.get('AI_triage_calls', 0)}")
    print(f"Full score calls: {run_result.get('full_score_calls', 0)}")
    print(f"Unchanged descriptions served from cache: {run_result.get('cached_unchanged', 0)}")
    print(f"Elapsed time: {run_result.get('elapsed_time', 0):.2f}s")
    print("Daily run metrics:")
    for name in (
        "fetched", "deterministic_rejects", "duplicates", "cached_unchanged",
        "AI_triage_calls", "full_score_calls", "Apply_Yes", "resumes_generated",
        "failures", "elapsed_time",
    ):
        value = run_result.get(name, 0)
        if name == "elapsed_time":
            value = f"{float(value):.2f}s"
        print(f"  {name}: {value}")
    if dry_run:
        print("Gmail response tracking: skipped in dry run")
    elif gmail_result is not None:
        print(f"Gmail emails checked: {gmail_result.emails_checked}")
        print(f"Gmail responses matched: {gmail_result.emails_matched}")
        print(f"Response rows updated: {gmail_result.tracker_rows_updated}")
        print("Updated Response rows: " + (
            ", ".join(map(str, gmail_result.updated_rows)) if gmail_result.updated_rows else "None"
        ))
    else:
        print(f"Gmail response tracking: failed without stopping Daily Job Scout ({gmail_error})")
    print("\nCreated resumes:")
    if queue_result.successes:
        for index, (item, artifacts) in enumerate(queue_result.successes, 1):
            print(f"{index}. {item.company} | {item.title} | {artifacts.resume}")
    else:
        print("None")
    print("\nFailures:")
    if queue_result.failures:
        for index, failure in enumerate(queue_result.failures, 1):
            print(f"{index}. {failure.item.company} | {failure.item.title} | {failure.reason}")
    else:
        print("None")


def _empty_queue_result():
    from types import SimpleNamespace
    return SimpleNamespace(
        snapshot=SimpleNamespace(pending=[], already_created=[]), recovered=0,
        created=0, failures=[], successes=[], exit_code=0,
    )


def daily(args, store, preferences):
    """Discover, sync, geographically approve, and generate Gecko resumes."""
    started = time.monotonic()
    if args.dry_run and not getattr(args, "_temporary_store", False):
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "daily-dry-run.sqlite3") as temporary_store:
                store.connection.backup(temporary_store.connection)
                temporary_store.connection.commit()
                dry_args = argparse.Namespace(**vars(args))
                dry_args._temporary_store = True
                return daily(dry_args, temporary_store, preferences)
    validator = DailyLinkValidator()
    if isinstance(store, JobStore):
        existing = [job for job in store.all() if job.status not in {"ignored", "rejected"}]
        if args.dry_run:
            protected = {
                job.id for job in existing
                if job.id is not None and job.status not in {"new", "reviewing"}
            }
        else:
            existing.extend(sheet_only_active_jobs(
                None, {job.id for job in existing if job.id is not None}
            ))
            protected = protected_job_ids(existing)
            existing_sheet_ids = scout_row_ids()
            if existing_sheet_ids:
                store.observe_scout_id(max(existing_sheet_ids))
        checked = validator.check_existing(existing)
        dead = [(job, result) for job, result in checked if result.status == "dead"]
        removable = [(job, result) for job, result in dead if job.id not in protected]
        validator.protected_dead += len(dead) - len(removable)
        if removable and not args.dry_run:
            ids = {job.id for job, _ in removable}
            sync_tracker(store, jobs=[], append_only=True, remove_scout_ids=ids)
            for job, result in removable:
                store.delete_dead_unprotected(job.id)
                validator.record_removed(job, result)
    search_args = argparse.Namespace(
        source="core", query=None, location=None, page=1, results=args.results,
        limit=args.limit, daily_mode=True,
        link_validator=validator, dry_run=args.dry_run,
        sources_config=getattr(args, "sources_config", None),
    )
    result = search(search_args, store, preferences)
    manual_indeed = ManualIndeedSummary()
    if not args.dry_run:
        manual_indeed = process_manual_indeed_rows(GoogleTracker(), store)
        print("Manual Indeed intake:")
        print(json.dumps(manual_indeed.to_dict(), indent=2))
        run_result = getattr(search_args, "run_result", {})
        for job_id in manual_indeed.new_job_ids:
            if job_id not in run_result.setdefault("new_job_ids", []):
                run_result["new_job_ids"].append(job_id)
        run_result["newly_discovered"] = len(run_result.get("new_job_ids", []))
        tracker_summary = getattr(search_args, "tracker_summary", {"added": 0})
        tracker_summary["added"] = tracker_summary.get("added", 0) + manual_indeed.processed
        search_args.tracker_summary = tracker_summary
    print("Link validation:")
    for field in ("checked", "valid", "removed_dead", "temporary_failure", "protected_dead"):
        print(f"  {field}: {validator.report()[field]}")
    for removed in validator.removed:
        print(f"  removed: {removed['company']} | {removed['job_title']} | {removed['url']} | "
              f"{removed['reason_removed']} | HTTP/status {removed['http_status'] or 'n/a'}")
    run_result = getattr(search_args, "run_result", {})
    evaluation_ids = list(dict.fromkeys([
        *run_result.get("new_job_ids", []), *run_result.get("changed_job_ids", []),
    ]))
    new_jobs = [store.get(job_id) for job_id in run_result.get("new_job_ids", [])]
    evaluation_jobs = [store.get(job_id) for job_id in evaluation_ids]
    evaluator = JobEvaluator(store, preferences)
    evaluations, evaluation_metrics = evaluator.evaluate(
        [job for job in evaluation_jobs if job], dry_run=args.dry_run
    )
    for job_id, evaluation in evaluations.items():
        print(
            f"AI EVALUATION: Scout ID {job_id} | {evaluation.relevance} | "
            f"Match Score {evaluation.match_score if evaluation.match_score is not None else 'n/a'} | "
            f"Apply {evaluation.apply_decision} | "
            f"{evaluation.score_reason or evaluation.triage_reason}"
        )
    run_result.update({
        "cached_unchanged": evaluation_metrics.cached_unchanged,
        "AI_triage_calls": evaluation_metrics.AI_triage_calls,
        "full_score_calls": evaluation_metrics.full_score_calls,
        "Apply_Yes": evaluation_metrics.Apply_Yes,
        "ai_evaluation_disabled": evaluation_metrics.disabled,
    })
    run_result["failures"] = len(run_result.get("source_errors", {})) + evaluation_metrics.failures
    if result and not manual_indeed.new_job_ids:
        run_result["elapsed_time"] = time.monotonic() - started
        _print_daily_summary(run_result, _empty_queue_result(), {"added": 0},
                             dry_run=args.dry_run, manual_indeed=manual_indeed)
        return result
    queue = build_review_queue(
        [job for job in new_jobs if job], limit=args.limit, include_closed=False,
    )
    qualifying = sum(len(jobs) for jobs in queue.values())
    if not qualifying:
        print("DAILY REVIEW: No new qualifying jobs were discovered in this run.")
    else:
        print(f"DAILY REVIEW: {qualifying} new qualifying job(s) discovered in this run.")
        print(format_review_queue(queue))
    if args.dry_run:
        run_result["resumes_generated"] = 0
        run_result["elapsed_time"] = time.monotonic() - started
        _print_daily_summary(run_result, _empty_queue_result(), {"added": 0}, dry_run=True,
                             manual_indeed=manual_indeed)
        return 0
    eligible_ids = run_result.get("new_job_ids", [])
    if evaluator.enabled:
        eligible_ids = [job_id for job_id in eligible_ids
                        if (evaluation := evaluations.get(job_id)) is not None
                        if evaluation.apply_decision == "Yes"]
    queue_result = _daily_resume_runner(eligible_ids, store)
    if not evaluator.enabled:
        run_result["Apply_Yes"] = (
            len(queue_result.snapshot.pending) + len(queue_result.snapshot.already_created)
        )
    run_result["resumes_generated"] = queue_result.created
    run_result["failures"] += len(queue_result.failures) + manual_indeed.failures
    gmail_result, gmail_error = _daily_gmail_response_runner()
    run_result["failures"] += int(bool(gmail_error))
    run_result["elapsed_time"] = time.monotonic() - started
    _print_daily_summary(
        run_result, queue_result,
        getattr(search_args, "tracker_summary", {"added": 0}),
        gmail_result=gmail_result, gmail_error=gmail_error, manual_indeed=manual_indeed,
    )
    return queue_result.exit_code or result


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--preferences", help="Alternate preferences JSON")
    parser.add_argument("--sources-config", help="Alternate job source configuration JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    find = sub.add_parser("search", help="Search configured providers and save role-relevant results")
    find.add_argument(
        "--source",
        choices=["all", "core", *CORE_PROVIDERS],
        default=DEFAULT_SOURCE,
        help=(f"Provider to query (default: {DEFAULT_SOURCE}); core is every enabled "
              "supported source (Web Careers uses Brave when configured)"),
    )
    find.add_argument("--query", action="append", help="Repeat for multiple role queries; defaults to all target roles")
    find.add_argument(
        "--location", action="append",
        help="Repeat for non-Remotive providers; defaults to Utah and Remote. Remotive is always Remote.",
    )
    find.add_argument("--page", type=int, default=1)
    find.add_argument("--results", type=int, default=20)
    find.add_argument(
        "--limit", type=int, default=100,
        help="Unique Remotive jobs to import after within-provider deduplication (default: 100)",
    )
    find.set_defaults(function=search)
    diagnostic = sub.add_parser(
        "diagnose-remotive",
        help="Run a read-only Remotive-only API, filter, and deduplication diagnostic",
    )
    diagnostic.add_argument(
        "--query", action="append",
        help="Repeat to override the digital marketing / paid search / PPC / analytics queries",
    )
    diagnostic.add_argument(
        "--results", type=int, default=10_000,
        help="Maximum matching records considered per query (default: 10000)",
    )
    diagnostic.add_argument("--examples", type=int, default=5)
    diagnostic.set_defaults(function=diagnose_remotive)
    feeds_diagnostic = sub.add_parser(
        "diagnose-remotive-feeds",
        help="Dry-run Remotive RSS acquisition and deduplication",
    )
    feeds_diagnostic.add_argument("--limit", type=int, default=100)
    feeds_diagnostic.set_defaults(function=diagnose_remotive_feeds)
    verify_parser = sub.add_parser(
        "verify-sources", help="Read-only live verification of every Job Scout provider",
    )
    verify_parser.add_argument("--results", type=int, default=5)
    verify_parser.set_defaults(function=verify_sources)
    listing = sub.add_parser("list", help="Show saved jobs")
    listing.add_argument("--status", choices=["new", "reviewing", "selected", "resume-created", "applied", "contacted", "interview", "rejected", "offer", "ignored"])
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
    enrich_parser = sub.add_parser("enrich", help="Retrieve fuller descriptions")
    enrich_parser.add_argument("job_id", nargs="?", type=int)
    enrich_parser.add_argument("--all", action="store_true", help="Enrich all Adzuna jobs")
    enrich_parser.set_defaults(function=enrich_jobs)
    resolve_parser = sub.add_parser(
        "resolve-url", help="Verify provider links and find authoritative employer/ATS postings",
    )
    resolve_parser.add_argument("job_id", nargs="?", type=int)
    resolve_parser.add_argument("--jooble", action="store_true", help="Resolve unresolved Jooble-sourced jobs")
    resolve_parser.add_argument("--limit", type=int, default=20)
    resolve_parser.add_argument("--force", action="store_true", help="Retry jobs with an existing URL status")
    resolve_parser.set_defaults(function=resolve_urls)
    review_parser = sub.add_parser("review", help="Show the prioritized, read-only Job Scout review queue")
    review_parser.add_argument("--limit", type=int, default=20)
    review_parser.add_argument("--json", action="store_true")
    review_parser.add_argument(
        "--include-closed", action="store_true",
        help="Include applied, rejected, and ignored jobs",
    )
    review_parser.set_defaults(function=review_jobs)
    daily_parser = sub.add_parser(
        "daily", help="Search, sync, approve Utah/remote jobs, and create Gecko resumes"
    )
    daily_parser.add_argument("--results", type=int, default=20)
    daily_parser.add_argument("--limit", type=int, default=20)
    daily_parser.add_argument(
        "--dry-run", action="store_true",
        help="Run discovery against a temporary database without tracker or resume writes",
    )
    daily_parser.set_defaults(function=daily)
    sync_parser = sub.add_parser(
        "sync-sheets",
        help="Synchronize Job Scout datastore values to the canonical Google Sheet",
    )
    sync_parser.set_defaults(function=sync_sheets)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        load_local_environment()
        load_local_environment(PROJECT_ROOT / ".env.google-sheets.local")
        preferences = load_preferences(args.preferences)
        with JobStore(args.db) as store:
            return args.function(args, store, preferences)
    except (OSError, RuntimeError, ValueError, ProviderError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
