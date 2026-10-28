"""Normalize tracker salary displays without changing raw discovery evidence."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import ast
import html
import re

NUMBER = r'\d+(?:[, \u00a0]\d{3})*(?:\.\d+)?[ \t]*[kK]?'
CURRENCY = r'(?:USD|CAD|AUD|EUR|GBP|US\$|CA\$|A\$|\$|€|£)'
MONEY = re.compile(
    rf'(?<![\w.])(?P<currency>{CURRENCY})?[ \t]*(?P<low>{NUMBER})'
    rf'(?:[ \t]*(?P<currency_mid>USD|CAD|AUD|EUR|GBP))?'
    rf'(?:[ \t]*(?:-|–|—|to)[ \t]*(?P<currency2>{CURRENCY})?[ \t]*(?P<high>{NUMBER}))?'
    rf'(?:\s*(?P<currency3>USD|CAD|AUD|EUR|GBP))?'
    r'(?:\s*(?:per|/|an?|each)\s*(?P<period>yearly|annually|annual|year|hourly|hour|hr|monthly|month|weekly|week|daily|day|task)\b'
    r'|\s*(?P<period2>annually|annual|yearly|hourly|monthly|weekly|daily)\b)?', re.I)
STANDARD = re.compile(r'^\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?(?: - \$\d{1,3}(?:,\d{3})*(?:\.\d{2})?)?(?: (?:CAD|AUD|EUR|GBP))?$')
PAY_LABEL = re.compile(r'\b(?:salary|base pay|base compensation|pay range|rate of pay|pay transparency|compensation(?: range)?|annual compensation|estimated pay ranges?|annual base pay|total earnings|on.target earnings)\b', re.I)
BASE_LABEL = re.compile(r'\bbase\s+(?:salary|pay|compensation)\b', re.I)


def _number(value):
    return Decimal(re.sub(r'[kK\s,]', '', value)) * (1000 if 'k' in value.casefold() else 1)


def _money(value):
    value = value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    return '$' + (f'{value:,.0f}' if value == value.to_integral() else f'{value:,.2f}')


@dataclass(frozen=True)
class Salary:
    low: Decimal
    high: Decimal | None
    currency: str
    period: str
    evidence: str
    source: str
    score: int
    qualifier: str = ''


def _candidates(text, source):
    text = str(text or '')
    # ATS salary blocks often have a pay-range wrapper after a regional heading.
    text = re.sub(r'<[^>]*class=["\'][^"\']*pay-range[^"\']*["\'][^>]*>', ' Salary range: ', text, flags=re.I)
    text = html.unescape(re.sub(r'<[^>]+>', ' ', text)).replace('\\-', '-')
    text = re.sub(r'(?<=\d)[\u00a0 ](?=\d{3}\b)', '', text)
    text = re.sub(r'(?<=\d)\s+and\s+(?=(?:USD|CAD|AUD|EUR|GBP|\$|€|£)?\s*\d)', ' - ', text, flags=re.I)
    text = re.sub(r'\[\s*(USD|CAD|AUD|EUR|GBP)\s*\]', r'\1', text, flags=re.I)
    # Public ATS schemas can arrive as a QuantitativeValue dictionary string.
    if source == 'Salary' and text.strip().startswith('{'):
        try:
            item = ast.literal_eval(text)
            amount = item.get('value', item)
            if isinstance(amount, dict):
                low = amount.get('minValue', amount.get('value'))
                high = amount.get('maxValue')
                if low is not None:
                    yield Salary(Decimal(str(low)), Decimal(str(high)) if high is not None else None,
                                 str(item.get('currency') or 'USD'), str(amount.get('unitText') or 'YEAR').casefold(),
                                 text, source, 5)
                    return
        except (ValueError, SyntaxError, TypeError, AttributeError):
            pass
    for match in MONEY.finditer(text):
        before = text[max(0, match.start()-250):match.start()]
        after = text[match.end():match.end()+55]
        clause = re.split(r'[\n.!?;]|\|', before)[-1]
        label = PAY_LABEL.search(clause)
        # Region labels can separate the payment from the salary heading.
        if not label and re.search(r'\b(?:zone [a-z]|(?:us )?remote range|san francisco|new york|california|colorado|utah|canada)\b', clause, re.I):
            label = PAY_LABEL.search(before)
        if re.search(r'(?:PHP|INR|PLN|BRL|MXN|SGD|HKD|NZD|CHF|ZAR|₱|₹)\s*$', before, re.I):
            continue  # preserve unsupported currency rather than invent USD
        marked = bool(match['currency'] or match['currency_mid'] or match['currency3'])
        immediate_label = re.search(r'\b(?:salary|pay|compensation)(?: range)?\s*(?:is|:|of|from|between)?\s*$',clause,re.I)
        if not marked and not immediate_label and text.strip() != match[0].strip():
            continue  # e.g. 401K is a benefit, never a $401,000 salary
        if source != 'Salary' and not label:
            continue
        if source == 'Salary' and not (match['currency'] or match['currency_mid'] or match['currency3'] or label
                or text.strip() == match[0].strip()):
            continue
        if re.search(r'\b(?:fee|stipend|allowance|budget|revenue|401k|reimbursement|bonus|sign.on|equity grant)\b[^.!?;\n]*$', clause, re.I) and not label:
            continue
        nearby = text[max(0, match.start()-90):match.start()]
        if (re.search(r'\b(?:budget|advertising spend|ad spend|media spend|campaign spend|revenue)\b[^.!?\n]{0,55}$', nearby, re.I)
                and not re.search(r'\b(?:salary|base pay|pay range)\b[^.!?\n]{0,25}$', nearby, re.I)):
            continue  # campaign spend is not employee compensation
        low = _number(match['low']); high = _number(match['high']) if match['high'] else None
        # A shared k suffix in "120-150k" applies to both range endpoints.
        if high is not None and 'k' in match['high'].casefold() and 'k' not in match['low'].casefold() and low < 1000:
            low *= 1000
        currency = (match['currency3'] or match['currency2'] or match['currency_mid'] or match['currency'] or 'USD').upper()
        currency = {'$':'USD','US$':'USD','CA$':'CAD','A$':'AUD','€':'EUR','£':'GBP'}.get(currency,currency)
        if re.match(r'\s*/\s*(?:USD|CAD|AUD|EUR|GBP)', after, re.I):
            continue  # mixed-currency range is ambiguous
        prefix_period = re.search(r'\b(hourly|monthly|weekly|daily|annual)\s+(?:base\s+)?(?:pay|salary|compensation)\b',clause,re.I)
        period = (match['period'] or match['period2'] or (prefix_period[1] if prefix_period else 'year')).casefold()
        period = {'yearly':'year','annual':'year','annually':'year','hourly':'hour','hr':'hour',
                  'monthly':'month','weekly':'week','daily':'day'}.get(period,period)
        if low <= 0 or (high is not None and high < low) or period == 'task':
            continue
        if period in {'year','yearly','annual','annually'} and low < 10000:
            continue  # never turn small unlabeled payments into annual salaries
        qualifier = ''
        if re.search(r'\b(?:estimated?|predicted)\b', clause + ' ' + after, re.I):
            qualifier = 'Provider estimate; not confirmed employer base pay.'
        if re.search(r'\b(?:OTE|on.target earnings|total compensation|base and bonus)\b', clause, re.I):
            qualifier = 'Posted total/OTE compensation; not base salary alone.'
        if re.search(r'\b(?:up to|at most|maximum(?: of)?)\s*:?\s*$', clause, re.I):
            qualifier = 'Posted upper bound only; not a guaranteed salary.'
        elif re.search(r'\b(?:from|at least|minimum(?: of)?|starting (?:at|point))\s*:?\s*$', clause, re.I) and high is None:
            qualifier = 'Posted lower bound only.'
        base = bool(BASE_LABEL.search(clause))
        score = 5 if source == 'Salary' else 3
        score += 4 if base else 0
        score += 2 if label and high is not None else 0
        score += 1 if currency == 'USD' else 0
        score -= 5 if 'estimate' in qualifier.casefold() else 0
        yield Salary(low, high, currency, period, match[0].strip(), source, score, qualifier)


def _no_amount(row, reason):
    current = str(row.get('Salary') or '').strip()
    if not current:
        return {}, {'reason':reason}
    changes = {'Salary':''}
    if current.casefold() not in {'not stated','not disclosed','not specified','n/a','unknown','negotiable','tbd','none'}:
        notes = str(row.get('Notes') or '')
        addition = 'Original source text (no reliable annual pay extracted):\n' + current
        if addition not in notes:
            changes['Notes'] = notes.rstrip() + ('\n\n' if notes.strip() else '') + addition
            if len(changes['Notes']) > 49000:
                return {}, {'reason':'notes are too long to preserve original salary text safely'}
    return changes, {'reason':'salary text moved to Notes; amount left blank','original_salary':current,'formatted_salary':''}


def normalize_salary_row(row):
    """Keep prose in Notes; display a posted amount/range or leave Salary blank."""
    from description_columns import description_value
    row = {**row, 'Job Description': description_value(row)}
    current = str(row.get('Salary') or '').strip()
    if STANDARD.fullmatch(current):
        return {}, {'reason':'already standard'}
    candidates = []
    for source in ('Salary','Notes','Job Description'):
        candidates.extend(_candidates(row.get(source,''),source))
        if source == 'Salary' and candidates and max(c.score for c in candidates) >= 6:
            break  # readable posted salary wins over unrelated context amounts
    if not candidates:
        return _no_amount(row, 'no explicit salary amount')
    best = max(c.score for c in candidates)
    choices = [c for c in candidates if c.score == best]
    # An advertised range takes precedence over isolated amounts elsewhere in
    # the prose. For multiple equally ranked ranges, retain the first posted one.
    item = next((c for c in choices if c.high is not None), choices[0])
    alternatives = len({(c.low,c.high,c.currency,c.period) for c in candidates if c.source == item.source}) > 1
    period = item.period
    multiplier = Decimal(1); assumption = ''
    context = current + '\n' + str(row.get('Notes') or '') + '\n' + str(row.get('Job Description') or '')
    if period in {'hour','hourly','hr'}:
        hours = re.search(r'(?<![\d-])(\d{1,2}(?:\.\d+)?)\s*hours?\s*(?:per|a|/)\s*week\b',context,re.I)
        weekly = Decimal(hours[1]) if hours and 0 < Decimal(hours[1]) <= 80 else Decimal(40)
        multiplier = weekly * 52
        assumption = f'{weekly:g} hours/week × 52 weeks/year'
    elif period in {'month','monthly'}:
        multiplier=Decimal(12);assumption='12 months/year'
    elif period in {'week','weekly'}:
        multiplier=Decimal(52);assumption='52 weeks/year'
    elif period in {'day','daily'}:
        multiplier=Decimal(260);assumption='5 days/week × 52 weeks/year'
    elif period not in {'year','yearly','annual','annually'}:
        return _no_amount(row, 'unsupported pay period')
    display = _money(item.low * multiplier)
    if item.high is not None:
        display += ' - ' + _money(item.high * multiplier)
    if item.currency != 'USD':
        display += ' ' + item.currency
    changes = {'Salary':display}
    note = item.qualifier
    if alternatives:
        note = (note + ' Multiple posted amounts/rates were listed. Salary displays the advertised range '
                '(the first listed range when equally ranked); alternate rates and conditions remain in the original text.').strip()
        if current:
            note += '\nOriginal salary text:\n' + current
    if assumption:
        note = f'Estimated annual equivalent of {item.evidence} using {assumption}. This is an annualized rate, not guaranteed yearly earnings. ' + note
    if note:
        addition = 'Salary details: ' + note.strip()
        notes = str(row.get('Notes') or '')
        if addition not in notes:
            changes['Notes'] = notes.rstrip() + ('\n\n' if notes.strip() else '') + addition
            if len(changes['Notes']) > 49000:
                return {}, {'reason':'notes are too long to preserve conversion evidence safely'}
    return changes, {'reason':'annualized' if assumption else 'formatted', 'source':item.source,
                     'evidence':item.evidence,'original_salary':row.get('Salary',''),'formatted_salary':display}


def extract_salary(raw_salary, description, metadata=None, *, with_notes=False):
    """Extract evidence-backed annual pay during discovery, even if source salary is absent.

    Structured compensation is authoritative. Original descriptions are fallback;
    never invent market estimates or confuse advertising budgets with pay.
    """
    metadata = metadata if isinstance(metadata, dict) else {}
    structured = metadata.get('baseSalary')
    if not structured:
        ranges = metadata.get('salaryRange')
        if isinstance(ranges, dict) and ranges.get('min') is not None:
            structured = {'currency': ranges.get('currency') or 'USD',
                          'value': {'minValue': ranges['min'], 'maxValue': ranges.get('max'),
                                    'unitText': ranges.get('interval') or 'YEAR'}}
    omitted_note = ''
    for original in (structured, raw_salary):
        if not original:
            continue
        original = str(original)
        changes, _ = normalize_salary_row({'Salary': original,
                                          'Job Description': '' if structured and original == str(structured)
                                          else (description or '')})
        if changes.get('Salary'):
            return (changes['Salary'], changes.get('Notes', '')) if with_notes else changes['Salary']
        if not changes and STANDARD.fullmatch(original.strip()):
            return (original.strip(), '') if with_notes else original.strip()
        omitted_note = changes.get('Notes', '') or omitted_note
    changes, _ = normalize_salary_row({'Salary': '', 'Job Description': description or ''})
    amount = changes.get('Salary', '')
    note = changes.get('Notes', '') or (omitted_note if not amount else '')
    return (amount, note) if with_notes else amount
