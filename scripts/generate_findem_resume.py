"""Build Scout 702's resume from content verified against the current master DOCX."""

from pathlib import Path

import docx
from docx.shared import Inches, RGBColor

from generate_wpromote_resume import build_resume as build_layout
from generate_wpromote_resume import set_labeled, set_plain
from generate_vitality_medical_resume import NAVY
from gecko_v2 import master_identity, master_jobs, source_hashes

ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "ae77d4a7-f6dc-4efc-a4c3-1a059ecece35"
SCRATCH = ROOT / "scratch" / f"Findem+{JOB_KEY}"
OUTPUT = ROOT / "output" / "resumes" / f"Dave-Call+Findem+{JOB_KEY}.docx"


def build_resume(path: Path = OUTPUT):
    # Existing generator supplies layout only; replace every content paragraph below.
    identity = master_identity()
    jobs = master_jobs()
    build_layout(path, scratch_dir=SCRATCH)
    doc = docx.Document(path)
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Inches(.45)
    p = doc.paragraphs
    set_plain(p[0], identity["name"], size=19, bold=True, color=NAVY)
    set_plain(p[1], "DIGITAL MARKETING MANAGER | PAID MEDIA & CAMPAIGN EXECUTION",
              size=11.5, bold=True, color=RGBColor(40, 70, 110))
    set_plain(p[2], identity["contact"], size=9.5)
    set_plain(p[3], "PROFESSIONAL SUMMARY", bold=True, color=NAVY)
    set_plain(p[4],
              "Hands-on digital marketer with 14+ years across paid search, ecommerce, and multi-channel "
              "campaigns. Experienced in campaign builds, daily optimization, budget pacing, conversion tracking, "
              "testing, and client reporting. Managed 75+ Google Ads accounts with more than $276K in monthly "
              "spend and up to $30 million per month in paid media with a four-person team. Combines Google and "
              "Meta execution with GA4, reporting automation, and repeatable quality checks.")
    set_plain(p[5], "CORE COMPETENCIES & TECHNICAL SKILLS", bold=True, color=NAVY)
    skills = {
        6: ("Paid Media Platforms: ", "Google Ads, Microsoft Ads, Meta, Amazon, Instagram, TikTok, Search, Shopping, Performance Max, Display, YouTube, remarketing, mobile, and Google Ads Editor."),
        7: ("Campaign Execution: ", "Account activation, campaign builds and structures, keyword and negative-keyword strategy, audience segmentation, ad copy, bid testing, budget pacing, daily optimization, and quality assurance."),
        8: ("Tracking & Optimization: ", "GA4, Google Tag Manager, conversion tracking, data-driven attribution, CPC and CPA analysis, ROAS, landing pages, conversion optimization, A/B testing, and multivariate testing."),
        9: ("Reporting & Automation: ", "Looker Studio, Tableau, Funnel.io, Excel, Python, SQL, Databricks, automated reporting, campaign monitoring scripts, KPI reporting, forecasting, and financial analysis."),
        10: ("Client & Team Collaboration: ", "Client consultation, campaign recommendations, performance presentations, cross-functional coordination, documentation of learnings, issue resolution, SEO, ecommerce, and email channel experience."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(p[index], lead, body, lead_color=NAVY)
    set_plain(p[11], "PROFESSIONAL EXPERIENCE", bold=True, color=NAVY)
    bullets = {
        12: ("Campaign Analysis: ", "Analyzed max CPC versus smart bidding, brand and non-brand target CPA, audience performance, incremental CPA, and the Performance Max/Shopping mix to inform optimization."),
        13: ("Reliable Reporting: ", "Built Tableau dashboards and automated weekly reporting across 10+ channels using Python, Databricks, SQL, Excel, and Funnel.io, improving accuracy and decision speed."),
        14: ("Conversion Measurement: ", "Evaluated data-driven attribution and customer journeys from reach and micro-conversions through purchase, click-to-call, and lifetime value to identify search and budget opportunities."),
        15: ("Budget Recommendations: ", "Used regression models, holdouts, geo tests, scale-up/down analysis, and budget reallocation scenarios to forecast outcomes and present investment recommendations."),
        16: ("Paid Media Execution: ", "Managed Google Ads, Microsoft Ads, Amazon, Meta, Instagram, and TikTok across an approximately $400K monthly advertising budget."),
        17: ("Campaign Optimization: ", "Increased monthly volume fourfold while improving ROAS from 1.5 to 3.5 through bidding strategy, audience analysis, campaign testing, budget allocation, and conversion review."),
        18: ("Tracking & Visibility: ", "Configured GA4 and Google Tag Manager measurement and built Looker Studio KPI dashboards for campaign pacing, website performance, inventory planning, and leadership decisions."),
        19: ("Cross-Functional Execution: ", "Coordinated search and broader channel strategy with website, SEO, operations, and creative priorities to maintain efficient delivery and support profitable growth."),
        21: ("B2B Marketing Operations: ", "Directed digital marketing and ecommerce for a large distributor, coordinating execution and reporting across marketing, sales, operations, finance, IT, and product teams."),
        22: ("Channel Expansion: ", "Modernized the company's digital environment and launched multiple B2C channels while protecting relationships with more than 650 B2B retail partners."),
        23: ("Reporting Consistency: ", "Maintained marketing databases, financial reporting, and cross-channel systems that improved budget visibility, data consistency, collaboration, and decisions."),
        24: ("Business Priorities: ", "Applied project-by-project cost-benefit analysis to prioritize growth initiatives, marketplace opportunities, product investments, and operational improvements."),
        25: ("Multi-Account Delivery: ", "Managed 75+ Google Ads accounts and more than $276K in monthly spend across search, display, mobile, remarketing, YouTube, lead generation, and multi-channel client programs."),
        26: ("Client Partnership: ", "Consulted directly with clients on business goals, pain points, budget allocation, campaign structure, SEO, website, email, social, and paid media opportunities."),
        27: ("Targeting & Testing: ", "Conducted keyword and competitive research, developed targeting and messaging recommendations, and created conversion, attribution, A/B, and multivariate testing frameworks."),
        28: ("Monitoring & Quality: ", "Built Funnel.io and Looker Studio reporting, created automated monitoring scripts, and developed a repeatable account-management system adopted across the agency."),
        29: ("Campaign & Team Delivery: ", "Led an eight-person ecommerce team responsible for paid search, customer acquisition, campaign delivery, website performance, and growth across the US, Canada, and UK."),
        30: ("Campaign Scale: ", "Managed 150+ campaigns and approximately $400K in monthly spend, generating more than $9M in revenue and 35% of company sales."),
        31: ("Hands-On Optimization: ", "Directed keyword strategy, bid experiments, landing-page optimization, ad copy, audience analysis, conversion optimization, attribution, and A/B and multivariate testing."),
        32: ("Multi-Channel Programs: ", "Managed Google Ads, Microsoft Ads, and Amazon campaigns across search, shopping, display, video, remarketing, mobile, social, local, and email."),
        33: ("Performance Communication: ", "Created annual projections and KPI reporting with senior leadership, using platform, analytics, Magento, accounting, and competitive data to guide budget and campaign decisions."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(p[index], lead, body)
    for table, job in zip(doc.tables, jobs, strict=True):
        set_plain(table.cell(0, 0).paragraphs[0],
                  f"{job['title']} | {job['company']} — {job['location']}", bold=True, color=NAVY)
        table.cell(0, 1).text = ""
    set_plain(p[34], "EDUCATION & CERTIFICATIONS", bold=True, color=NAVY)
    set_plain(p[35], identity["education"], bold=True)
    p[36]._element.getparent().remove(p[36]._element)
    set_plain(p[37], identity["certifications"])
    doc.save(path)
    import json
    (SCRATCH / "generation-source-hashes.json").write_text(json.dumps(source_hashes(), indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    build_resume()
