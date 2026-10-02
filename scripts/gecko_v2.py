"""Evidence-first Gecko V2 resume pipeline. Job Scout is intentionally separate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import fitz
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from silent_subprocess import windows_creationflags

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "input" / "master-resume" / "Dave-Call-Resume.txt"
FORMAT_MODEL = ROOT / "input" / "master-resume" / "MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf"
SECTIONS = (
    "Professional Summary", "Core Strengths", "Selected Results",
    "Professional Experience", "Tools & Platforms", "Education & Certifications",
)
MODEL_FONT = "EB Garamond"
MODEL_BODY_SIZE = 10.5
MODEL_OLIVE = (85, 107, 47)
TERMS = (
    "SEO", "technical SEO", "paid search", "Google Ads", "Bing Ads", "Microsoft Ads", "Meta Ads", "Google Analytics",
    "GA4", "Google Tag Manager", "GTM", "Looker Studio", "Tableau", "SQL", "Python", "JavaScript",
    "HTML5", "CSS3", "Magento", "Shopify", "WordPress", "Amazon", "HubSpot", "CRM", "email",
    "automation", "attribution", "CRO", "conversion rate optimization", "keyword research", "content",
    "schema markup", "metadata", "taxonomy", "link building", "Semrush", "Search Console", "e-commerce",
    "B2B", "B2C", "budget", "forecasting", "reporting", "analytics", "leadership", "management",
    "social media", "customer acquisition", "lifecycle", "AI", "machine learning", "Adobe Analytics",
    "Excel", "Power BI", "Salesforce", "Marketo", "Klaviyo", "Mailchimp", "Snowflake",
    "Core Web Vitals", "canonicalization", "XML sitemaps", "robots directives", "faceted navigation",
    "AI search", "AI Overviews", "backlinks", "schema", "structured data", "catalog", "merchandising",
    "Codex", "ChatGPT", "Claude", "Perplexity", "Cursor", "AntiGravity",
)
TOOLS = set("Google Ads|Bing Ads|Microsoft Ads|Meta Ads|Google Analytics|GA4|Google Tag Manager|GTM|Looker Studio|Tableau|SQL|Python|JavaScript|HTML5|CSS3|Magento|Shopify|WordPress|Amazon|HubSpot|Semrush|Search Console|Adobe Analytics|Excel|Power BI|Salesforce|Marketo|Klaviyo|Mailchimp|Snowflake|Codex|ChatGPT|Claude|Perplexity|Cursor|AntiGravity".split("|"))
STOP = set("the and for with from into your their our you will are this that have has must should ability using use work role team experience years strong plus including across based more about through".split())

# Canonical, source-backed labels used for the two mandatory competency sections.
# The marker strings must occur in the master archive; selection ranks them by
# relevance to the target listing and then uses catalog order as a stable tie-breaker.
CORE_STRENGTHS_CATALOG = (
    ("Digital Marketing Strategy", ("digital marketing", "marketing strategy")),
    ("Paid Media Strategy", ("paid media", "PPC strategy")),
    ("Performance Marketing", ("performance marketing",)),
    ("Marketing Analytics", ("analytics", "analytical")),
    ("E-Commerce Strategy", ("e-commerce", "e-commerce operations")),
    ("Conversion Rate Optimization", ("conversion-rate optimization", "CRO")),
    ("Cross-Functional Leadership", ("cross-functional leadership", "cross-functional communication")),
    ("Marketing Automation", ("automation", "process automation")),
    ("Attribution Modeling", ("attribution models", "attribution")),
    ("Budget Forecasting", ("forecasting", "budget scenarios")),
    ("Customer Acquisition", ("customer acquisition",)),
    ("Lead Generation", ("lead generation",)),
    ("SEO & SEM Strategy", ("SEO/SEM", "SEO", "SEM")),
    ("Campaign Optimization", ("campaign", "optimizations")),
    ("A/B & Multivariate Testing", ("A/B testing", "multivariate testing")),
    ("Data Visualization", ("data visualization",)),
    ("Team Development", ("team development", "trained team members")),
    ("B2B & B2C Marketing", ("B2B", "B2C")),
    ("Marketing Technology", ("marketing-technology",)),
    ("Operational Efficiency", ("operational efficiency",)),
)

TOOLS_PLATFORMS_CATALOG = (
    ("Google Ads", ("Google Ads", "AdWords")),
    ("Microsoft Ads", ("Microsoft Ads", "Bing Ads")),
    ("Google Analytics 4", ("Google Analytics 4", "GA4")),
    ("Google Tag Manager", ("Google Tag Manager",)),
    ("Google Search Console", ("Google Search Console",)),
    ("Looker Studio", ("Looker Studio", "Google Data Studio")),
    ("Tableau", ("Tableau",)),
    ("Power BI", ("Power BI",)),
    ("Google Ads Editor", ("Google Ads Editor",)),
    ("Bing Ads Editor", ("Bing Ads Editor",)),
    ("Meta Ads", ("Meta/Facebook Ads", "Meta Ads")),
    ("Amazon Seller Central", ("Amazon Seller Central",)),
    ("Amazon Vendor Central", ("Amazon Vendor Central",)),
    ("Shopify", ("Shopify",)),
    ("Magento", ("Magento",)),
    ("HubSpot", ("HubSpot",)),
    ("Salesforce", ("Salesforce",)),
    ("Funnel.io", ("Funnel.io",)),
    ("Python", ("Python",)),
    ("SQL", ("SQL",)),
    ("JavaScript", ("JavaScript",)),
    ("Excel", ("Excel",)),
    ("Google Ads API", ("Google Ads API",)),
    ("ChatGPT", ("ChatGPT",)),
    ("Codex", ("Codex",)),
    ("Claude", ("Claude",)),
    ("Gemini", ("Gemini",)),
    ("Perplexity", ("Perplexity",)),
    ("Cursor", ("Cursor",)),
    ("VS Code", ("VS Code",)),
)


def validate_required_sources() -> None:
    """Fail closed when either permanent Gecko authority is unavailable."""
    if not MASTER.is_file():
        raise FileNotFoundError(f"Required Gecko master resume could not be found: {MASTER}")
    if not FORMAT_MODEL.is_file():
        raise FileNotFoundError(f"Required Gecko formatting model could not be found: {FORMAT_MODEL}")


def formatting_model_hash() -> str:
    validate_required_sources()
    return hashlib.sha256(FORMAT_MODEL.read_bytes()).hexdigest()


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\ufffd", " ")).strip()


def key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def contains_term(haystack: str, term: str) -> bool:
    return bool(re.search(r"(?:^| )" + re.escape(key(term)) + r"(?: |$)", key(haystack)))


def words(text: str) -> set[str]:
    return {w for w in key(text).split() if len(w) > 2 and w not in STOP}


def _select_catalog_entries(listing: str, source: str, catalog: tuple, *, maximum: int) -> list[str]:
    """Choose at least eight canonical, source-backed entries, favoring target relevance."""
    supported = []
    for order, (label, markers) in enumerate(catalog):
        if not any(contains_term(source, marker) for marker in markers):
            continue
        direct_hits = sum(contains_term(listing, marker) for marker in markers)
        overlap = len(words(label) & words(listing))
        supported.append((direct_hits * 10 + overlap, order, label))
    if len(supported) < 8:
        raise ValueError("The master archive does not support at least eight required catalog entries.")
    relevant_count = sum(score > 0 for score, _, _ in supported)
    limit = min(maximum, max(8, relevant_count))
    supported.sort(key=lambda item: (-item[0], item[1]))
    return [label for _, _, label in supported[:limit]]


def select_core_strengths(listing: str, source: str) -> list[str]:
    return _select_catalog_entries(listing, source, CORE_STRENGTHS_CATALOG, maximum=12)


def select_tools_platforms(listing: str, source: str) -> list[str]:
    return _select_catalog_entries(listing, source, TOOLS_PLATFORMS_CATALOG, maximum=16)


def _canonical_labels(catalog: tuple) -> set[str]:
    return {label for label, _ in catalog}


def formatting_content_issues(core_strengths: list[str], tools_platforms: list[str]) -> list[str]:
    """Validate mandatory counts and canonical professional/brand capitalization."""
    issues = []
    if len(core_strengths) < 8:
        issues.append("CORE STRENGTHS contains fewer than 8 entries.")
    if len(tools_platforms) < 8:
        issues.append("TOOLS & PLATFORMS contains fewer than 8 entries.")
    core_labels = _canonical_labels(CORE_STRENGTHS_CATALOG)
    tool_labels = _canonical_labels(TOOLS_PLATFORMS_CATALOG)
    if any(value not in core_labels for value in core_strengths):
        issues.append("A CORE STRENGTHS entry lacks canonical professional Title Case.")
    if any(value not in tool_labels for value in tools_platforms):
        issues.append("A TOOLS & PLATFORMS entry lacks canonical brand capitalization.")
    if any(value == value.casefold() and re.search(r"[a-z]", value) for value in core_strengths + tools_platforms):
        issues.append("An obviously lowercase placeholder-style entry remains.")
    return issues


def normalize_resume_format(plan: dict) -> None:
    """Auto-correct mandatory section entries from current source and listing before rendering."""
    listing = Path(plan["listing"]).read_text(encoding="utf-8-sig")
    source = source_text()
    plan["resume"]["core_strengths"] = select_core_strengths(listing, source)
    plan["resume"]["tools_platforms"] = select_tools_platforms(listing, source)
    plan["resume"].pop("skills", None)


def document_format_issues(plan: dict, doc: Document) -> list[str]:
    """Inspect the mandatory section content and two-line experience hierarchy."""
    issues = formatting_content_issues(
        plan["resume"].get("core_strengths", []),
        plan["resume"].get("tools_platforms", []),
    )
    if not doc.tables:
        return issues + ["CORE STRENGTHS table is missing."]
    actual_strengths = [
        cell.text.strip() for row in doc.tables[0].rows for cell in row.cells if cell.text.strip()
    ]
    if actual_strengths != plan["resume"]["core_strengths"]:
        issues.append("CORE STRENGTHS entries differ from the validated plan.")

    body_paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    try:
        tools_heading = body_paragraphs.index("TOOLS & PLATFORMS")
        tools_line = body_paragraphs[tools_heading + 1]
    except (ValueError, IndexError):
        tools_line = ""
        issues.append("TOOLS & PLATFORMS section or content is missing.")
    expected_tools_line = " • ".join(plan["resume"]["tools_platforms"])
    if tools_line and tools_line != expected_tools_line:
        issues.append("TOOLS & PLATFORMS entries differ from the validated plan.")

    evidence = {item["id"]: item for item in plan["evidence"]}
    expected_jobs = [
        (job["title"], f"{job['company']}  {job['location']}" if job["location"] else job["company"])
        for index, job in enumerate(plan["resume"]["jobs"])
        if any(evidence[eid]["job"] == index for eid in plan["resume"]["selected_evidence_ids"])
    ]
    job_tables = doc.tables[1:]
    if len(job_tables) != len(expected_jobs):
        issues.append("Professional Experience job-header count differs from the plan.")
        return issues
    for table, (expected_title, expected_company) in zip(job_tables, expected_jobs):
        if len(table.rows) != 2 or len(table.columns) != 2:
            issues.append("A Professional Experience job does not use the required two-line hierarchy.")
            continue
        actual_title = table.cell(0, 0).text.strip()
        actual_company = table.cell(1, 0).text.strip()
        if actual_title != expected_title:
            issues.append("A Professional Experience job title is not on its own line.")
        if actual_company != expected_company:
            issues.append("A company and city/state line is not directly below its job title.")
        if " | " in actual_title or " | " in actual_company:
            issues.append("A job still uses the prohibited 'Job Title | Company' format.")
        if table.cell(0, 1).text.strip() or table.cell(1, 1).text.strip():
            issues.append("A date cell contains visible text.")
    return issues


def master_lines() -> list[str]:
    """Read the current master archive on every call."""
    return MASTER.read_text(encoding="utf-8-sig").splitlines()


def source_text() -> str:
    """Read the current master archive on every call."""
    return "\n".join(line.strip() for line in master_lines() if line.strip())


def source_hashes() -> dict[str, str]:
    return {str(MASTER.relative_to(ROOT)): hashlib.sha256(MASTER.read_bytes()).hexdigest()}


def _is_bullet(line: str) -> bool:
    return bool(re.match(r"^[\u2022\ufffd*-]\s+", line.strip()))


def _bullet_text(line: str) -> str:
    return normalized(re.sub(r"^[\u2022\ufffd*-]\s+", "", line.strip()))


def _is_job_header(line: str) -> bool:
    line = line.strip()
    return bool(re.match(r"^.+ \| .+$", line)) and not re.match(r"^.+,\s*[A-Z]{2}\s*\|", line) and not _is_bullet(line)


def parsed_jobs() -> list[dict]:
    """Employment roles from PROFESSIONAL EXPERIENCE; consulting remains in source_text()."""
    lines = [line.strip() for line in master_lines()]
    start = lines.index("PROFESSIONAL EXPERIENCE") + 1
    end = next(i for i, line in enumerate(lines)
               if line in {"CONSULTING, CONTRACT & CLIENT PROJECTS",
                           "PAID SEARCH, PERFORMANCE MARKETING & CLIENT PARTNERSHIP SCOPE"})
    jobs: list[dict] = []
    current = None
    skip = {"CONSULTING, CONTRACT & CLIENT PROJECTS", "Additional named client/contract work"}
    for line in lines[start:end]:
        if not line or line.startswith("---") or line in skip or line.startswith("The source material"):
            continue
        if _is_job_header(line):
            title, company = line.split(" | ", 1)
            current = {"title": title.strip(), "company": company.strip(), "location": "", "bullets": []}
            jobs.append(current)
            continue
        if current and re.match(r"^.+,\s*[A-Z]{2}\s*\|", line):
            current["location"] = line.split("|", 1)[0].strip()
            continue
        if current and _is_bullet(line):
            quote = _bullet_text(line)
            if len(quote) >= 35:
                current["bullets"].append(quote)
    if not jobs:
        raise ValueError("Master archive job history could not be parsed.")
    return jobs


def _highlight_job(quote: str, jobs: list[dict]) -> int | None:
    for index, job in enumerate(jobs):
        name = job["company"].split("/")[0].strip()
        if name and name.casefold() in quote.casefold():
            return index
    rules = (
        (r"\$30 million", "TravelPass"),
        (r"110,000 ad groups|1\.6 million", "TravelPass"),
        (r"75\+", "Infinite Agency"),
        (r"200,000 to .{0,30}800,000|ROAS from 1\.5", "GRIP6"),
        (r"\$9 million", "LifeSpan"),
        (r"650", "Intercon"),
        (r"25% of firm", "Bowen"),
        (r"Databricks", "1-800 Contacts"),
        (r"32 businesses", "Any Hour"),
    )
    for pattern, needle in rules:
        if re.search(pattern, quote, re.I):
            for index, job in enumerate(jobs):
                if needle.casefold() in job["company"].casefold() or needle.casefold() in job["title"].casefold():
                    return index
    return None


def extract_evidence(source: str) -> list[dict]:
    """Take results and work-history bullets from the canonical master archive only."""
    jobs = parsed_jobs()
    rel = str(MASTER.relative_to(ROOT))
    evidence = []
    for job_index, job in enumerate(jobs):
        for quote in job["bullets"]:
            evidence.append({"id": f"E{len(evidence)+1:03d}", "job": job_index, "source": rel, "quote": quote})
    lines = [line.strip() for line in master_lines()]
    for line in lines[lines.index("CAREER HIGHLIGHTS & SELECTED RESULTS") + 1:lines.index("PROFESSIONAL EXPERIENCE")]:
        if not _is_bullet(line):
            continue
        quote = _bullet_text(line)
        job_index = _highlight_job(quote, jobs)
        if job_index is None or len(quote) < 35:
            continue
        if any(item["quote"] == quote and item["job"] == job_index for item in evidence):
            continue
        evidence.append({"id": f"E{len(evidence)+1:03d}", "job": job_index, "source": rel, "quote": quote})
    return evidence


def listing_metadata(listing: str, path: Path) -> dict[str, str]:
    def field(name: str) -> str:
        match = re.search(rf"(?mi)^\s*-\s*\*\*{re.escape(name)}[^*]*\*\*\s*:?\s*(.*?)\s*$", listing)
        return match.group(1).strip(" `") if match else ""
    headline = next((line.lstrip("# ").strip() for line in listing.splitlines() if line.startswith("# ")), "")
    company = field("Company") or (headline.split(" — ")[-1] if " — " in headline else "")
    title = headline.split(" — ")[0] if headline else ""
    job_number = field("Job Key (Indeed jk)") or field("Job Number") or path.stem.split("+")[-1]
    if not company or not title or not job_number:
        raise ValueError("Listing needs a title, company, and job number; add metadata to the archived description.")
    safe_company = re.sub(r'[\\/:*?"<>|]', "", company).replace(" ", "-").rstrip(" .")
    return {"company": company, "safe_company": safe_company, "title": title, "job_number": job_number}


def resume_filename(company: str, title: str, job_number: str) -> str:
    """Build a Word-safe name while retaining the job number as the final field."""
    def safe_part(value: str) -> str:
        value = re.sub(r'[\\/:*?"<>|+]+', "-", normalized(value))
        value = re.sub(r"\s+", "-", value)
        return re.sub(r"-{2,}", "-", value).strip(" .-")

    company_part, title_part, number_part = map(safe_part, (company, title, job_number))
    if not all((company_part, title_part, number_part)):
        raise ValueError("Resume filename needs a company, job title, and job number")
    # Keep the complete path comfortable for Word on Windows; only long titles are shortened.
    available = 180 - len(f"Dave-Call+{company_part}++{number_part}.docx")
    if available < 20:
        raise ValueError("Company and job number leave too little room for the job title")
    return f"Dave-Call+{company_part}+{title_part[:available].rstrip(' .-')}+{number_part}.docx"


REQUIREMENT_STARTERS = (
    "ability to", "accredited", "analyze", "bachelor", "build", "collect", "collaborate",
    "comfortable", "communicate", "conduct", "coordinate", "create", "define", "develop",
    "drive", "ensure", "evangelize", "execute", "experience", "identify", "implement",
    "lead", "leverage", "maintain", "manage", "minimum", "monitor", "optimize", "oversee",
    "own", "partner", "present", "prior experience", "product knowledge", "proven", "provide",
    "represent", "report", "strong", "support", "understand", "when required", "work with",
)


def _requirement_candidates(listing: str) -> list[tuple[str, str]]:
    """Extract bullets and aggregator-flattened requirement clauses with section context."""
    text = listing.replace("\\n", "\n")
    # Aggregators frequently flatten section headings and every bullet into one paragraph.
    inline_headings = (
        "Professional Experience/Background to be successful in this role",
        "Competencies (Attributes needed to be successful in this role)",
        "Expected Outcomes in 3, 6, or 12 months",
        "Responsibilities", "Qualifications", "Required Qualifications",
        "Preferred Qualifications", "Requirements", "What You'll Do", "What You Will Do",
    )
    for label in inline_headings:
        text = re.sub(rf"\s*{re.escape(label)}\s*:\s*", f"\n## {label}\n", text, flags=re.I)
    starter_pattern = "|".join(re.escape(value) for value in sorted(REQUIREMENT_STARTERS, key=len, reverse=True))
    heading = ""
    candidates: list[tuple[str, str]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("#"):
            heading = key(stripped.lstrip("# "))
            continue
        if not stripped or stripped.startswith("- **") or stripped.startswith("http"):
            continue
        is_bullet = stripped.startswith(("-", "*", "•", "ï‚·"))
        clean = re.sub(r"^(?:[-*•]|ï‚·)\s+", "", stripped).strip()
        pieces = [clean] if is_bullet else re.split(
            rf"(?<=[.!?;])\s+|\s+(?=(?:{starter_pattern})\b)", clean, flags=re.I
        )
        for piece in pieces:
            candidate = normalized(piece).strip(" -•")
            if len(candidate) < 18 or len(candidate) > 500:
                continue
            contextual = bool(re.search(
                r"responsibil|qualification|requirement|experience|background|competenc|outcome|what you",
                heading, re.I,
            ))
            starts_like_requirement = bool(re.match(rf"(?:{starter_pattern})\b", candidate, re.I))
            if is_bullet or contextual or starts_like_requirement:
                candidates.append((heading, candidate))
    return candidates


def requirements(listing: str, source: str, evidence: list[dict]) -> dict[str, list[dict]]:
    result = {name: [] for name in ("required_skills", "preferred_skills", "responsibilities", "tools", "seniority_signals", "industry_terminology", "ats_keywords")}
    for heading, candidate in _requirement_candidates(listing):
        preferred = bool(re.search(r"preferred|nice to have|bonus|strong plus", heading + " " + candidate, re.I))
        required = bool(re.search(r"required|qualification|must have", heading + " " + candidate, re.I))
        category = "preferred_skills" if preferred else "required_skills" if required else "responsibilities"
        overlaps = [(len(words(candidate) & words(item["quote"])), item["id"]) for item in evidence]
        best = max(overlaps, default=(0, ""))
        term_hits = [term for term in TERMS if contains_term(candidate, term)]
        supported_terms = [term for term in term_hits if contains_term(source, term)]
        unsupported_terms = [term for term in term_hits if term not in supported_terms]
        status = "gap" if unsupported_terms else "supported" if supported_terms and best[0] >= 2 else "review" if best[0] >= 3 else "gap"
        result[category].append({"text": candidate, "status": status,
                                 "evidence_ids": [best[1]] if status != "gap" else [],
                                 "matched_terms": supported_terms, "unsupported_terms": unsupported_terms})
        for term in term_hits:
            group = "tools" if term in TOOLS else "ats_keywords"
            if not any(x["text"].casefold() == term.casefold() for x in result[group]):
                result[group].append({"text": term, "status": "supported" if term in supported_terms else "gap",
                                      "evidence_ids": [best[1]] if term in supported_terms and best[1] else []})
        if re.search(r"lead|manag|director|own|mentor|budget|executive|senior", candidate, re.I):
            result["seniority_signals"].append({"text": candidate, "status": status, "evidence_ids": [best[1]] if best[1] else []})
        if re.search(r"healthcare|medical|e-commerce|retail|b2b|b2c|saas|agency|catalog", candidate, re.I):
            result["industry_terminology"].append({"text": candidate, "status": status, "evidence_ids": [best[1]] if best[1] else []})
    return result


def relevant_metric_ids(listing: str, evidence: list[dict]) -> list[str]:
    """Protect proven scale/outcome bullets when the target work makes them useful."""
    metric_rules = (
        (r"\$30 million per month", r"paid|budget|marketing manager|leadership|director"),
        (r"\$200,000 to \$800,000|ROAS from 1\.5", r"e-commerce|ecommerce|growth|revenue|paid"),
        (r"650\+ existing retail|650 B2B", r"b2b|retail|e-commerce|ecommerce|catalog"),
        (r"75\+ Google Ads accounts", r"paid|search|agency|account|sem"),
        (r"\$9 million in revenue", r"revenue|e-commerce|ecommerce|marketing|growth"),
    )
    result = []
    for metric, trigger in metric_rules:
        if re.search(trigger, listing, re.I):
            match = next((item for item in evidence if re.search(metric, item["quote"], re.I)), None)
            if match:
                result.append(match["id"])
    return result


def polish_quote(quote: str) -> str:
    """Apply small grammar edits without changing facts or product names."""
    for old, new in (("Setup ", "Set up "), ("Created a inventory", "Created an inventory"),
                     ("I helped convert", "Helped convert"),
                     ("marketingnvironment", "marketing environment")):
        quote = quote.replace(old, new)
    return quote


def _near_duplicate(left: str, right: str) -> bool:
    """Detect accomplishment bullets that repeat substantially the same claim."""
    left_words, right_words = words(left), words(right)
    smaller = min(len(left_words), len(right_words))
    return bool(smaller and len(left_words & right_words) / smaller >= .6)


def master_identity() -> dict[str, str]:
    lines = [line.strip() for line in master_lines() if line.strip()]
    education = next(_bullet_text(line) for line in lines if "Brigham Young University" in line)
    cert_start = lines.index("CERTIFICATIONS") + 1
    certs = []
    for line in lines[cert_start:]:
        if line.startswith("ADDITIONAL") or not _is_bullet(line):
            break
        certs.append(_bullet_text(line))
    return {
        "name": lines[0],
        "headline": next(line for line in lines if line.startswith("Digital Marketing |")),
        "contact": normalized(next(line for line in lines if "linkedin.com/in/mdavidcall" in line)),
        "summary": lines[lines.index("PROFESSIONAL PROFILE") + 1],
        "education": education,
        "certifications": "Certifications: " + "; ".join(certs),
    }


def master_jobs() -> list[dict[str, str]]:
    return [{"title": job["title"], "company": job["company"], "location": job["location"]}
            for job in parsed_jobs()]


def create_plan(listing_path: Path) -> dict:
    validate_required_sources()
    listing = listing_path.read_text(encoding="utf-8-sig")
    source = source_text()
    evidence = extract_evidence(source)
    meta = listing_metadata(listing, listing_path)
    reqs = requirements(listing, source, evidence)
    target = words(listing)
    mandatory_metrics = relevant_metric_ids(listing, evidence)
    selected = []
    jobs = master_jobs()
    # The required model devotes separate space to selected results and tools.
    # Keep the longer archive conservative so Word-native pagination stays at
    # two pages without shrinking the model typography.
    bullets_per_job = 3 if len(jobs) <= 5 else 2
    for index in range(len(jobs)):
        pool = [item for item in evidence if item["job"] == index]
        concise = [item for item in pool if len(item["quote"].split()) <= 55]
        if len(concise) >= 4:
            pool = concise
        ranked = sorted(pool, key=lambda item: (
            len(words(item["quote"]) & target) + 3 * bool(re.search(r"\$[\d,]+|\b\d+[%+]", item["quote"]))
            - 4 * bool(re.search(r"\b(?:I|my|we|our)\b", item["quote"])),
            ), reverse=True)
        mandatory = [item for item in ranked if item["id"] in mandatory_metrics]
        chosen_items = []
        for item in mandatory + ranked:
            if item in chosen_items:
                continue
            if any(_near_duplicate(item["quote"], picked["quote"]) for picked in chosen_items):
                continue
            chosen_items.append(item)
            if len(chosen_items) == bullets_per_job:
                break
        # Very small source sections may contain only similar bullets. Preserve
        # the page budget even there instead of silently dropping a role.
        if len(chosen_items) < bullets_per_job:
            chosen_items.extend(item for item in ranked if item not in chosen_items)
            chosen_items = chosen_items[:bullets_per_job]
        chosen = [item["id"] for item in chosen_items]
        selected.extend(chosen)
    core_strengths = select_core_strengths(listing, source)
    tools_platforms = select_tools_platforms(listing, source)
    metric_pool = [item for item in evidence if re.search(r"\$[\d,]+|\b\d+(?:\.\d+)?[%+]", item["quote"])]
    ranked_metrics = sorted(metric_pool, key=lambda item: (
        item["id"] in mandatory_metrics,
        len(words(item["quote"]) & target),
    ), reverse=True)
    selected_results = []
    for item in ranked_metrics:
        if item["id"] not in selected_results:
            selected_results.append(item["id"])
        if len(selected_results) == 4:
            break
    return {"version": 3, "job": meta, "listing": str(listing_path.resolve()),
            "listing_sha256": hashlib.sha256(listing_path.read_bytes()).hexdigest(),
            "source_sha256": source_hashes(), "format_model_sha256": formatting_model_hash(),
            "format_model": FORMAT_MODEL.relative_to(ROOT).as_posix(),
            "requirements": reqs, "evidence": evidence,
            "resume": {**master_identity(), "jobs": jobs,
                       "core_strengths": core_strengths, "tools_platforms": tools_platforms,
                       "selected_evidence_ids": selected,
                       "selected_results_ids": selected_results,
                       "relevant_metric_ids": mandatory_metrics},
            "review_notes": ["Review requirement classifications and evidence links before generation.",
                             "All factual content comes from the required master TXT.",
                             "Visual formatting is governed by the required model PDF; no fallback resume or template is allowed."]}


def verify_plan(plan: dict) -> None:
    validate_required_sources()
    if plan.get("version") != 3 or plan.get("source_sha256") != source_hashes():
        raise ValueError("Plan source has changed; rebuild the tailoring plan.")
    if (plan.get("format_model") != FORMAT_MODEL.relative_to(ROOT).as_posix()
            or plan.get("format_model_sha256") != formatting_model_hash()):
        raise ValueError("Required Gecko formatting model has changed; rebuild the tailoring plan.")
    listing_path = Path(plan["listing"])
    if hashlib.sha256(listing_path.read_bytes()).hexdigest() != plan["listing_sha256"]:
        raise ValueError("Listing has changed; rebuild the tailoring plan.")
    current_source = source_text()
    actual = {item["id"]: item for item in extract_evidence(current_source)}
    if plan["requirements"] != requirements(listing_path.read_text(encoding="utf-8-sig"), current_source, list(actual.values())):
        raise ValueError("Requirement classifications differ from the listing; rebuild the plan.")
    for item in plan["evidence"]:
        if actual.get(item["id"]) != item:
            raise ValueError(f"Unsupported or altered evidence: {item['id']}")
    for eid in plan["resume"]["selected_evidence_ids"]:
        if eid not in actual:
            raise ValueError(f"Unknown evidence ID: {eid}")
    for eid in plan["resume"].get("selected_results_ids", []):
        if eid not in actual:
            raise ValueError(f"Unknown selected-result evidence ID: {eid}")
    if plan["resume"]["relevant_metric_ids"] != relevant_metric_ids(listing_path.read_text(encoding="utf-8-sig"), list(actual.values())):
        raise ValueError("Relevant accomplishment anchors differ from the source and listing.")
    source = source_text()
    listing = listing_path.read_text(encoding="utf-8-sig")
    if plan["resume"].get("core_strengths") != select_core_strengths(listing, source):
        raise ValueError("Core Strengths are stale, unsupported, or incorrectly capitalized; rebuild the plan.")
    if plan["resume"].get("tools_platforms") != select_tools_platforms(listing, source):
        raise ValueError("Tools & Platforms are stale, unsupported, or incorrectly capitalized; rebuild the plan.")
    format_issues = formatting_content_issues(
        plan["resume"]["core_strengths"], plan["resume"]["tools_platforms"])
    if format_issues:
        raise ValueError(" ".join(format_issues))
    if any(plan["resume"].get(field) != value for field, value in master_identity().items()):
        raise ValueError("Identity, summary, education, or certifications differ from the current master archive.")
    if plan["resume"].get("jobs") != master_jobs():
        raise ValueError("Job history differs from the current master archive.")


def make_resume(plan: dict, path: Path) -> None:
    normalize_resume_format(plan)
    verify_plan(plan)
    doc = Document()
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Inches(.48)
        section.left_margin = section.right_margin = Inches(.5)
        section.page_width, section.page_height = Inches(8.5), Inches(11)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = MODEL_FONT, Pt(MODEL_BODY_SIZE)
    normal.paragraph_format.line_spacing = 1.15
    normal.paragraph_format.space_after = Pt(0)

    def para(text: str, *, bold=False, center=False, after=0, before=0, color=None, style=None):
        p = doc.add_paragraph(style=style)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(before), Pt(after)
        p.paragraph_format.line_spacing = 1.15
        r = p.add_run(text)
        r.bold = bold
        r.font.name, r.font.size = MODEL_FONT, Pt(MODEL_BODY_SIZE)
        if color:
            r.font.color.rgb = RGBColor(*color)
        return p

    def section(title):
        p = para(title.upper(), before=5, after=2, color=MODEL_OLIVE)
        p.paragraph_format.keep_with_next = True
        border = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        for attr, value in (("val", "single"), ("sz", "6"), ("color", "556B2F")):
            bottom.set(qn("w:" + attr), value)
        border.append(bottom)
        p._p.get_or_add_pPr().append(border)

    para(plan["resume"]["name"], center=True, after=1).runs[0].font.size = Pt(22)
    para(plan["resume"]["headline"], center=True, after=2)
    para(plan["resume"]["contact"], center=True, after=3).runs[0].font.size = Pt(9.5)
    section(SECTIONS[0])
    para(plan["resume"]["summary"], after=2)
    section(SECTIONS[1])
    strengths = plan["resume"]["core_strengths"]
    table = doc.add_table(rows=(len(strengths) + 1) // 2, cols=2)
    table.autofit = False
    table.columns[0].width = table.columns[1].width = Inches(3.75)
    for index, strength in enumerate(strengths):
        cell = table.cell(index // 2, index % 2)
        cell.text = ""
        p = cell.paragraphs[0]
        p.style = doc.styles["List Bullet"]
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.15
        run = p.add_run(strength)
        run.font.name, run.font.size = MODEL_FONT, Pt(MODEL_BODY_SIZE)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = OxmlElement("w:" + edge)
        node.set(qn("w:val"), "none")
        borders.append(node)
    table._tbl.tblPr.append(borders)
    evidence = {item["id"]: item for item in plan["evidence"]}
    results = [evidence[eid] for eid in plan["resume"].get("selected_results_ids", [])]
    if results:
        section(SECTIONS[2])
        for item in results:
            p = para(polish_quote(item["quote"]), style="List Bullet", after=1)
            p.paragraph_format.left_indent = Inches(.18)
    section(SECTIONS[3])
    for index, job in enumerate(plan["resume"]["jobs"]):
        title, company, location = job["title"], job["company"], job["location"]
        selected = [evidence[eid] for eid in plan["resume"]["selected_evidence_ids"] if evidence[eid]["job"] == index]
        if not selected:
            continue
        table = doc.add_table(rows=2, cols=2)
        table.autofit = False
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.columns[0].width, table.columns[1].width = Inches(5.7), Inches(1.8)
        for row in range(2):
            table.cell(row, 0).width, table.cell(row, 1).width = Inches(5.7), Inches(1.8)
        title_paragraph = table.cell(0, 0).paragraphs[0]
        title_paragraph.add_run(title).bold = True
        company_line = f"{company}  {location}" if location else company
        company_paragraph = table.cell(1, 0).paragraphs[0]
        company_paragraph.add_run(company_line).bold = True
        # Keep each job header with its first bullet so a table-backed heading
        # cannot be orphaned at the bottom of a page in Microsoft Word.
        title_paragraph.paragraph_format.keep_with_next = True
        company_paragraph.paragraph_format.keep_with_next = True
        table.cell(0, 1).text = ""  # Required right-side date area.
        table.cell(1, 1).text = ""
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            node = OxmlElement("w:" + edge)
            node.set(qn("w:val"), "none")
            borders.append(node)
        table._tbl.tblPr.append(borders)
        for item_index, item in enumerate(selected):
            p = para(polish_quote(item["quote"]), style="List Bullet", after=1)
            p.paragraph_format.left_indent = Inches(.18)
            # Keep a role's bullets together with its table-backed heading when
            # Word can fit the complete block on one page. This avoids a lone
            # continuation bullet at the top of the following page.
            if item_index < len(selected) - 1:
                p.paragraph_format.keep_with_next = True
    section(SECTIONS[4])
    para(" • ".join(plan["resume"]["tools_platforms"]), after=2)
    section(SECTIONS[5])
    para(plan["resume"]["education"], after=1)
    para(plan["resume"]["certifications"])
    pre_save_issues = document_format_issues(plan, doc)
    if pre_save_issues:
        raise ValueError("Resume formatting validation failed before save: " + " ".join(pre_save_issues))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def inspect_docx(plan: dict, docx_path: Path) -> list[str]:
    issues = []
    try:
        validate_required_sources()
    except FileNotFoundError as exc:
        issues.append(str(exc))
    if plan.get("source_sha256") != source_hashes():
        issues.append("Master archive changed after planning; rebuild the plan and resume.")
    if plan.get("format_model_sha256") != formatting_model_hash():
        issues.append("Formatting model changed after planning; rebuild the plan and resume.")
    doc = Document(docx_path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    evidence = {item["id"]: item for item in plan["evidence"]}
    allowed_ids = set(plan["resume"]["selected_evidence_ids"]) | set(plan["resume"].get("selected_results_ids", []))
    allowed = {polish_quote(evidence[eid]["quote"]) for eid in allowed_ids}
    actual_bullets = [p.text.strip() for p in doc.paragraphs if p.style.name == "List Bullet"]
    expected_experience = [polish_quote(evidence[eid]["quote"]) for eid in plan["resume"]["selected_evidence_ids"]]
    expected_results = [polish_quote(evidence[eid]["quote"]) for eid in plan["resume"].get("selected_results_ids", [])]
    if sorted(actual_bullets) != sorted(expected_experience + expected_results):
        issues.append("Resume bullets differ from the source-backed tailoring plan.")
    for eid in plan["resume"]["relevant_metric_ids"]:
        if polish_quote(evidence[eid]["quote"]) not in actual_bullets:
            issues.append(f"Relevant quantified accomplishment omitted: {eid}")
    fixed = {plan["resume"]["name"], plan["resume"]["headline"], plan["resume"]["summary"],
             plan["resume"]["contact"], " • ".join(plan["resume"]["tools_platforms"]),
             plan["resume"]["education"], plan["resume"]["certifications"]}
    fixed.update(s.upper() for s in SECTIONS)
    if any(p not in fixed and p not in allowed for p in paragraphs):
        issues.append("DOCX contains text outside the approved source-backed plan.")
    issues.extend(document_format_issues(plan, doc))
    if any(node.get(qn("w:val")) != "none" for table in doc.tables for node in table._tbl.tblPr.xpath(".//w:tblBorders/*")):
        issues.append("A job table has visible borders.")
    expected_sections = [s.upper() for s in SECTIONS if s != "Selected Results" or plan["resume"].get("selected_results_ids")]
    if [p for p in paragraphs if p in [s.upper() for s in SECTIONS]] != expected_sections:
        issues.append("Required section order is missing or changed.")
    if not paragraphs[2].endswith("linkedin.com/in/mdavidcall") or "Spanish" in paragraphs[2]:
        issues.append("Header contact format is incorrect.")
    normal = doc.styles["Normal"]
    normal_size = normal.font.size
    normal_spacing = normal.paragraph_format.line_spacing
    if (normal.font.name != MODEL_FONT
            or normal_size is None or abs(normal_size.pt - MODEL_BODY_SIZE) > .01
            or normal_spacing is None or abs(normal_spacing - 1.15) > .01):
        issues.append("Body typography or line spacing differs from the required formatting model.")
    for p in doc.paragraphs[3:]:
        if p.paragraph_format.line_spacing not in (None, 1.15):
            issues.append("A body paragraph has incorrect line spacing.")
            break
        if any(run.font.size is not None and abs(run.font.size.pt - MODEL_BODY_SIZE) > .01
               and p.text not in {plan["resume"]["name"], plan["resume"]["contact"]} for run in p.runs):
            issues.append("A body paragraph has incorrect font size.")
            break
    if len(doc.sections) != 1 or doc.sections[0].page_width != Inches(8.5) or doc.sections[0].page_height != Inches(11):
        issues.append("Page size/layout differs from Gecko rules.")
    if any(getattr(doc.sections[0], edge) < Inches(.4) for edge in ("top_margin", "bottom_margin", "left_margin", "right_margin")):
        issues.append("Page margins are smaller than Gecko's safety margin.")
    if doc.element.body.xpath(".//w:shd"):
        issues.append("Background shading violates the white-page layout.")
    # Fixed identity, summary, tools, education, and certification text is
    # source-governed rather than tailored from the listing. Excluding it
    # prevents legitimate repeated product names (for example, Google Ads,
    # Microsoft Ads, and Meta Ads) from tripping the stuffing safeguard.
    stuffing_text = " ".join(paragraph for paragraph in paragraphs if paragraph not in fixed)
    for token, count in Counter(re.findall(r"\b[A-Za-z][A-Za-z0-9+]{2,}\b", stuffing_text.casefold())).items():
        if token not in STOP and count >= 18 and token in words(Path(plan["listing"]).read_text(encoding="utf-8-sig")):
            issues.append(f"Possible keyword stuffing: {token} appears {count} times.")
    return issues


def native_qa(plan: dict, docx_path: Path, scratch: Path) -> dict:
    scratch.mkdir(parents=True, exist_ok=True)
    pdf = scratch / "word-export.pdf"
    status = scratch / "validation-status.json"
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
           "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/validate_word_native.ps1"),
           "-DocxPath", str(docx_path), "-PdfPath", str(pdf), "-ResultPath", str(status)]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                            creationflags=windows_creationflags())
    issues = inspect_docx(plan, docx_path)
    native = json.loads(status.read_text(encoding="utf-8-sig")) if status.exists() else {}
    if result.returncode or native.get("status") != "native-valid" or native.get("word_pages") != 2 or native.get("pdf_pages") != 2:
        issues.append("Native Word pagination did not confirm exactly two pages. " + (result.stderr.strip() or result.stdout.strip())[-500:])
    if pdf.exists():
        with fitz.open(pdf) as rendered:
            if len(rendered) == 2:
                for number, page in enumerate(rendered, 1):
                    blocks = [fitz.Rect(b[:4]) for b in page.get_text("blocks") if normalized(str(b[4]))]
                    if not blocks or max(block.y1 for block in blocks) > page.rect.height - 18:
                        issues.append(f"Page {number} has possible bottom overflow or no extractable text.")
                    if any(b.x0 < 12 or b.x1 > page.rect.width - 12 for b in blocks):
                        issues.append(f"Page {number} has possible horizontal overflow.")
    reqs = plan["requirements"]
    weaknesses = [r["text"] for group in ("required_skills", "preferred_skills", "responsibilities") for r in reqs[group] if r["status"] != "supported"]
    report = {"status": "pass" if not issues else "fail", "word_pages": native.get("word_pages"),
              "pdf_pages": native.get("pdf_pages"), "issues": issues, "remaining_weaknesses": weaknesses,
              "native_validation": str(status), "word_output": result.stdout.strip()}
    (scratch / "v2-qa.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="Extract job requirements and source-backed tailoring plan")
    p.add_argument("listing", type=Path)
    p = sub.add_parser("generate", help="Generate DOCX from an existing plan")
    p.add_argument("plan", type=Path)
    p = sub.add_parser("qa", help="Check DOCX and run authoritative Word pagination")
    p.add_argument("plan", type=Path)
    args = parser.parse_args()
    if args.command == "plan":
        plan = create_plan(args.listing.resolve())
        name = f"{plan['job']['safe_company']}+{plan['job']['job_number']}"
        scratch = ROOT / "scratch" / name
        scratch.mkdir(parents=True, exist_ok=True)
        path = scratch / "tailoring-plan.json"
        path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        print(path)
        return 0
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    verify_plan(plan)
    name = f"{plan['job']['safe_company']}+{plan['job']['job_number']}"
    output = ROOT / "output/resumes" / resume_filename(
        plan["job"]["company"], plan["job"]["title"], plan["job"]["job_number"])
    scratch = ROOT / "scratch" / name
    if args.command == "generate":
        scratch.mkdir(parents=True, exist_ok=True)
        candidate = scratch / "manual-candidate.docx"
        make_resume(plan, candidate)
        report = native_qa(plan, candidate, scratch)
        if report["status"] == "pass":
            output.parent.mkdir(parents=True, exist_ok=True)
            os.replace(candidate, output)
        print(json.dumps({"docx": str(output) if report["status"] == "pass" else None,
                          "candidate": str(candidate), **report}, indent=2))
        return 0 if report["status"] == "pass" else 1
    if not output.exists():
        old_output = ROOT / "output/resumes" / f"Dave-Call+{name}.docx"
        if old_output.exists():
            output = old_output
    if not output.exists():
        raise FileNotFoundError(output)
    report = native_qa(plan, output, scratch)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
