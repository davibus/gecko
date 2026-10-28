"""Normalize provider-specific records into the common JobListing model."""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl, parse_qs, urlencode, urlsplit, urlunsplit

from models import JobListing, RawListing


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
TRACKING_PARAMS = {
    "from", "ref", "referrer", "referral", "source", "trk", "trackingid",
    "gh_src", "lever-source", "gclid", "fbclid", "mc_cid", "mc_eid",
    "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term",
}


def clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = TAG_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = sorted(
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS and not key.lower().startswith("utm_")
    )
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))

def posting_identity(url: str):
    """Match supported posting aliases without using numeric tracker IDs."""
    parts=urlsplit(canonicalize_url(str(url or '')))
    host=(parts.hostname or '').casefold().removeprefix('www.')
    pieces=parts.path.strip('/').split('/')
    if host.endswith('indeed.com') and parse_qs(parts.query).get('jk'):
        return ('indeed',parse_qs(parts.query)['jk'][0])
    if host=='apply.workable.com' and 'j' in pieces and pieces.index('j')+1<len(pieces):
        return ('workable',pieces[pieces.index('j')+1])
    if host in {'boards.greenhouse.io','job-boards.greenhouse.io'}:
        host='job-boards.greenhouse.io'
    return ('url',host,parts.path,parts.query)


def posting_aliases(job: JobListing) -> set[tuple]:
    """Retain source and resolved URLs as evidence for the same saved posting."""
    urls = [job.url, job.canonical_url, job.original_url,
            job.authoritative_url, job.url_redirect_url]
    if job.enrichment_status == 'succeeded':
        urls.append(job.enriched_source_url)
    urls.extend(link.get('url', '') for link in job.source_links)
    return {posting_identity(url) for url in urls if str(url or '').strip()}


def infer_work_arrangement(raw: RawListing) -> str:
    # Provider fields take priority. Only explicit, job-specific declarations in
    # a title or description are fallback evidence, not generic remote benefits.
    def arrangement(value):
        value = clean_text(value).casefold()
        if re.search(r"\b(?:not (?:a )?remote|no remote|remote (?:work )?(?:is )?not (?:available|allowed|permitted))\b", value):
            return "on-site"
        if re.search(r"\bhybrid\b", value):
            return "hybrid"
        if re.search(r"\b(?:on[ -]?site|in[ -]office)\b", value):
            return "on-site"
        if re.search(r"\b(?:remote|telecommut(?:e|ing)|work[ -]from[ -]home)\b", value):
            return "remote"
        return None

    structured = arrangement(f"{raw.remote_type} {raw.location}")
    if structured:
        return structured
    description = clean_text(raw.description)
    declarations = re.findall(
        r"\b(?:location|work arrangement|workplace type|work location|job classification)\s*:\s*"
        r"((?:(?:fully|100%)\s+)?(?:remote|hybrid|on[ -]?site|in[ -]office|"
        r"not remote|no remote|work[ -]from[ -]home)\b[^.;\n]{0,45})",
        description, re.I,
    )
    # Keep role-specific denials and hybrid/on-site requirements ahead of an
    # otherwise remote title or location declaration.
    declarations += re.findall(
        r"\b(?:this (?:role|position|job) (?:is|requires)|work arrangement is)\s+"
        r"((?:not\s+)?(?:a\s+)?(?:fully\s+)?(?:remote|hybrid|on[ -]?site|in[ -]office)\b)",
        description, re.I,
    )
    # Some provider snippets start with the exact role header followed by its
    # arrangement, e.g. "Manager of Paid Search Remote As the Manager ...".
    header = re.sub(r'[\u200b-\u200d\ufeff]', '', description)
    header = re.sub(r'^(?:position|job title|title)\s*:\s*', '', header, flags=re.I)
    header_marker = re.match(
        re.escape(clean_text(raw.title)) + r'\s*[-–—|:]*\s*(remote|hybrid|on[ -]?site)\b',
        header, re.I,
    )
    if header_marker:
        declarations.append(header_marker[1])
    declared = {arrangement(value) for value in declarations} - {None}
    if "hybrid" in declared:
        return "hybrid"
    if "on-site" in declared:
        return "on-site"
    if "remote" in declared:
        return "remote"
    title = clean_text(raw.title)
    title_marker = re.search(
        r"(?:^|[-–—(|])\s*((?:fully\s+)?(?:remote|hybrid|on[ -]?site|in[ -]office)\b[^|)]{0,30})",
        title, re.I,
    )
    if title_marker:
        return arrangement(title_marker[1]) or "unknown"
    return "on-site" if raw.location else "unknown"


def normalize(raw: RawListing, discovered: str | None = None) -> JobListing:
    employment_type = clean_text(raw.employment_type).lower().replace("_", "-")
    employment_type = {'fulltime': 'full-time', 'parttime': 'part-time'}.get(
        employment_type, employment_type)
    discovered_date = discovered or JobListing.today()
    from salary_format import extract_salary
    salary = extract_salary(raw.salary, raw.description, raw.metadata)
    return JobListing(
        company=clean_text(raw.company) or "Unknown company",
        title=clean_text(raw.title),
        location=clean_text(raw.location),
        work_arrangement=infer_work_arrangement(raw),
        employment_type=employment_type,
        salary=salary,
        source=clean_text(raw.source),
        found_using=("Firecrawl" if str(raw.metadata.get("_discovered_via", "")).casefold()
                     in {"firecrawl", "firecrawl-search", "indeed-results-page"}
                     or (not raw.metadata.get("_discovered_via")
                         and str(raw.metadata.get("_retrieved_via", "")).casefold() == "firecrawl")
                     else "Gecko"),
        source_job_id=clean_text(raw.source_job_id),
        url=raw.url.strip(),
        date_posted=clean_text(raw.date_posted)[:10],
        date_discovered=discovered_date,
        description=clean_text(raw.description),
        canonical_url=canonicalize_url(raw.url),
        category=clean_text(raw.category),
        tags=[clean_text(tag) for tag in raw.tags if clean_text(tag)],
        last_seen=discovered_date,
        source_links=[{"source": clean_text(raw.source), "source_job_id": clean_text(raw.source_job_id), "url": raw.url.strip(),
            **({'source_requisition_id': 'greenhouse:'+str(raw.metadata['ats_company']).casefold()+':'+str(raw.metadata['internal_job_id'])}
               if raw.source.casefold()=='greenhouse' and raw.metadata.get('ats_company') and raw.metadata.get('internal_job_id') else {})}],
        indeed_application_method=str(raw.metadata.get("_indeed_application_method") or "")
        if raw.source.casefold() == "indeed" else "",
        indeed_application_verified_on=discovered_date
        if raw.source.casefold() == "indeed" and raw.metadata.get("_indeed_application_method") else "",
    )
