"""Context-aware, evidence-confidence-aware Gecko Match Score."""

from __future__ import annotations

import re
from dataclasses import dataclass

from models import JobListing


WEIGHTS = {
    "role/domain relevance": 15,
    "responsibilities/required skills": 15,
    "paid media/performance marketing": 14,
    "analytics/measurement": 11,
    "e-commerce/SEO/transferable digital marketing": 10,
    "martech/automation/AI": 10,
    "years/seniority/scope": 8,
    "leadership/management": 10,
    "location/work arrangement": 4,
    "education/certifications": 3,
}

LEVEL_FACTORS = {
    "direct match": 1.0,
    "related/transferable match": .75,
    "unknown because source text is incomplete": .50,
    "weak match": .30,
    "true mismatch": 0.0,
}

WORD = r"(?<![a-z0-9]){}(?![a-z0-9])"
UTAH_PLACES = (
    "utah", "salt lake", "utah county", "lehi", "draper", "provo", "orem",
    "midvale", "riverton", "sandy", "murray", "south jordan", "west jordan",
    "cottonwood", "layton", "ogden", "cedar pass", "bonnie",
)

REMOTE_US_ELIGIBILITY = (
    "worldwide", "anywhere", "global", "usa", "united states", "u.s.",
    "north america", "northern america", "americas", "est", "cst", "mst", "pst",
)


def _remote_location_eligibility(location: str) -> str:
    """Return allowed, restricted, or unspecified for a US-based remote candidate."""
    value = location.casefold().strip()
    if not value or value == "remote":
        return "unspecified"
    if _matches(value, REMOTE_US_ELIGIBILITY):
        return "allowed"
    return "restricted"


@dataclass
class ScoreResult:
    total: int
    dimensions: dict[str, int]
    evidence_levels: dict[str, str]
    strengths: list[str]
    weaknesses: list[str]
    confidence: int
    provisional: bool


def _has_phrase(text: str, phrase: str) -> bool:
    """Match complete words while tolerating spaces, hyphens, and underscores."""
    tokens = re.findall(r"[a-z0-9]+", phrase.lower())
    if not tokens:
        return False
    pattern = r"[\s_-]+".join(re.escape(token) for token in tokens)
    return bool(re.search(WORD.format(pattern), text.lower()))


def _matches(text: str, phrases: tuple[str, ...] | list[str]) -> list[str]:
    return [phrase for phrase in phrases if _has_phrase(text, phrase)]


def _abbreviated(job: JobListing) -> bool:
    text = job.description.strip()
    return job.source.lower() == "adzuna" and (len(text) <= 600 or text.endswith(("…", "...")))


def _level_for_absence(job: JobListing) -> str:
    return "unknown because source text is incomplete" if _abbreviated(job) else "weak match"


def _context_contains(text: str, term: str, context: tuple[str, ...], window: int = 100) -> bool:
    """Require an ambiguous acronym to occur close to disambiguating context."""
    low = text.lower()
    for match in re.finditer(WORD.format(re.escape(term.lower())), low):
        nearby = low[max(0, match.start() - window):match.end() + window]
        if any(_has_phrase(nearby, value) for value in context):
            return True
    return False


def _paid_signals(text: str) -> list[str]:
    signals = _matches(text, (
        "paid search", "paid social", "pay per click", "google ads", "google adwords",
        "microsoft ads", "bing ads", "meta ads", "facebook ads", "performance max",
        "display advertising", "media buying", "shopping ads", "youtube ads",
        "mobile user acquisition", "mobile UA",
    ))
    if _context_contains(text, "ppc", ("advertising", "marketing", "search", "campaign", "media", "ads", "agency")):
        signals.append("PPC")
    if _context_contains(text, "sem", ("advertising", "marketing", "search", "campaign", "media", "ads", "agency")):
        signals.append("SEM")
    return list(dict.fromkeys(signals))


def _analytics_signals(text: str) -> list[str]:
    signals = _matches(text, (
        "marketing analytics", "digital analytics", "google analytics", "GA4", "adobe analytics",
        "tableau", "power BI", "looker", "databricks", "funnel.io", "SQL", "python",
        "attribution", "lifetime value", "LTV", "regression", "A/B testing",
        "conversion rate optimization", "data visualization", "business intelligence",
    ))
    if _context_contains(text, "CRO", ("conversion", "optimization", "landing page", "testing")):
        signals.append("CRO")
    if _context_contains(text, "GTM", ("google tag manager", "tagging", "analytics", "tracking")):
        signals.append("Google Tag Manager")
    return list(dict.fromkeys(signals))


def _transferable_signals(text: str) -> tuple[list[str], list[str]]:
    direct = _matches(text, (
        "e-commerce", "ecommerce", "Shopify", "Magento", "Amazon", "SEO",
        "technical SEO", "on-page SEO", "search engine optimization",
    ))
    related = _matches(text, (
        "growth marketing", "demand generation", "customer acquisition", "user acquisition",
        "acquisition strategy", "performance marketing", "digital marketing", "full-funnel",
        "conversion", "marketing strategy",
    ))
    return list(dict.fromkeys(direct)), list(dict.fromkeys(related))


def _martech_signals(text: str) -> tuple[list[str], list[str]]:
    direct = _matches(text, (
        "HubSpot", "Salesforce", "Marketo", "Pardot", "Klaviyo", "WordPress",
        "marketing automation", "automation", "automated", "JavaScript", "Python", "SQL",
        "custom script", "scripts", "ChatGPT", "artificial intelligence", "machine learning",
        "AI-native", "AI marketing",
    ))
    if _context_contains(text, "AI", ("automation", "artificial intelligence", "machine learning", "model", "native"), 60):
        direct.append("AI")
    related = _matches(text, ("CRM", "marketing platform", "technology stack", "integration", "workflow"))
    return list(dict.fromkeys(direct)), list(dict.fromkeys(related))


def _wrong_domain(title: str, description: str) -> bool:
    combined = f"{title} {description}".lower()
    wrong = _matches(combined, (
        "quality regulatory", "regulatory compliance", "production and process control",
        "supplier quality", "clinical", "surgery", "manufacturing quality",
    ))
    marketing = _matches(combined, (
        "marketing", "advertising", "paid search", "paid social", "digital", "media",
        "customer acquisition", "demand generation", "e-commerce", "SEO",
    ))
    return bool(wrong and not marketing)


def _role_level(job: JobListing) -> tuple[str, list[str]]:
    title = job.title.lower()
    if _wrong_domain(job.title, job.description):
        return "true mismatch", ["Title/domain is outside digital marketing."]
    direct = _matches(title, (
        "paid search manager", "paid search specialist", "PPC manager", "SEM manager",
        "digital marketing manager", "performance marketing manager", "marketing analytics manager",
        "digital marketing analyst", "growth marketing manager", "e-commerce marketing manager",
        "director of performance marketing", "senior paid search strategist",
    ))
    if direct:
        return "direct match", [f"Target role family: {direct[0]}."]
    related = _matches(title, (
        "paid social", "performance marketing", "growth marketing", "marketing analytics",
        "digital marketing", "paid search", "e-commerce", "ecommerce", "SEO",
        "demand generation", "acquisition marketing", "growth manager",
    ))
    if related:
        return "related/transferable match", [f"Related role family: {related[0]}."]
    if _matches(title, ("product marketing", "marketing manager", "marketing director", "strategic growth")):
        return "weak match", ["Adjacent marketing role family."]
    return "true mismatch", ["Title does not indicate a target digital-marketing role."]


def _required_level(job: JobListing, candidate_text: str) -> tuple[str, list[str], list[str]]:
    clauses = [sentence for sentence in re.split(r"[.;\n]", job.description)
               if re.search(r"\b(required|must have|minimum qualifications?|requirement)\b", sentence, re.I)]
    if not clauses:
        level = _level_for_absence(job)
        return level, [], ["No complete requirements section is available."]
    requirement_text = " ".join(clauses).lower()
    supported_families = []
    for family, signals in (
        ("paid media", _paid_signals(requirement_text)),
        ("analytics", _analytics_signals(requirement_text)),
        ("e-commerce/SEO", sum(_transferable_signals(requirement_text), [])),
        ("martech/automation/AI", sum(_martech_signals(requirement_text), [])),
    ):
        if signals and any(_has_phrase(candidate_text, signal) for signal in signals):
            supported_families.append(family)
    unsupported = []
    for term in ("MBA", "PhD", "medical license", "CPA", "security clearance"):
        if _has_phrase(requirement_text, term) and not _has_phrase(candidate_text, term):
            unsupported.append(term)
    if unsupported:
        return "true mismatch", supported_families, ["Mandatory unsupported qualification: " + ", ".join(unsupported) + "."]
    if supported_families:
        return "direct match", supported_families, []
    return "related/transferable match", [], ["Requirements are present but contain few recognized skill-family signals."]


def _confidence(job: JobListing) -> int:
    length = len(job.description.strip())
    if length <= 600:
        score = 35
    elif length <= 1000:
        score = 50
    elif length <= 2000:
        score = 70
    else:
        score = 90
    text = job.description.lower()
    score += 3 if re.search(r"\b(required|must have|minimum qualifications?)\b", text) else 0
    score += 3 if re.search(r"\b\d{1,2}\+?\s+years?\b", text) else 0
    score += 2 if re.search(r"\b(bachelor|degree|certification)\b", text) else 0
    score += 2 if job.employment_type else 0
    return min(100, score)


def _add_dimension(dimensions: dict[str, int], levels: dict[str, str], name: str, level: str) -> None:
    levels[name] = level
    dimensions[name] = round(WEIGHTS[name] * LEVEL_FACTORS[level])


def score_job(job: JobListing, preferences: dict, resume_text: str = "") -> ScoreResult:
    """Estimate candidate fit separately from the completeness of source evidence."""
    candidate = preferences["candidate"]
    candidate_values = " ".join(
        str(item) for value in candidate.values() for item in (value if isinstance(value, list) else [value])
    )
    candidate_text = f"{resume_text} {candidate_values}".lower()
    text = f"{job.title}\n{job.description}".lower()
    dimensions: dict[str, int] = {}
    levels: dict[str, str] = {}
    strengths: list[str] = []
    weaknesses: list[str] = []

    role_level, role_notes = _role_level(job)
    _add_dimension(dimensions, levels, "role/domain relevance", role_level)
    (strengths if role_level != "true mismatch" else weaknesses).extend(role_notes)

    required_level, supported, required_notes = _required_level(job, candidate_text)
    _add_dimension(dimensions, levels, "responsibilities/required skills", required_level)
    if supported:
        strengths.append("Supported requirement families: " + ", ".join(supported) + ".")
    weaknesses.extend(required_notes)

    paid = _paid_signals(text)
    performance = _matches(text, ("performance marketing", "growth marketing", "demand generation", "acquisition"))
    if paid:
        paid_level = "direct match"
        strengths.append("Paid-media evidence: " + ", ".join(paid[:5]) + ".")
    elif performance:
        paid_level = "related/transferable match"
        strengths.append("Transferable performance-marketing evidence: " + ", ".join(performance[:3]) + ".")
    elif role_level == "true mismatch":
        paid_level = "true mismatch"
    else:
        paid_level = _level_for_absence(job)
        weaknesses.append("Paid-media details are not present in the available source text.")
    _add_dimension(dimensions, levels, "paid media/performance marketing", paid_level)

    analytics = _analytics_signals(text)
    analytics_related = _matches(text, ("data-driven", "reporting", "metrics", "measurement", "optimize", "analytical"))
    if analytics:
        analytics_level = "direct match"
        strengths.append("Analytics evidence: " + ", ".join(analytics[:5]) + ".")
    elif analytics_related:
        analytics_level = "related/transferable match"
        strengths.append("Related measurement evidence: " + ", ".join(analytics_related[:3]) + ".")
    elif role_level == "true mismatch":
        analytics_level = "true mismatch"
    else:
        analytics_level = _level_for_absence(job)
        weaknesses.append("Analytics details are not present in the available source text.")
    _add_dimension(dimensions, levels, "analytics/measurement", analytics_level)

    digital_direct, digital_related = _transferable_signals(text)
    if digital_direct:
        digital_level = "direct match"
        strengths.append("E-commerce/SEO evidence: " + ", ".join(digital_direct[:5]) + ".")
    elif digital_related:
        digital_level = "related/transferable match"
        strengths.append("Transferable digital-marketing evidence: " + ", ".join(digital_related[:4]) + ".")
    elif role_level == "true mismatch":
        digital_level = "true mismatch"
    else:
        digital_level = _level_for_absence(job)
    _add_dimension(dimensions, levels, "e-commerce/SEO/transferable digital marketing", digital_level)

    martech_direct, martech_related = _martech_signals(text)
    if martech_direct:
        martech_level = "direct match"
        strengths.append("Martech/automation/AI evidence: " + ", ".join(martech_direct[:5]) + ".")
    elif martech_related:
        martech_level = "related/transferable match"
        strengths.append("Related marketing-technology evidence: " + ", ".join(martech_related[:4]) + ".")
    elif role_level == "true mismatch":
        martech_level = "true mismatch"
    else:
        martech_level = _level_for_absence(job)
    _add_dimension(dimensions, levels, "martech/automation/AI", martech_level)

    junior = _matches(job.title, ("intern", "internship", "entry level", "junior"))
    years = [int(value) for value in re.findall(r"\b(\d{1,2})\+?\s+years?\b", text)]
    requested_years = max(years, default=0)
    senior_title = _matches(job.title, ("senior", "sr", "manager", "director", "head", "lead"))
    if junior:
        seniority_level = "true mismatch"
        weaknesses.append("Role is explicitly junior, entry-level, or an internship.")
    elif requested_years and candidate.get("years_experience", 0) >= requested_years:
        seniority_level = "direct match"
        strengths.append(f"14+ years meets the stated {requested_years}-year requirement.")
    elif requested_years:
        seniority_level = "weak match"
        weaknesses.append(f"Detected experience requirement exceeds the configured {candidate.get('years_experience', 0)} years.")
    elif senior_title:
        seniority_level = "direct match"
        strengths.append("Senior/managerial scope aligns with 14+ years of experience.")
    else:
        seniority_level = _level_for_absence(job)
    _add_dimension(dimensions, levels, "years/seniority/scope", seniority_level)

    leadership = _matches(text, ("manager", "director", "head", "leadership", "lead a team", "manage a team", "team management", "mentor", "supervise"))
    individual_contributor = _matches(text, ("individual contributor", "specialist", "analyst", "strategist"))
    if leadership:
        leadership_level = "direct match"
        strengths.append("Leadership requirement aligns with verified department and team management.")
    elif individual_contributor:
        leadership_level = "related/transferable match"
    else:
        leadership_level = _level_for_absence(job)
    _add_dimension(dimensions, levels, "leadership/management", leadership_level)

    place = f"{job.work_arrangement} {job.location}".lower()
    employment = job.employment_type.lower().replace("_", "-")
    remote_eligibility = (
        _remote_location_eligibility(job.location)
        if job.work_arrangement == "remote" else "unspecified"
    )
    preferred_place = bool(_matches(place, ("remote",) + UTAH_PLACES))
    if remote_eligibility == "restricted":
        preferred_place = False
    incompatible_place = bool(
        (job.work_arrangement == "remote" and remote_eligibility == "restricted")
        or (job.location and not preferred_place and job.work_arrangement != "remote")
    )
    contract = bool(_matches(employment, ("contract", "temporary", "part-time", "part time", "freelance")))
    if contract:
        location_level = "true mismatch"
        weaknesses.append("Employment type conflicts with the full-time preference.")
    elif preferred_place and _matches(employment, ("full-time", "full time", "permanent")):
        location_level = "direct match"
        strengths.append(f"Preferred location/work arrangement: {job.location or job.work_arrangement}; {employment}.")
    elif preferred_place:
        location_level = "related/transferable match"
        strengths.append(f"Preferred location/work arrangement: {job.location or job.work_arrangement}.")
    elif incompatible_place:
        location_level = "true mismatch"
        weaknesses.append(
            "Remote eligibility appears to exclude the candidate's US location."
            if job.work_arrangement == "remote"
            else "Location/work arrangement is outside the configured preference."
        )
    else:
        location_level = _level_for_absence(job)
    _add_dimension(dimensions, levels, "location/work arrangement", location_level)

    education = _matches(text, ("bachelor", "bachelor's degree", "degree", "google ads certification", "google analytics certification"))
    unsupported_education = _matches(text, ("MBA required", "PhD required"))
    if unsupported_education:
        education_level = "true mismatch"
        weaknesses.append("Listing states an unsupported mandatory education requirement.")
    elif education:
        education_level = "direct match"
        strengths.append("Verified degree/certifications align with the education signals.")
    else:
        education_level = _level_for_absence(job)
    _add_dimension(dimensions, levels, "education/certifications", education_level)

    confidence = _confidence(job)
    provisional = sum(dimensions.values()) >= 80 and (_abbreviated(job) or confidence < 65)
    if provisional:
        weaknesses.append("80+ provisional — full description recommended.")
    return ScoreResult(
        total=min(100, sum(dimensions.values())), dimensions=dimensions,
        evidence_levels=levels, strengths=strengths, weaknesses=weaknesses,
        confidence=confidence, provisional=provisional,
    )
