#!/usr/bin/env python
"""Gecko Job Scout command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

from enrichment import enrich_and_store
from deduplicate import find_duplicate
from google_tracker import GoogleTracker, marked
from handoff import archive_listing
from link_validation import DailyLinkValidator
from models import RawListing
from normalize import normalize
from normalize import canonicalize_url
from preferences import load_preferences
from review import build_review_queue, format_review_queue, queue_to_json
from role_filter import is_relevant_role
from service import discover, discover_remotive_full_feed
from sources import (
    AdzunaProvider, IndeedProvider, ProviderError, RemotiveProvider,
    WebCareerProvider,
)
from sources.base import SearchRequest
from storage import DEFAULT_DB, JobStore
from url_resolution import resolve_and_store, url_status_label


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MASTER_RESUME = PROJECT_ROOT / "input" / "master-resume" / "Dave-Call-resume-9-23-26.docx"
DEFAULT_SOURCE = "adzuna"
CORE_PROVIDERS = ("adzuna", "remotive", "web-careers")


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
    return {
        provider.name: provider
        for provider in (
            AdzunaProvider(), RemotiveProvider(), IndeedProvider(),
            WebCareerProvider(),
        )
    }


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
    removed = tracker.remove_dead_scout(remove_scout_ids) if remove_scout_ids else set()
    if remove_scout_ids and removed != remove_scout_ids:
        raise RuntimeError(f"Google Sheets did not clear every unprotected Scout row: {sorted(remove_scout_ids - removed)}")
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
        if any(marked(row.get(field)) for field in ("Apply?", "Applied", "Contacted", "Resume Created")) or str(row.get("Gecko Status") or "").lower() not in {"", "new", "reviewing"}:
            protected.add(scout_id)
    for _, row in tracker.application().rows:
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
            item.authoritative_url = str(value("Authoritative URL") or "")
            result.append(item)
    return result


def search(args, store, preferences):
    daily_mode = bool(getattr(args, "daily_mode", False))
    link_validator = getattr(args, "link_validator", None) if daily_mode else None
    preexisting_ids = {job.id for job in store.all()}
    available = providers()
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
        "filtered_by_role": 0, "jooble_excluded": 0,
        "newly_discovered": 0, "already_existed": 0,
        "new_job_ids": [], "existing_job_ids": [],
        "unique_remotive_jobs_available": 0, "unique_jobs_imported": 0,
        "eligibility_includes_usa": 0, "eligibility_worldwide": 0,
        "example_jobs": [],
        "source_counts": {name: 0 for name in selected}, "source_backends": {},
        "source_diagnostics": {},
        "google_cse": {},
        "skipped_sources": [], "source_errors": {},
    }
    successful_sources = 0
    for name in selected:
        provider = available[name]
        if name == "web-careers":
            web_diagnostics = provider.diagnostics()
            aggregate["source_diagnostics"][name] = web_diagnostics
            aggregate["google_cse"] = web_diagnostics["google_cse"]
            if provider.backend:
                aggregate["source_backends"][name] = provider.backend
        if not provider.configured():
            aggregate["skipped_sources"].append(name)
            continue
        try:
            if name == "remotive":
                summary = discover_remotive_full_feed(
                    provider, store, limit=getattr(args, "limit", 100),
                    preserve_existing=daily_mode, preexisting_ids=preexisting_ids,
                    link_validator=link_validator,
                )
            else:
                summary = discover(
                    provider, requests, store,
                    preserve_existing=daily_mode, preexisting_ids=preexisting_ids,
                    link_validator=link_validator,
                )
        except ProviderError as error:
            aggregate["source_errors"][name] = str(error)
            print(f"Warning: {name} provider failed: {error}", file=sys.stderr)
            continue
        successful_sources += 1
        aggregate["source_counts"][name] = (
            (summary.unique_imported or summary.fetched)
            if name == "remotive" else summary.fetched
        )
        if summary.source_backend:
            aggregate["source_backends"][name] = summary.source_backend
        if name == "web-careers":
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
            "filtered_by_role", "jooble_excluded",
        ):
            aggregate[key] += getattr(summary, key)
        for job_id in summary.new_job_ids:
            if job_id not in aggregate["new_job_ids"]:
                aggregate["new_job_ids"].append(job_id)
        for job_id in summary.existing_job_ids:
            if job_id not in aggregate["existing_job_ids"]:
                aggregate["existing_job_ids"].append(job_id)
    aggregate["newly_discovered"] = len(aggregate["new_job_ids"])
    aggregate["already_existed"] = len(aggregate["existing_job_ids"])
    aggregate["sources_searched"] = successful_sources + len(aggregate["source_errors"])
    args.run_result = aggregate
    print(json.dumps(aggregate, indent=2))
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


def diagnose_remotive_rss(args, store, preferences):
    """Backward-compatible alias for the category-feed diagnostic."""
    return diagnose_remotive_feeds(args, store, preferences)


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
    print(json.dumps(get_job(store, args.job_id).to_dict(), indent=2))
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
    """Enrich one job or every Adzuna job without evaluating compatibility."""
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
    """Run the canonical Gecko queue for only IDs discovered in this daily run."""
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
        eligible_scout_ids=set(new_job_ids), print_summary=False,
        logger=generate_apply_queue._append_run_log,
    )
    generate_apply_queue._append_run_log(f"DAILY RESUME END exit_code={result.exit_code}")
    return result


def _print_daily_summary(run_result, queue_result, tracker_summary, *, dry_run=False):
    print("\nDaily Job Scout complete" + (" (dry run)" if dry_run else ""))
    print(f"Sources searched: {run_result.get('sources_searched', 0)}")
    print(f"Jobs discovered: {run_result.get('fetched', 0)}")
    print(f"Jooble jobs excluded: {run_result.get('jooble_excluded', 0)}")
    print(f"Duplicates skipped: {run_result.get('duplicates', 0)}")
    print(f"New jobs added: {tracker_summary.get('added', 0)}")
    print(f"Jobs marked Apply = Yes: {len(queue_result.snapshot.pending) + len(queue_result.snapshot.already_created)}")
    print(f"Resumes already existing: {len(queue_result.snapshot.already_created) + queue_result.recovered}")
    print(f"New Gecko resumes created: {queue_result.created}")
    print(f"Resume failures: {len(queue_result.failures)}")
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
    """Discover, sync, and generate Gecko resumes for new approved jobs."""
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
        checked = validator.check_existing(existing)
        dead = [(job, result) for job, result in checked if result.status == "dead"]
        removable = [(job, result) for job, result in dead if job.id not in protected]
        validator.protected_dead += len(dead) - len(removable)
        if removable and not args.dry_run:
            ids = {job.id for job, _ in removable}
            sync_tracker(store, jobs=[], append_only=True, remove_scout_ids=ids)
            uncleared = ids & scout_row_ids()
            if uncleared:
                raise RuntimeError(f"Confirmed-dead Scout rows were not cleared: {sorted(uncleared)}")
            for job, result in removable:
                store.delete_dead_unprotected(job.id)
                validator.record_removed(job, result)
    search_args = argparse.Namespace(
        source="core", query=None, location=None, page=1, results=args.results,
        limit=100, daily_mode=True,
        link_validator=validator, dry_run=args.dry_run,
    )
    result = search(search_args, store, preferences)
    print("Link validation:")
    for field in ("checked", "valid", "removed_dead", "temporary_failure", "protected_dead"):
        print(f"  {field}: {validator.report()[field]}")
    for removed in validator.removed:
        print(f"  removed: {removed['company']} | {removed['job_title']} | {removed['url']} | "
              f"{removed['reason_removed']} | HTTP/status {removed['http_status'] or 'n/a'}")
    run_result = getattr(search_args, "run_result", {})
    if result:
        _print_daily_summary(run_result, _empty_queue_result(), {"added": 0},
                             dry_run=args.dry_run)
        return result
    new_jobs = [store.get(job_id) for job_id in run_result.get("new_job_ids", [])]
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
        _print_daily_summary(run_result, _empty_queue_result(), {"added": 0}, dry_run=True)
        return 0
    queue_result = _daily_resume_runner(run_result.get("new_job_ids", []), store)
    _print_daily_summary(
        run_result, queue_result,
        getattr(search_args, "tracker_summary", {"added": 0}),
    )
    return queue_result.exit_code


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--preferences", help="Alternate preferences JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    find = sub.add_parser("search", help="Search configured providers and save role-relevant results")
    find.add_argument(
        "--source", "--provider",
        choices=["all", "core", "adzuna", "remotive", "indeed", "web-careers"],
        default=DEFAULT_SOURCE,
        help=(f"Provider to query (default: {DEFAULT_SOURCE}); core is Adzuna, "
              "Remotive, and Web Careers (Brave when configured)"),
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
    rss_diagnostic = sub.add_parser(
        "diagnose-remotive-rss",
        help="Backward-compatible alias for the Remotive category-feed diagnostic",
    )
    rss_diagnostic.add_argument("--limit", type=int, default=100)
    rss_diagnostic.set_defaults(function=diagnose_remotive_rss)
    feeds_diagnostic = sub.add_parser(
        "diagnose-remotive-feeds",
        help="Dry-run Remotive RSS acquisition and deduplication",
    )
    feeds_diagnostic.add_argument("--limit", type=int, default=100)
    feeds_diagnostic.set_defaults(function=diagnose_remotive_feeds)
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
        "daily", help="Search, sync, and create Gecko resumes for new approved jobs"
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
