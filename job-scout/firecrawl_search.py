"""Budget-aware breadth followed by evidence-based Firecrawl search expansion.

The v2 web-search contract has no pagination token/offset. Expansion uses only
documented larger limits (up to 100) and temporary excludeDomains filters.
All work uses the existing queries table and shared reservation ledger.
"""
from collections import Counter
import json
from urllib.parse import urlsplit

from firecrawl_state import request_key, SEARCH_MAX_RESULTS


def records(history, day):
    with history.connect() as con:
        return {r['query_key']: dict(r) for r in con.execute('SELECT * FROM queries WHERE day=?', (day,))}


def uncovered(history, queries, day):
    saved = records(history, day)
    return [q for q in queries if q['key'] not in saved or saved[q['key']]['status'] != 'complete']


def minimum_search_reservation(settings):
    return settings['pricing']['search_per_10_results'] + settings['reservation_headroom']


def extraction_room(history, queries, day):
    """Keep enough request-admission capacity for every remaining base category."""
    return max(0, history.remaining_budget(day) -
               len(uncovered(history, queries, day)) * minimum_search_reservation(history.settings))


def _limit(available, settings, maximum):
    blocks = int(max(0, available - settings['reservation_headroom']) // settings['pricing']['search_per_10_results'])
    return min(maximum, blocks * 10)


def _payload(query, limit, cutoff, now, zone, excluded=()):
    # Prefer actual employer/ATS postings over broad aggregator search pages.
    scope = ' (site:jobs.lever.co OR site:job-boards.greenhouse.io OR site:jobs.ashbyhq.com OR site:apply.workable.com OR inurl:careers)'
    targeted = query + scope if len(query + scope) <= 500 else query
    value = {'query': targeted, 'limit': limit, 'sources': ['web'], 'country': 'US',
             'highlights': False, 'domainTools': False,
             'tbs': f'cdr:1,cd_min:{cutoff.astimezone(zone):%m/%d/%Y},cd_max:{now.astimezone(zone):%m/%d/%Y}'}
    if excluded:
        value['excludeDomains'] = list(excluded)
    return value


def _work(query, payload, kind='breadth', depth=1, parent=None):
    root = parent or query['key']
    return {**query, 'key': root if kind == 'breadth' else request_key('search-expansion', {'parent': root, 'payload': payload}),
            'parent_key': root, 'payload': payload, 'kind': kind, 'depth': depth}


def next_work(history, queries, day, cutoff, now, zone):
    """Choose one request, then let extraction establish its actual job yield."""
    settings = history.settings
    saved = records(history, day)
    # Reuse an exact saved payload after an interrupted ingestion; config changes
    # must never turn a restart into an extra paid request.
    for key, row in saved.items():
        if row['status'] == 'retrieved':
            stats = json.loads(row['stats_json'])
            payload = stats.get('payload') or _payload(row['query'], 10, cutoff, now, zone)
            return {'key': key, 'query': row['query'], 'parent_key': stats.get('parent_key', key),
                    'kind': stats.get('kind', 'breadth'), 'depth': stats.get('depth', 1), 'payload': payload}
    # Cached interrupted ingestion may resume at the limit, but no new breadth
    # or expansion request may exceed the configured daily query count.
    if len(saved) >= settings['max_queries_per_day']:
        return None
    remaining = uncovered(history, queries, day)
    available = history.remaining_budget(day)
    minimum = minimum_search_reservation(settings)
    if remaining:
        if available < minimum:
            return None
        # Target 50 results where affordable, while preserving coverage and a
        # modest verification reserve. More expensive pricing reduces depth.
        verification = min(settings.get('search_verification_headroom_credits', 20),
                           max(0, available - len(remaining) * minimum))
        quota = max(minimum, (available - verification) / len(remaining))
        limit = _limit(quota, settings, settings['results_per_query'])
        return _work(remaining[0], _payload(remaining[0]['query'], limit, cutoff, now, zone))
    with history.connect() as con:
        used_scrapes = con.execute("SELECT COUNT(*) FROM requests WHERE day=? AND endpoint='scrape'", (day,)).fetchone()[0]
        verifications = con.execute('SELECT COUNT(*) FROM candidates WHERE last_attempt_at LIKE ?', (day + '%',)).fetchone()[0]
    if used_scrapes >= settings['max_scrapes_per_day'] or verifications >= settings['max_unknown_date_verifications_per_day']:
        return None
    expansions = []
    for query in queries:
        root = query['key']
        pages = [(key, row, json.loads(row['stats_json'])) for key, row in saved.items()
                 if row['status'] == 'complete' and json.loads(row['stats_json']).get('parent_key', key) == root]
        if not pages:
            continue
        key, last, stats = max(pages, key=lambda item: item[2].get('depth', 1))
        results = json.loads(last['result_json'] or '[]')
        old_limit = stats.get('requested_limit', 10)
        if len(results) < old_limit or not stats.get('new_candidates', stats.get('qualified', 0)):
            continue  # exhausted or duplicate-only; no blind deeper requests
        with history.connect() as con:
            qualified = con.execute("SELECT COUNT(*) FROM candidates WHERE query_key=? AND qualified_at IS NOT NULL AND verification_status IN ('validated','synced')", (key,)).fetchone()[0]
        if not qualified:
            continue
        # Expansion must leave capacity to verify at least one new candidate.
        scrape_reserve = settings['pricing']['basic_scrape'] + settings['reservation_headroom']
        limit = _limit(available - scrape_reserve, settings, SEARCH_MAX_RESULTS)
        excluded = tuple(stats.get('payload', {}).get('excludeDomains', []))
        if old_limit < SEARCH_MAX_RESULTS:
            limit = min(limit, max(settings['results_per_query'], old_limit * 2))
            if limit <= old_limit:
                continue
            kind = 'deeper_results'
        else:
            hosts = Counter(urlsplit(r.get('url', '')).hostname for r in results if r.get('url'))
            fresh_hosts = [host for host, _ in hosts.most_common() if host and host not in excluded]
            if not fresh_hosts or limit < 1:
                continue
            excluded = tuple(sorted((*excluded, fresh_hosts[0])))
            limit = min(limit, settings['results_per_query'])
            kind = 'domain_expansion'
        work = _work(query, _payload(query['query'], limit, cutoff, now, zone, excluded),
                     kind, stats.get('depth', 1) + 1, root)
        if work['key'] not in saved:
            search_credits = stats.get('search_credits', 0)
            with history.connect() as con:
                extraction_credits = con.execute('SELECT COALESCE(SUM(credits),0) FROM candidates WHERE query_key=?', (key,)).fetchone()[0]
            score = qualified / max(1, search_credits + extraction_credits)
            expansions.append((score, work))
    return max(expansions, key=lambda item: item[0])[1] if expansions else None


def coverage(history, queries, day):
    saved = records(history, day)
    covered = [q for q in queries if q['key'] in saved and saved[q['key']]['status'] == 'complete']
    expansions = [r for k,r in saved.items() if json.loads(r['stats_json']).get('kind', 'breadth') != 'breadth']
    return {'configured': len(queries), 'completed': len(covered),
            'uncovered_queries': [q['query'] for q in queries if q not in covered],
            'expansion_requests': len(expansions), 'pagination_supported': False,
            'expansion_methods': ['larger_result_limit', 'temporary_domain_exclusions'],
            'requested_depths': [json.loads(r['stats_json']).get('requested_limit', 10) for r in saved.values()]}
