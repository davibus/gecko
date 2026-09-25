"""Generate the second requested Scout batch with the established Gecko workflow.

Usage: python scripts/generate_requested_scout_batch_20260924b.py <scout-id>
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import generate_requested_scout_batch as gecko


# Each fit assessment was reviewed against the current master resume and the
# available Scout excerpt. The shared prepare() function re-reads the master
# for every generation and report, and validates in Microsoft Word.
JOBS = {
    264: ("social", 60, ["Dedicated ownership of Meta as the primary customer acquisition channel is not established.", "Meal subscription acquisition and creative production are not documented."], "Confirm the full Tovala listing and the expected depth of Meta account ownership."),
    84: ("performance", 73, ["Direct ownership of Cozy Earth's brand creative and merchandising programs is not documented.", "The short excerpt omits full channel, budget, and team requirements."], "Lead with paid search, paid social, ecommerce, reporting, and budget decisions."),
    154: ("paid", 82, ["The recruiting excerpt does not show the client's industry, account scale, or full requirements.", "Confirm the opening and application destination with Huzzle."], "Lead with Google Ads, agency accounts, ROAS improvement, testing, and client strategy."),
    276: ("content", 32, ["Despite the analytics title, the excerpt asks for end-to-end B2B SEO/GEO strategy; the master shows SEO collaboration rather than organic-search ownership.", "Topic authority, semantic SEO, and generative-search program leadership are unsupported."], "Confirm whether the actual role is marketing analytics or an SEO/GEO strategist contract."),
    77: ("digital", 58, ["Organic-channel ownership and construction-products industry experience are not established.", "The short Scout excerpt omits most requirements."], "Emphasize B2B distributor marketing, paid media, website collaboration, and measurement."),
    103: ("social", 49, ["The excerpt describes paid social performance media despite the Paid Search Manager title.", "Dedicated social-platform leadership and the full client requirements are not documented."], "Confirm the real job title and channel mix before applying."),
    545: ("social", 47, ["A dedicated B2B paid-social growth engine, server-side signals, and pipeline attribution are not documented.", "The excerpt omits work-location and full platform requirements."], "This appears related to Brex Scout ID 779; confirm one current posting and work location."),
    560: ("growth", 45, ["Full ownership of B2B demand-generation pipeline, GTM programs, and sales-cycle acceleration is not established.", "CRM and marketing automation requirements are unavailable in the excerpt."], "Audiohook's role emphasizes qualified pipeline; present channel acquisition as transferable experience."),
    140: ("paid", 78, ["End-to-end SEO program ownership is not documented.", "The excerpt does not specify full agency, management, or technical requirements."], "Lead with agency paid search and client strategy; describe SEO as collaboration."),
    355: ("growth", 60, ["Website product ownership and growth experimentation depth are unclear in the excerpt.", "Dedicated SaaS lifecycle or CRM-led growth is not documented."], "Clarify the website ownership, employment model, and client assignment."),
    167: ("ecommerce", 64, ["Healthcare and medical-supplies ecommerce experience is not documented.", "The short excerpt omits channel, platform, and operational scope."], "Lead with eight-person ecommerce leadership, B2B/B2C expansion, SEO/SEM collaboration, and acquisition."),
    544: ("ecommerce", 68, ["Pattern's marketplace-specific growth systems and full-funnel campaign ownership are not fully documented.", "The short excerpt omits the exact role scope and platform requirements."], "Emphasize ecommerce growth, Amazon advertising, Google/Meta media, and forecasting."),
    17: ("digital", 60, ["Outdoor-sports brand and product-marketing experience is not documented.", "The Adzuna excerpt contains company background but few role requirements."], "Confirm Nordica's full digital-channel scope before applying."),
    87: ("digital", 25, ["Scout's Digital Marketing Manager title conflicts with its excerpt for a hybrid Portfolio Marketing Manager.", "Portfolio marketing, roofing experience, and CRM ownership are not established."], "Verify the employer's actual title and current opening before applying."),
    638: ("growth", 30, ["Qualified B2B pipeline and integrated demand-generation ownership are not documented.", "The excerpt says Remote - TX, while the master lists Utah; eligibility is unclear."], "Confirm Texas residency eligibility and the full B2B demand-generation requirements."),
    798: ("paid", 77, ["SA360 and direct B2B enterprise specialization are not documented.", "The official role is an individual-contributor Manager position requiring far less tenure than the master shows."], "Official Wpromote posting: https://jobs.lever.co/wpromote/af0f35a1-d0e7-42bb-a90d-38042d803f7d . Clarify seniority fit."),
    576: ("digital", 58, ["Power BI, SMS program ownership, and full brand/creative leadership are not documented.", "The excerpt omits employer and industry context behind the recruiter listing."], "Emphasize analytics, paid channels, teams, and cross-functional planning; verify the underlying employer."),
    612: ("paid", 82, ["SA360 and dedicated B2B SaaS client experience are not documented.", "The official Manager role lists a much shorter experience range than the master."], "Official Wpromote posting: https://jobs.lever.co/wpromote/af0f35a1-d0e7-42bb-a90d-38042d803f7d . This may be the same opening as Scout ID 798."),
    346: ("growth", 18, ["The excerpt specifies Central and Eastern Europe remote location, while the master lists Utah.", "Cloud-technology demand generation and SaaS pipeline ownership are not documented."], "Confirm US eligibility; location may rule out this opening."),
    546: ("growth", 55, ["SaaS demand-generation and marketing-sourced pipeline ownership are not established.", "The excerpt does not show complete platform or leadership requirements."], "This appears related to Vasion Scout ID 328; confirm one current opening."),
    328: ("growth", 55, ["SaaS demand-generation and marketing-sourced pipeline ownership are not established.", "The excerpt does not show complete platform or leadership requirements."], "This appears related to Vasion Scout ID 546; confirm one current opening."),
    244: ("performance", 62, ["Dedicated B2B SaaS pipeline programs and CRM attribution are not documented.", "The recruiter excerpt omits complete client and platform requirements."], "Lead with paid-media scale, testing, attribution, and client strategy; verify the client."),
    673: ("ecommerce", 61, ["Drink or supplement DTC category experience and full ecommerce revenue ownership are not documented.", "The excerpt omits the full operating model and channel requirements."], "Emphasize ecommerce leadership, ROAS improvement, and acquisition measurement."),
    815: ("ecommerce", 68, ["Pattern's marketplace-specific growth systems and full-funnel campaign ownership are not fully documented.", "The excerpt omits the exact role scope and platform requirements."], "This appears related to Pattern Scout ID 544; confirm one current opening."),
    814: ("growth", 54, ["Ownership of product-page conversion, referral-led traffic, and website experimentation is not fully documented.", "Health and wellness product-category experience is absent."], "This appears related to Unicity Scout ID 547; emphasize verified CRO and ecommerce work."),
    258: ("growth", 61, ["Healthcare staffing growth programs and full lifecycle ownership are not documented.", "The short excerpt omits complete platform and responsibility requirements."], "Emphasize analytics-driven acquisition, channel testing, and clear stakeholder recommendations."),
    547: ("growth", 54, ["Ownership of product-page conversion, referral-led traffic, and website experimentation is not fully documented.", "Health and wellness product-category experience is absent."], "This appears related to Unicity Scout ID 814; confirm one current opening."),
    356: ("growth", 63, ["Founder-facing revenue ownership and any required CRM/lifecycle programs are not documented.", "The excerpt omits business model and full requirements."], "Emphasize hands-on acquisition, budget ownership, and reporting; clarify the CEO partnership scope."),
    351: ("growth", 60, ["Dedicated SaaS lifecycle or CRM-led growth programs are not documented.", "The recruiter excerpt omits the client's industry and detailed requirements."], "Clarify the end client and lead with cross-channel acquisition and experimentation."),
    242: ("performance", 68, ["The client industry and full channel mix are unavailable in the excerpt.", "Dedicated B2B pipeline or lifecycle-platform ownership is not documented."], "Lead with paid-media scale, multi-channel optimization, and ROAS improvement."),
    330: ("growth", 35, ["This is insurance field marketing and relationship-driven in-market pipeline ownership, which the master does not document.", "The Scout title and excerpt describe different emphasis; full requirements are unavailable."], "Confirm the role's insurance segment, territory, and event/partner responsibilities."),
    620: ("social", 52, ["LinkedIn and Reddit ad-platform experience, CRM-linked audience architecture, and B2B pipeline attribution are not documented.", "The official posting asks for AI workflow skills that are not established in the master."], "Official Canopy posting: https://job-boards.greenhouse.io/canopytax/jobs/4374505009 . It lists a Monday/Wednesday/Friday hybrid schedule in Draper."),
}


def prepare(scout_id: int) -> dict:
    if scout_id not in JOBS:
        raise ValueError(f"Scout ID {scout_id} is not in this batch")
    gecko.JOBS[scout_id] = JOBS[scout_id]
    result = gecko.prepare(scout_id)
    # The first batch's shell-created Unicode heading can render incorrectly
    # under the Windows console encoding. Keep this heading plain ASCII.
    report = Path(result["report"])
    body = report.read_text(encoding="utf-8")
    report.write_text(f"# {result['company']} - Scout ID {scout_id}" + body[body.index("\n"):], encoding="utf-8")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit("Usage: python scripts/generate_requested_scout_batch_20260924b.py <scout-id>")
    print(json.dumps(prepare(int(sys.argv[1])), indent=2))
