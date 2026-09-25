"""Fast title-family filtering before Gecko match scoring."""

from __future__ import annotations

import re


_SPACE = re.compile(r"[^a-z0-9+#.]+")


def _title_text(title: str) -> str:
    return " ".join(_SPACE.sub(" ", title.casefold()).split())


# These phrases identify the role families Dave actually wants to review.  The
# scoring model remains authoritative for fit once a title passes this gate.
DIRECT_MARKETING_PHRASES = (
    "performance marketing", "paid search", "paid media", "ppc", "sem",
    "search marketing", "digital marketing", "growth marketing",
    "marketing analytics", "marketing analyst", "marketing data",
    "ecommerce marketing", "e commerce marketing", "demand generation",
    "acquisition marketing", "digital acquisition", "media buying",
    "marketing operations", "marketing automation", "lifecycle marketing",
    "retention marketing", "seo manager", "seo strategist",
    "ecommerce manager", "e commerce manager", "content marketing",
    "email marketing", "social media marketing", "customer marketing",
    "client marketing", "marketing account", "account marketing",
)

SENIORITY_TERMS = (
    "manager", "director", "head", "vice president", "vp", "senior", "sr",
    "lead", "strategist", "principal",
)

MARKETING_TERMS = (
    "marketing", "paid media", "paid search", "ppc", "sem", "seo",
    "demand generation", "digital acquisition", "media buyer",
)

UNRELATED_PATTERNS = (
    r"\bsoftware (?:engineer|engineering|developer|development)\b",
    r"\b(?:front ?end|back ?end|full ?stack) (?:engineer|developer)\b",
    r"\b(?:devops|site reliability|sre|platform engineer)\b",
    r"\b(?:quality assurance|qa engineer|qa analyst|software tester)\b",
    r"\b(?:it support|help ?desk|desktop support|systems administrator)\b",
    r"\b(?:ai|artificial intelligence|machine learning) engineer\b",
    r"\b(?:\.net|dotnet|react|rails|ruby on rails) (?:engineer|developer)\b",
    r"\bcustomer (?:service|support|success representative)\b",
    r"\b(?:administrative|executive|virtual) assistant\b",
    r"\b(?:account executive|sales representative|sales development representative|business development representative|sdr|bdr)\b",
    r"\b(?:copywriter|content writer|technical writer|staff writer|editor)\b",
)

# These titles produced false positives when a provider matched only a broad
# keyword such as "manager" or "production". Explicit marketing phrases still
# take precedence (for example, "Digital Marketing Project Manager").
GENERIC_MANAGER_PATTERNS = (
    r"\b(?:(?:assistant|asst\.?) )?production manager\b",
    r"\bmedia production specialist\b",
    r"\b(?:senior |sr )?contracts? manager\b",
    r"\b(?:senior |sr )?project manager\b",
    r"\b(?:senior |sr )?program manager\b",
    r"\bfield office manager\b",
)


def role_filter_reason(title: str) -> tuple[bool, str]:
    """Return whether a title belongs in the scoring pipeline and why."""
    value = _title_text(title or "")
    if not value:
        return False, "missing title"

    if "spanish" in value and "fluent" in value:
        return False, "fluent Spanish required in title"

    if "data scientist" in value and "marketing analytics" not in value:
        return False, "non-marketing data science"

    for pattern in UNRELATED_PATTERNS:
        if re.search(pattern, value):
            return False, "unrelated role family"

    if any(phrase in value for phrase in DIRECT_MARKETING_PHRASES):
        return True, "target digital/performance marketing family"

    for pattern in GENERIC_MANAGER_PATTERNS:
        if re.search(pattern, value):
            return False, "generic non-marketing manager/production role"

    has_marketing = any(term in value for term in MARKETING_TERMS)
    has_seniority = any(re.search(rf"\b{re.escape(term)}\b", value) for term in SENIORITY_TERMS)
    if has_marketing and has_seniority:
        return True, "senior marketing role"

    return False, "outside target role families"


def is_relevant_role(title: str) -> bool:
    return role_filter_reason(title)[0]
