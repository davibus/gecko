"""Complete source acquisition with per-query failures and pagination evidence."""
from dataclasses import replace
from .base import ProviderError


def search_pages(provider, request):
    """Continue supported pages until exhausted; fail on a repeating page."""
    page = request.page
    seen = set()
    while True:
        event = {'query': request.query, 'location': request.location, 'page':page,
                 'page_size':request.results_per_page, 'status':'attempted'}
        if not hasattr(provider,'acquisition_events'): provider.acquisition_events=[]
        provider.acquisition_events.append(event)
        rows=[]
        prior_errors=len(getattr(provider,'errors',[]))
        try:
            for row in provider.search(replace(request,page=page)):
                rows.append(row)
        except (ProviderError,OSError,ValueError) as error:
            event.update(status='failed', parsed=len(rows), error=str(error))
            yield from rows
            raise
        reported_errors=getattr(provider,'errors',[])[prior_errors:]
        if reported_errors:
            event.update(status='failed',parsed=len(rows),error=str(reported_errors))
            yield from rows
            raise ProviderError(str(reported_errors))
        event.update(status='completed',parsed=len(rows))
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
        provider.acquisition_events=[{'kind':'full feed','status':'attempted'}]
        try:
            rows.extend(provider.full_feed())
            provider.acquisition_events[0].update(status='completed',parsed=len(rows))
        except (ProviderError,OSError,ValueError) as exc:
            provider.acquisition_events[0].update(status='failed',parsed=len(rows),error=str(exc))
            errors.append({'error':str(exc)})
    else:
        for request in requests:
            try:
                rows.extend(search_pages(provider, request))
            except (ProviderError, OSError, ValueError) as exc:
                errors.append({'query': request.query, 'location': request.location,
                               'error': str(exc)})
                # A source-wide auth, payment or rate failure cannot be repaired by another query.
                if any(code in str(exc) for code in ('HTTP Error 401', 'HTTP Error 402',
                                                    'HTTP Error 403', 'HTTP Error 429', 'cached billing failure',
                                                    'HTTP 401', 'HTTP 402', 'HTTP 403', 'HTTP 429')):
                    break
            latest_errors=getattr(provider,'errors',[])
            if latest_errors and '402' in str(latest_errors[-1]):
                break
    errors.extend(getattr(provider, 'board_errors', []))
    errors.extend(getattr(provider, 'errors', []))
    errors.extend({'category': r['category'], 'error': r['error']}
                  for r in getattr(provider, 'feed_results', []) if not r['success'])
    return rows, errors
