"""Evidence-preserving, deterministic job parsing; no network or AI calls."""
from html.parser import HTMLParser
import html
import json
import re
from urllib.parse import urljoin, urlsplit

from description_retrieval import description_is_sufficient
from normalize import clean_text
from sources.http import _validate_public_url
from sources.base import ProviderError


class MarkdownHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.ignored = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.ignored += 1
        if self.ignored:
            return
        if tag in {'p', 'div', 'section', 'ul', 'ol', 'table', 'tr'}:
            self.parts.append('\n\n')
        elif tag == 'li':
            self.parts.append('\n- ')
        elif tag == 'br':
            self.parts.append('\n')
        elif re.fullmatch('h[1-6]', tag):
            self.parts.append('\n\n' + '#' * int(tag[1]) + ' ')
        elif tag in {'td', 'th'}:
            self.parts.append(' | ')
    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.ignored = max(0, self.ignored - 1)
        elif not self.ignored and tag in {'p', 'div', 'li', 'section'} | {'h' + str(i) for i in range(1, 7)}:
            self.parts.append('\n\n')
    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def markdown(value):
    if value is None:
        return ''
    if isinstance(value, list):
        return '\n'.join(filter(None, (markdown(v) for v in value)))
    if isinstance(value, dict):
        return markdown(value.get('text') or value.get('description') or value.get('name') or value.get('value'))
    value = str(value)
    if re.search(r'</?[a-z][^>]*>', value, re.I):
        parser = MarkdownHTML(); parser.feed(value)
        value = ''.join(parser.parts)
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', html.unescape(value)).strip()


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).replace(',', '').strip()
    if not re.fullmatch(r'\d+(?:\.\d+)?[kK]?', text):
        return None
    number = float(text.rstrip('kK')) * (1000 if text.lower().endswith('k') else 1)
    return int(number) if number.is_integer() else number


def _salary(item, text):
    result = {'minimum': None, 'maximum': None, 'currency': None, 'pay_period': None, 'evidence': None}
    base = item.get('baseSalary')
    periods = {'year': 'year', 'annual': 'year', 'annually': 'year', 'hour': 'hour', 'hourly': 'hour',
               'hr': 'hour', 'month': 'month', 'monthly': 'month', 'week': 'week', 'weekly': 'week', 'day': 'day'}
    if base is not None:
        amount = base.get('value') if isinstance(base, dict) else base
        currency = (base.get('currency') if isinstance(base, dict) else None) or item.get('salaryCurrency')
        if isinstance(amount, dict):
            exact = _number(amount.get('value'))
            low, high = _number(amount.get('minValue')), _number(amount.get('maxValue'))
            period = periods.get(str(amount.get('unitText') or '').casefold())
        else:
            exact, low, high, period = _number(amount), None, None, None
        result.update(minimum=low if low is not None else exact, maximum=high if high is not None else exact,
                      currency=currency, pay_period=period, evidence='JobPosting.baseSalary: ' + json.dumps(base))
    if result['minimum'] is None and result['maximum'] is None:
        for match in re.finditer(r'(?P<currency>USD|CAD|EUR|GBP|\$|€|£)\s*(?P<low>\d[\d,]*(?:\.\d+)?[kK]?)\s*(?:(?:-|–|—|to)\s*(?:USD|CAD|EUR|GBP|\$|€|£)?\s*(?P<high>\d[\d,]*(?:\.\d+)?[kK]?))?(?:\s*(?:per|/|a)\s*(?P<period>year|hour|hr|month|week|day)|\s*(?P<adverb>annually|annual|hourly|monthly|weekly))?', text, re.I):
            prefix = text[max(0, match.start()-60):match.start()]
            if re.search(r'application(?: processing)? fee[^.\n]*$', prefix, re.I):
                continue
            if not (match['period'] or match['adverb'] or re.search(r'\b(?:salary|compensation|pay range|base pay)\b', prefix, re.I)):
                continue
            low = _number(match['low']); high = _number(match['high']) if match['high'] else low
            result.update(minimum=low, maximum=high, currency=match['currency'],
                          pay_period=periods.get(str(match['period'] or match['adverb'] or '').casefold()), evidence=match[0])
            break
    if result['minimum'] is not None and result['maximum'] is not None and result['minimum'] > result['maximum']:
        result['minimum'] = result['maximum'] = None  # conflicting bounds remain in evidence
    return result


def salary_display(salary):
    low, high = salary['minimum'], salary['maximum']
    if low is None and high is None:
        return ''
    def number(v): return f'{v:,}' if isinstance(v, int) else str(v)
    values = (number(low) if low is not None else '') + ('–' + number(high) if high is not None and high != low else '')
    if low is None:
        values = 'up to ' + number(high)
    return ' '.join(filter(None, [salary['currency'], values, ('per ' + salary['pay_period']) if salary['pay_period'] else '']))


def _section(text, names):
    lines = text.splitlines(); found = []; active = False
    for line in lines:
        heading = line.strip().strip('#*: ').casefold()
        if any(re.fullmatch(name, heading) for name in names):
            active = True; continue
        if active and (line.startswith('#') or re.fullmatch(r'[A-Za-z &/]{3,50}:', line.strip())):
            break
        if active:
            found.append(line)
    return '\n'.join(found).strip() or None


def _fee(text, item):
    declared = item.get('applicationFee')
    if isinstance(declared, dict) and declared.get('required') is True:
        return True, 'JobPosting.applicationFee: ' + json.dumps(declared)
    for sentence in re.split(r'(?<=[.!?])\s+|\n', text):
        if not re.search(r'\b(?:application|application processing|processing) fee\b', sentence, re.I):
            continue
        if re.search(r'\b(?:no|without)\s+(?:(?:mandatory|required|an?)\s+)?application(?: processing)? fee\b|\b(?:do not|does not|never)\s+charge\b|\b(?:application|processing) fee\b.{0,40}\b(?:not required|not charged)\b', sentence, re.I):
            return False, sentence.strip()
        if re.search(r'\b(?:may|might|optional|could)\b|if applicable', sentence, re.I):
            continue
        if re.search(r'\b(?:required|mandatory|must)\b', sentence, re.I):
            return True, sentence.strip()
    return None, None


def _application_url(item, page, text, target):
    action = item.get('potentialAction') or {}
    if isinstance(action, list):
        action = next((a for a in action if isinstance(a, dict) and a.get('@type') == 'ApplyAction'), {})
    action_target = action.get('target') if isinstance(action, dict) and action.get('@type') == 'ApplyAction' else None
    if isinstance(action_target, dict):
        action_target = action_target.get('urlTemplate') or action_target.get('url')
    choices = [item.get('applicationUrl'), action_target,
               item.get('url') if item.get('directApply') is True else None]
    choices += re.findall(r'\[(?:apply(?: now| here| for this job)?)\]\(([^)]+)\)', text, re.I)
    choices += re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>\s*(?:apply now|apply here|apply)\s*</a>', page, re.I)
    for choice in choices:
        if not isinstance(choice, str) or '{' in choice:
            continue
        value = urljoin(target, html.unescape(choice))
        try:
            _validate_public_url(value)
            return value
        except (ValueError, ProviderError):
            continue
    return None


def _company_website(item, text, page, target, company):
    """Use declared organization URLs or explicit employer home-page links only."""
    employer = item.get('hiringOrganization') or {}
    candidates = []
    if isinstance(employer, dict):
        candidates.append(employer.get('url'))
    links = re.findall(r'\[([^\]\n]+)\]\(([^\s)]+)\)', text)
    class Anchors(HTMLParser):
        def __init__(self):
            super().__init__(); self.href = None; self.label = []
        def handle_starttag(self, tag, attrs):
            if tag == 'a':
                self.href = dict(attrs).get('href'); self.label = []
        def handle_data(self, value):
            if self.href is not None: self.label.append(value)
        def handle_endtag(self, tag):
            if tag == 'a' and self.href is not None:
                links.append((''.join(self.label), self.href)); self.href = None
    parser = Anchors(); parser.feed(page)
    name = clean_text(company or '').casefold()
    for label, href in links:
        label = clean_text(label).casefold()
        if (re.fullmatch(r'(?:company|employer) (?:website|home ?page)', label)
                or (name and name in label and re.search(r'\b(?:home ?page|website)\b', label))):
            candidates.append(href)
    for value in candidates:
        if not isinstance(value, str) or not value.strip(): continue
        value = urljoin(target, html.unescape(value.strip()))
        try: _validate_public_url(value)
        except ProviderError: continue
        host = (urlsplit(value).hostname or '').casefold()
        if any(host == h or host.endswith('.' + h) for h in (
                'lever.co', 'greenhouse.io', 'ashbyhq.com', 'workable.com',
                'linkedin.com', 'facebook.com', 'eeoc.gov')):
            continue
        return value
    return None


def extract(data, raw, date_evidence):
    item = raw.metadata
    source_markdown = str(data.get('markdown') or '')
    source_html = str(data.get('rawHtml') or data.get('html') or '')
    original = item.get('description') or ''
    structured = markdown(original)
    # Keep the published Markdown verbatim and append only missing source
    # paragraphs/structured sections; do not replace either with a summary.
    full = source_markdown.strip() or structured
    supplements = [structured]
    for label, key in [('Responsibilities', 'responsibilities'), ('Required qualifications', 'qualifications'),
                       ('Preferred qualifications', 'preferredQualifications'),
                       ('Skills', 'skills'), ('Education requirements', 'educationRequirements'),
                       ('Experience requirements', 'experienceRequirements'), ('Benefits', 'jobBenefits'),
                       ('Work hours', 'workHours'), ('Special requirements', 'specialCommitments')]:
        value = markdown(item.get(key))
        if value and clean_text(value).casefold() not in clean_text(full).casefold():
            supplements.append('## ' + label + '\n\n' + value)
    for supplement in supplements:
        for paragraph in re.split(r'\n\s*\n', supplement):
            if paragraph.strip() and clean_text(paragraph).casefold() not in clean_text(full).casefold():
                full += '\n\n' + paragraph.strip()
    employment_raw = item.get('employmentType') or ''
    types = employment_raw if isinstance(employment_raw, list) else re.split(r'[,;/]', str(employment_raw))
    employment_map = {'fulltime': 'full-time', 'parttime': 'part-time', 'contractor': 'contract',
                      'contract': 'contract', 'temporary': 'temporary', 'temp': 'temporary',
                      'intern': 'internship', 'internship': 'internship', 'seasonal': 'seasonal', 'perdiem': 'per-diem'}
    employment = [employment_map.get(re.sub('[^a-z]', '', t.casefold()), t.strip().casefold()) for t in types if t]
    if not employment:
        employment = list(dict.fromkeys(m.group(1).lower().replace(' ', '-') for m in re.finditer(r'(?:employment type\s*:\s*|\b(?:a|this is a)\s+)(full[ -]time|part[ -]time|contract|temporary|internship)\b', full, re.I)))
    arrangement = None; arrangement_evidence = None
    patterns = [('hybrid', r'\bhybrid (?:role|position|schedule|work|arrangement)\b|(?:work arrangement|workplace type|location)\s*:\s*hybrid'),
                ('remote', r'\b(?:fully|100%) remote\b|\bremote (?:role|position|work arrangement)\b|(?:work arrangement|workplace type|location)\s*:\s*remote'),
                ('on-site', r'\bon[ -]site (?:role|position|work|schedule)\b|\bin[ -]office (?:role|position)\b|(?:work arrangement|workplace type|location)\s*:\s*on[ -]site')]
    for name, pattern in patterns:
        match = re.search(pattern, full, re.I)
        if match:
            arrangement, arrangement_evidence = name, match[0]; break
    if arrangement is None and str(item.get('jobLocationType') or '').upper() == 'TELECOMMUTE':
        arrangement, arrangement_evidence = 'remote', 'JobPosting.jobLocationType=TELECOMMUTE'
    restrictions = markdown(item.get('applicantLocationRequirements')) or None
    restriction_lines = [line.strip() for line in full.splitlines() if re.search(r'must (?:reside|be located)|remote.*(?:only|restricted)|work authori[sz]ation|visa sponsorship', line, re.I)]
    restrictions = '\n'.join(filter(None, [restrictions, *restriction_lines])) or None
    hours = markdown(item.get('workHours')) or None
    if hours is None:
        match = re.search(r'\b\d{1,2}(?:\s*[-–]\s*\d{1,2})?\s*hours?\s*(?:per|a|/)\s*(?:week|day)\b', full, re.I)
        hours = match[0] if match else None
    schedule = _section(full, ['work hours', 'schedule', 'work schedule']) or hours
    if schedule is None:
        stated = re.search(r'(?im)^.*\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b.*(?:\b(?:AM|PM)\b|through|to|\bshift\b).*$', full)
        schedule = stated[0].strip() if stated else None
    required = markdown(item.get('qualifications')) or _section(full, ['required qualifications', 'requirements', 'qualifications', 'what you bring'])
    preferred = markdown(item.get('preferredQualifications')) or _section(full, ['preferred qualifications', 'preferred', 'nice to have'])
    responsibilities = markdown(item.get('responsibilities')) or _section(full, ['responsibilities', 'what you.ll do', 'duties'])
    benefits = markdown(item.get('jobBenefits') or item.get('benefits')) or _section(full, ['benefits', 'what we offer'])
    special = '\n'.join(filter(None, [markdown(item.get(k)) for k in ('specialCommitments', 'eligibilityToWorkRequirement', 'securityClearanceRequirement')])) or _section(full, ['special requirements', 'additional requirements'])
    salary = _salary(item, full)
    fee, fee_evidence = _fee(full, item)
    fields = {'company': raw.company or None, 'title': raw.title or None, 'employment_types': employment,
              'work_hours': hours, 'schedule': schedule, 'salary': salary,
              'work_arrangement': arrangement, 'work_arrangement_evidence': arrangement_evidence,
              'location': raw.location or None, 'remote_eligibility_restrictions': restrictions,
              'application_fee_required': fee, 'application_fee_evidence': fee_evidence,
              'notes': _section(full, ['notes', 'additional information']) or special, 'special_requirements': special, 'responsibilities': responsibilities,
              'required_qualifications': required, 'preferred_qualifications': preferred, 'benefits': benefits,
              'original_posting_date': raw.date_posted or None, 'posting_date_evidence': date_evidence or None,
              'application_url': _application_url(item, source_html, source_markdown, raw.url),
              'employer_job_id': str(item.get('identifier', {}).get('value') or raw.source_job_id) if isinstance(item.get('identifier'), dict) else raw.source_job_id or None,
              'discovery_source': 'Firecrawl',
              'company_website': _company_website(item, source_markdown, source_html, raw.url, raw.company)}
    issues = []
    if (data.get('metadata') or {}).get('truncated') is True or data.get('truncated') is True:
        issues.append('Provider reports truncated content')
    if not raw.company or not raw.title:
        issues.append('Missing company or job title')
    if not description_is_sufficient(full):
        issues.append('Empty or insufficient full description')
    if any(re.search(r'(?:read more|show more|view full (?:job )?description|description truncated|sign in to (?:view|continue)|\.{3}|…)\s*[.!…]*\s*$', text, re.I) for text in (source_markdown, structured)):
        issues.append('Source appears truncated or access limited')
    if (data.get('metadata') or {}).get('statusCode', 200) != 200:
        issues.append('Posting is inaccessible')
    for section in re.finditer(r'(?m)^#{1,6}\s*(Responsibilities|Required qualifications|Qualifications|Benefits)\s*$', full):
        remainder = full[section.end():].strip()
        if not remainder or remainder.startswith('#'):
            issues.append('Published section is empty: ' + section[1])
    return {'status': 'complete' if not issues else 'review', 'issues': issues,
            'fields': fields, 'full_description_markdown': full, 'original_description': original,
            'raw_markdown': source_markdown, 'raw_html': source_html, 'source_url': raw.url}


def tracker_notes(details):
    f = details.get('fields', details)
    labels = [('work_hours', 'Work hours'), ('schedule', 'Schedule'), ('notes', 'Published notes'),
              ('remote_eligibility_restrictions', 'Remote eligibility'), ('special_requirements', 'Special requirements'),
              ('application_fee_evidence', 'Application fee evidence'), ('application_url', 'Direct application URL')]
    return '\n'.join(label + ': ' + str(f[key]) for key,label in labels if f.get(key))


def sheet_description(full):
    # Preserve over-limit descriptions in job_documents; never silently truncate.
    return full if len(full.encode('utf-16-le')) // 2 <= 50000 else ''
