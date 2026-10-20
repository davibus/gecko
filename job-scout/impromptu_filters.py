"""Per-run filters; never modifies the shared daily preferences."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_PROVIDERS = ('adzuna','remotive','web-careers','remote-careers','jobicy','remoteok','usajobs','greenhouse','lever','ashby','workable','weworkremotely','workingnomads','themuse','indeed','linkedin','glassdoor','ziprecruiter')
ARRANGEMENTS = ['remote', 'hybrid', 'on-site', 'unknown']
MATCHES = ['Strong (80–100)', 'Possible (50–79)', 'Low (0–49)', 'Unrated']
COSTS = ['No fee recorded', 'Fee required', 'Unknown']
LOCATIONS = ['Remote / anywhere', 'Utah (statewide)', 'Salt Lake City', 'Lehi', 'Draper', 'Provo', 'Orem', 'Midvale', 'Sandy', 'South Jordan', 'Ogden', 'Layton', 'Park City', 'St. George', 'Other / unknown']


def options():
    from preferences import load_preferences
    return dict(sources=list(CORE_PROVIDERS), titles=load_preferences()['target_roles'],
                arrangements=ARRANGEMENTS, matches=MATCHES, costs=COSTS, locations=LOCATIONS)


def validate(value):
    if not isinstance(value, dict):
        raise ValueError('Choose filters for this impromptu run.')
    allowed=options()
    result={}
    if type(value.get("create_resumes", False)) is not bool:
        raise ValueError("Create resumes must be on or off.")
    result["create_resumes"] = value.get("create_resumes", False)
    for key in ['sources','titles','arrangements','matches','costs','locations','priorities']:
        items=value.get(key)
        if not isinstance(items,list) or not items or len(items)>100 or any(not isinstance(x,str) or not x.strip() or len(x)>120 for x in items):
            raise ValueError('Select at least one '+key+' option.')
        if key not in ('priorities','titles') and any(x not in allowed[key] for x in items):
            raise ValueError('Unknown '+key+' selection. Refresh the filters.')
        result[key]=list(dict.fromkeys(x.strip() for x in items))
    for key in ['salary_min','salary_max']:
        raw=value.get(key,'')
        if raw in ('',None):result[key]=None
        elif type(raw) not in (int,float) or not 0<=raw<=10000000:
            raise ValueError('Salary must be a nonnegative annual USD amount.')
        else:result[key]=float(raw)
    if result['salary_min'] is not None and result['salary_max'] is not None and result['salary_min']>result['salary_max']:
        raise ValueError('Maximum salary must be at least the minimum.')
    if type(value.get('salary_unknown')) is not bool:
        raise ValueError('Choose whether to include unknown salaries.')
    result['salary_unknown']=value['salary_unknown']
    return result


def text(value):
    return ' '.join(re.findall(r'[a-z0-9]+',str(value or '').casefold()))


def matches(job, settings, known):
    if job.source not in settings['sources']:return False
    if not any(text(title) in text(job.title) for title in settings['titles']):return False
    arrangement=text(job.work_arrangement) or 'unknown'
    if arrangement=='on site':arrangement='on-site'
    if arrangement not in settings['arrangements']:return False
    location=text(job.location)
    groups=[]
    if arrangement=='remote':groups.append('Remote / anywhere')
    if 'utah' in location.split() or 'ut' in location.split():groups.append('Utah (statewide)')
    for city in LOCATIONS[2:-1]:
        if text(city) in location:groups.extend([city,'Utah (statewide)'])
    if not groups:groups=['Other / unknown']
    if not set(groups).intersection(settings['locations']):return False
    salary=str(job.salary or '')
    amounts=[]
    if re.search(r'USD|\$',salary,re.I) and not re.search(r'hour|/hr|month|week|day|EUR|GBP|CAD|AUD|NZD|CA\$|AU\$',salary,re.I):
        parts=re.findall(r'(\d[\d,]*(?:\.\d+)?)\s*(k\b)?',salary,re.I)
        if 1<=len(parts)<=2:amounts=[float(n.replace(',',''))*(1000 if k else 1) for n,k in parts]
        if any(n<1000 for n in amounts):amounts=[]
    if not amounts:
        if not settings['salary_unknown']:return False
    elif ((settings['salary_min'] is not None and max(amounts)<settings['salary_min']) or
          (settings['salary_max'] is not None and min(amounts)>settings['salary_max'])):return False
    record=known.get((str(job.source).casefold(),job.url),{})
    cost=str(record.get('cost','')).strip().casefold()
    cost_group='Fee required' if cost=='x' else 'No fee recorded' if cost in ('no','none','free','0') else 'Unknown'
    if cost_group not in settings['costs']:return False
    priority=str(record.get('priority','')).strip() or 'Unassigned'
    if priority not in settings['priorities']:return False
    score=record.get('score')
    category='Unrated' if score is None else MATCHES[0] if score>=80 else MATCHES[1] if score>=50 else MATCHES[2]
    return category in settings['matches']
