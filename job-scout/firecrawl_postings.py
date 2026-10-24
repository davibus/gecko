"""Cheap posting admission and exact, free public ATS verification.

Search dates/snippets never establish original posting dates or eligibility.
An unavailable public endpoint is not retried through a different transport.
"""
from datetime import datetime, timezone
import html
import json
import re
from urllib.parse import urlsplit, parse_qs, quote

from sources.http import get_json, get_document
from sources.base import ProviderError


def reject_result(url, title, cutoff):
    parts = urlsplit(url)
    host = (parts.hostname or '').lower().removeprefix('www.')
    path = parts.path.lower()
    if (re.search(r'/jobs?-srch|/jobs?/search|/search/jobs|/search-results', path)
            or (host == 'indeed.com' and ('/viewjob' not in path and '/rc/clk' not in path))
            or (host == 'glassdoor.com' and '/job-listing/' not in path)
            or re.search(r'\b\d[\d,]*\+?\s+(?:remote\s+)?(?:digital marketing|paid search|marketing)\s+jobs\b', title, re.I)):
        return 'Generic search/list page; no individual posting'
    if re.search(r'\b(?:talent pool|future opening|talent community)\b', title, re.I):
        return 'Future opening or talent pool'
    dated_path = re.search(r'/(20\d{2})/(\d{2})/(\d{2})/', path)
    if dated_path:
        try:
            date = datetime(*map(int, dated_path.groups()), tzinfo=timezone.utc)
            if (cutoff - date).days > 2:
                return 'Old dated URL; excluded before paid retrieval'
        except ValueError:
            pass
    if host in {'jobs.lever.co', 'jobs.ashbyhq.com'} and len(path.strip('/').split('/')) < 2:
        return 'Employer board index; no individual posting'
    return ''


def _company(platform, tenant):
    from sources.config import load_source_config
    for company in load_source_config()['providers'].get(platform, {}).get('companies', []):
        if tenant in [company.get(k) for k in ('site', 'token', 'board', 'slug')]:
            return company.get('name') or ''
    return ''


def public_listing(url, cache=None):
    """Return full original ATS evidence, or None without spending Firecrawl credits.

    Only known public posting endpoints are used. Original dates are retained;
    Greenhouse updated_at is deliberately never substituted for first_published.
    """
    from firecrawl_discovery import extract_listing, identity
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    bits = parts.path.strip('/').split('/')
    cache = cache if cache is not None else {}
    item = None
    try:
        if host in {'boards.greenhouse.io', 'job-boards.greenhouse.io'} and len(bits) >= 3 and bits[1] == 'jobs' and bits[2].isdigit():
            endpoint = f'https://boards-api.greenhouse.io/v1/boards/{quote(bits[0])}/jobs/{bits[2]}?content=true'
            d = get_json(endpoint)
            if str(d.get('id')) != bits[2] or not d.get('company_name'):
                return None
            item = {'title': d.get('title'), 'hiringOrganization': {'name': d['company_name']},
                    'identifier': {'value': str(d['id'])}, 'description': html.unescape(d.get('content') or ''),
                    'datePosted': d.get('first_published') or '', 'employmentType': d.get('employment_type') or '',
                    'jobLocation': {'address': d.get('location', {}).get('name', '')}}
            location = d.get('location', {}).get('name', '')
            if re.search(r'\bremote\b', location, re.I):
                item['jobLocationType'] = 'TELECOMMUTE'
        elif host == 'jobs.lever.co' and len(bits) >= 2:
            endpoint = f'https://api.lever.co/v0/postings/{quote(bits[0])}/{quote(bits[1])}?mode=json'
            d = get_json(endpoint)
            company = _company('lever', bits[0])
            if not company or str(d.get('id')) != bits[1] or identity(d.get('hostedUrl') or '') != identity(url):
                return None
            sections = [d.get('description') or d.get('descriptionPlain') or '']
            sections += ['<h2>' + str(x.get('text') or '') + '</h2>' + str(x.get('content') or '') for x in d.get('lists') or []]
            sections.append(d.get('additional') or d.get('additionalPlain') or '')
            created = d.get('createdAt')
            posted = datetime.fromtimestamp(created / 1000, timezone.utc).isoformat() if isinstance(created, (int, float)) else ''
            categories = d.get('categories') or {}
            sr = d.get('salaryRange') or {}
            item = {'title': d.get('text'), 'hiringOrganization': {'name': company},
                    'identifier': {'value': bits[1]}, 'description': '\n'.join(sections),
                    'datePosted': posted, 'employmentType': categories.get('commitment') or '',
                    'jobLocation': {'address': categories.get('location') or ''}}
            if sr.get('min') is not None:
                item['baseSalary'] = {'currency': sr.get('currency'), 'value': {'minValue': sr['min'], 'maxValue': sr.get('max'), 'unitText': sr.get('interval') or 'YEAR'}}
            if d.get('workplaceType') == 'remote':
                item['jobLocationType'] = 'TELECOMMUTE'
        elif host == 'jobs.ashbyhq.com' and len(bits) >= 2:
            endpoint = f'https://api.ashbyhq.com/posting-api/job-board/{quote(bits[0])}?includeCompensation=true'
            if endpoint not in cache:
                cache[endpoint] = get_json(endpoint)
            payload = cache[endpoint]
            matches = [j for j in payload.get('jobs', []) if str(j.get('id')) == bits[1]]
            company = _company('ashby', bits[0])
            if len(matches) != 1 or not company:
                return None
            d = matches[0]
            if not d.get('isListed', True) or identity(d.get('jobUrl') or '') != identity(url):
                return None
            item = {'title': d.get('title'), 'hiringOrganization': {'name': company},
                    'identifier': {'value': bits[1]}, 'description': d.get('descriptionHtml') or d.get('descriptionPlain') or '',
                    'datePosted': d.get('publishedAt') or '', 'employmentType': d.get('employmentType') or '',
                    'jobLocation': {'address': d.get('location') or ''}}
            if d.get('isRemote'):
                item['jobLocationType'] = 'TELECOMMUTE'
        elif host not in {'jobs.lever.co', 'jobs.ashbyhq.com', 'boards.greenhouse.io', 'job-boards.greenhouse.io', 'apply.workable.com'}:
            return None
        if item is not None:
            # This is a normalized representation of the saved public API record,
            # not a claim that the employer page contained this JSON-LD script.
            item.update({'@type': 'JobPosting', 'url': url})
            data = {'rawHtml': '<script type="application/ld+json">' + json.dumps(item).replace('<', '\\u003c') + '</script>',
                    'metadata': {'statusCode': 200, 'url': url}, 'public_api': {'url': endpoint, 'data': d}}
            raw, _, final = extract_listing(data, url)
            if raw is None:
                raise ProviderError('Public ATS record could not be normalized; retained for review')
            raw.metadata['_retrieved_via'] = 'public-ats-api'
            evidence = 'Public employer ATS original posting date: ' + str(item['datePosted']) if item['datePosted'] else ''
            return data, raw, evidence, final
        page = get_document(url)
        data = {'rawHtml': page.body.decode('utf-8', errors='replace'), 'metadata': {'statusCode': 200, 'url': page.final_url}}
        raw, evidence, final = extract_listing(data, url)
        return (data, raw, evidence, final) if raw else None
    except ProviderError:
        # Explicit target failures are retained, not bypassed with a paid proxy.
        raise
