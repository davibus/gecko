"""Eligibility from explicit source evidence; unknown facts stay unknown."""
import json
import re
from pathlib import Path

def source_location_blocker(raw):
    """Structured source countries outrank a generic remote flag."""
    metadata=raw.metadata
    workplace=str(metadata.get('workplaceType') or '').casefold()
    if workplace in ('hybrid','onsite','on-site') and not re.search(r'\bUtah\b|,\s*UT\b',raw.location,re.I):
        return 'Structured employer workplace is '+workplace+' outside verified Utah location; generic remote flag does not establish eligibility: '+raw.location
    countries=[]
    def walk(value):
        if isinstance(value,dict):
            if value.get('@type')=='Country' and value.get('name'):
                countries.append(str(value['name']).strip())
            for key,item in value.items():
                if key in ('addressCountry','country','country_code') and isinstance(item,str) and item:
                    countries.append(item.strip())
                elif key in ('address','postalAddress','secondaryLocations','locations','jobLocation','country'):walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    walk(metadata.get('applicantLocationRequirements'))
    if not countries:walk(metadata)
    if not countries:return ''
    allowed={'us','usa','united states','united states of america','worldwide','global'}
    if any(c.casefold() in allowed for c in countries):return ''
    return 'Structured employer/ATS country excludes verified U.S./Utah eligibility: '+', '.join(sorted(set(countries)))

def location_blocker(job):
    """Honor explicit applicant restrictions, including ISO country codes."""
    restriction=str(job.details.get('fields',{}).get('remote_eligibility_restrictions') or '').strip()
    if re.search(r'(?:except|exclud(?:e|es|ing)|not (?:hiring|accepting|considering)[^.;\n]{0,80})[^.;\n]{0,80}\bUtah\b',restriction,re.I):
        return 'Explicit applicant restriction excludes Utah: '+restriction
    # Hiring-region restrictions override a generic country/global marker.
    for line in restriction.splitlines():
        if (re.search(r'only (?:hiring|accepting|considering)',line,re.I)
                and re.search(r'Eastern|Central|Pacific|Atlantic',line,re.I)
                and not re.search(r'Mountain|all (?:US|U.S.|United States) time',line,re.I)):
            return 'Utah/Mountain time excluded by explicit hiring-zone restriction: '+line
    text=restriction or str(job.location or '').strip()
    countries=json.loads((Path(__file__).with_name('country-regions.json')).read_text(encoding='utf-8-sig'))
    us=lambda value:bool(re.search(r'\b(?:USA|United States|Worldwide|Anywhere|Global)\b',value,re.I) or re.search(r'\bUS\b',value))
    # A country-tagged requisition is distinct from a global job at the same
    # company. A generic country eligibility marker cannot resolve that conflict.
    for country in countries:
        if country['code'] in ('US','001'):continue
        name=re.escape(country['name'])
        if (not us(job.title) and re.search(r'(?:\||[-\u2013\u2014]|\()\s*'+name+r'\s*(?:\||\)|[-\u2013\u2014]|Remote|$)',job.title,re.I)):
            return 'Country-specific requisition: '+country['name']+'; Utah eligibility unverified'
    if us(text):return ''
    for country in countries:
        if country['code']=='US':continue
        if text.casefold() in {country['code'].casefold(),country['iso3'].casefold(),country['name'].casefold()}:
            return 'Explicit foreign-only applicant country: '+country['name']+' ('+country['code']+')'
        if len(country['name'])>3 and re.search(r'\b'+re.escape(country['name'])+r'\b',text,re.I):
            return 'Foreign-only job location/restriction: '+country['name']+'; U.S./Utah eligibility unverified'
    if re.fullmatch(r'[A-Z]{2}(?:\s*[,;/]\s*[A-Z]{2})*',text):
        # With no explicit US/global evidence, a country-code restriction is not
        # proof of Utah eligibility. Keep ambiguous state codes pending too.
        if text not in ('UT',):return 'Country/region restriction '+text+' does not establish U.S./Utah eligibility'
    if re.search(r'\b(?:Egypt|Bulgaria|Romania|Philippines|South Africa|Serbia|Poland|Argentina|Brazil|LATAM|EMEA|Canada|United Kingdom|Australia|New Zealand|India)\b',text,re.I):
        return 'Explicit foreign-only applicant restriction: '+text
    return ''
