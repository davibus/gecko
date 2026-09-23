"""Build Scout 692's resume from content verified against the current master DOCX."""

import json
from pathlib import Path

import docx
from docx.shared import Inches, RGBColor

from generate_wpromote_resume import build_resume as build_layout
from generate_wpromote_resume import set_labeled, set_plain
from generate_vitality_medical_resume import NAVY
from gecko_v2 import master_identity, master_jobs, source_hashes

ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "7c7ecd7f-c704-46d2-97b3-e4f5b06e5d44"
SCRATCH = ROOT / "scratch" / f"Pattern+{JOB_KEY}"
OUTPUT = ROOT / "output" / "resumes" / f"Dave-Call+Pattern+{JOB_KEY}.docx"


def build_resume(path: Path = OUTPUT):
    identity = master_identity()
    jobs = master_jobs()
    # Reuse layout; replace all factual text with current-master-backed content.
    build_layout(path, scratch_dir=SCRATCH)
    doc = docx.Document(path)
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Inches(.45)
    p = doc.paragraphs
    set_plain(p[0], identity["name"], size=19, bold=True, color=NAVY)
    set_plain(p[1], "DIGITAL MARKETING MANAGER | PAID SEARCH & ECOMMERCE",
              size=11.5, bold=True, color=RGBColor(40, 70, 110))
    set_plain(p[2], identity["contact"], size=9.5)
    set_plain(p[3], "PROFESSIONAL SUMMARY", bold=True, color=NAVY)
    set_plain(p[4],
              "Digital marketing professional with 14+ years across paid search, ecommerce, and agency client "
              "programs. Managed 75+ Google Ads accounts with more than $276K in monthly spend, advising clients "
              "on budgets, campaign structure, and growth priorities. Hands-on experience across Amazon, Google, "
              "Microsoft Ads, and Meta, supported by Excel, attribution, and reporting automation. Managed up to "
              "$30 million per month with a four-person team and led an eight-person ecommerce department.")
    set_plain(p[5], "CORE COMPETENCIES & TECHNICAL SKILLS", bold=True, color=NAVY)
    skills = {
        6: ("Paid Search & Display: ", "Google Ads, Amazon advertising, Microsoft Ads, Meta, Search, Shopping, Performance Max, Display, YouTube, remarketing, mobile, and Google Ads Editor."),
        7: ("Research & Experimentation: ", "Keyword and negative-keyword strategy, competitive research, audience segmentation, ad copy, bid experiments, smart-bidding analysis, landing pages, A/B testing, and multivariate testing."),
        8: ("Analytics & Performance: ", "Excel, GA4, Google Tag Manager, Tableau, Looker Studio, Funnel.io, attribution, conversion tracking, CPC, CPA, ROAS, LTV, forecasting, and financial analysis."),
        9: ("Client & Commerce Strategy: ", "Client consultation, budget allocation, performance presentations, B2B/B2C ecommerce, Shopify, Magento, Amazon Marketing Services, cross-functional collaboration, and team leadership."),
        10: ("Campaign Operations: ", "Campaign builds, daily optimization, budget pacing, quality assurance, Python, SQL, Databricks, reporting automation, monitoring scripts, issue resolution, and repeatable account processes."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(p[index], lead, body, lead_color=NAVY)
    set_plain(p[11], "PROFESSIONAL EXPERIENCE", bold=True, color=NAVY)
    bullets = {
        12: ("Bidding & Channel Analysis: ", "Analyzed max CPC versus smart bidding, brand and non-brand target CPA, Performance Max and Shopping mix, audience performance, data-driven attribution, and incremental CPA."),
        13: ("Performance Visibility: ", "Built Tableau dashboards and automated weekly reporting across 10+ channels using Python, Databricks, SQL, Excel, and Funnel.io, improving accuracy and decision speed."),
        14: ("Full-Funnel Measurement: ", "Evaluated customer journeys from reach and micro-conversions through purchase, click-to-call, and lifetime value to identify scalable search and budget opportunities."),
        15: ("Investment Recommendations: ", "Used regression models, holdouts, geo tests, scale-up/down analysis, and budget reallocation scenarios to forecast outcomes and present investment recommendations."),
        16: ("Multi-Platform Advertising: ", "Managed Google Ads, Microsoft Ads, Amazon, Meta, Instagram, and TikTok across an approximately $400K monthly advertising budget."),
        17: ("Ecommerce Growth: ", "Increased monthly volume fourfold while improving ROAS from 1.5 to 3.5 through bidding strategy, audience analysis, campaign testing, budget allocation, and conversion review."),
        18: ("Measurement & Reporting: ", "Configured GA4 and Google Tag Manager measurement and built Looker Studio KPI dashboards for campaign pacing, website performance, inventory planning, and leadership decisions."),
        19: ("Cross-Functional Alignment: ", "Coordinated search and broader channel strategy with website, SEO, operations, and creative priorities to maintain efficient delivery and support profitable growth."),
        21: ("Commerce & Partner Relationships: ", "Modernized a large B2B distributor's digital environment and launched multiple B2C channels while protecting relationships with more than 650 retail partners."),
        22: ("Commercial Priorities: ", "Applied project-by-project cost-benefit analysis to prioritize growth initiatives, marketplace opportunities, product investments, and operational improvements."),
        23: ("Financial & Marketing Visibility: ", "Maintained marketing databases, financial reporting, and cross-channel systems that improved budget visibility, data consistency, collaboration, and decisions."),
        24: ("Collaborative Execution: ", "Directed digital marketing and ecommerce, coordinating execution and reporting across marketing, sales, operations, finance, IT, and product teams."),
        25: ("Agency Portfolio: ", "Managed 75+ Google Ads accounts and more than $276K in monthly spend across search, display, mobile, remarketing, YouTube, lead generation, and multi-channel client programs."),
        26: ("Client Strategy & Budgets: ", "Consulted directly with clients on business goals, pain points, budget allocation, campaign structure, SEO, website, email, social, and paid media opportunities."),
        27: ("Research & Testing: ", "Conducted keyword and competitive research, developed targeting and messaging recommendations, and created conversion, attribution, A/B, and multivariate testing frameworks."),
        28: ("Reporting & Account Quality: ", "Built Funnel.io and Looker Studio reporting, created automated monitoring scripts, and developed a repeatable account-management system adopted across the agency."),
        29: ("Team Leadership: ", "Led an eight-person ecommerce team responsible for paid search, customer acquisition, campaign delivery, website performance, and growth across the US, Canada, and UK."),
        30: ("Revenue & Scale: ", "Managed 150+ campaigns and approximately $400K in monthly spend, generating more than $9M in revenue and 35% of company sales."),
        31: ("Campaign Optimization: ", "Directed keyword strategy, bid experiments, landing-page optimization, ad copy, audience analysis, conversion optimization, attribution, and A/B and multivariate testing."),
        32: ("Search & Marketplace Execution: ", "Managed Google Ads, Microsoft Ads, and Amazon campaigns across search, shopping, display, video, remarketing, mobile, social, local, and email."),
        33: ("Business Recommendations: ", "Created annual projections and KPI reporting with senior leadership, using platform, analytics, Magento, accounting, and competitive data to guide budget and campaign decisions."),
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
    (SCRATCH / "generation-source-hashes.json").write_text(json.dumps(source_hashes(), indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    build_resume()
