"""Complete source acquisition with per-query failures and pagination evidence."""
from dataclasses import replace
from .base import ProviderError


def search_pages(provider, request):
    """Continue supported pages until exhausted; fail on a repeating page."""
    page = request.page
    seen = set()
    while True:
        rows = list(provider.search(replace(request, page=page)))
        signature = tuple(sorted((r.source_job_id, r.url) for r in rows))
        if rows and signature in seen:
            raise ProviderError(f'{provider.name}: pagination repeated page {page}')
        seen.add(signature)
        yield from rows
        if not getattr(provider, 'has_more', False):
            return
        page += 1


def acquire(provider, requests):
    """Keep successful requests when another query fails; retain partial rows."""
    rows, errors = [], []
    if callable(getattr(type(provider), 'full_feed', None)):
        rows.extend(provider.full_feed())
    else:
        for request in requests:
            try:
                rows.extend(search_pages(provider, request))
            except (ProviderError, OSError, ValueError) as exc:
                errors.append({'query': request.query, 'location': request.location,
                               'error': str(exc)})
                # A source-wide auth, payment or rate failure cannot be repaired by another query.
                if any(code in str(exc) for code in ('HTTP Error 401', 'HTTP Error 402',
                                                    'HTTP Error 403', 'HTTP Error 429')):
                    break
    errors.extend(getattr(provider, 'board_errors', []))
    errors.extend(getattr(provider, 'errors', []))
    errors.extend({'category': r['category'], 'error': r['error']}
                  for r in getattr(provider, 'feed_results', []) if not r['success'])
    return rows, errors
