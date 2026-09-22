"""Build and validate the Gecko resume for QRY job -2181779819755903792."""

from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.shared import RGBColor

from generate_marksmen_growth_resume import build_resume as build_base_resume
from generate_vitality_medical_resume import NAVY, export_and_validate, set_run


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "-2181779819755903792"
COMPANY = "QRY"
OUTPUT = ROOT / "output" / "resumes" / f"Dave-Call+{COMPANY}+{JOB_KEY}.docx"
SCRATCH = ROOT / "scratch" / f"{COMPANY}+{JOB_KEY}"
PDF = SCRATCH / "resume-preview.pdf"


def clear_content(paragraph):
    for child in list(paragraph._p):
        if child.tag != qn("w:pPr"):
            paragraph._p.remove(child)


def set_plain(paragraph, text, *, size=11, bold=False, color=None):
    clear_content(paragraph)
    set_run(paragraph.add_run(text), size=size, bold=bold, color=color)


def set_labeled(paragraph, lead, body, *, lead_color=None):
    clear_content(paragraph)
    set_run(paragraph.add_run(lead), bold=True, color=lead_color)
    set_run(paragraph.add_run(body))


def build_resume(path: Path, scratch_dir: Path | None = None):
    scratch = Path(scratch_dir) if scratch_dir is not None else SCRATCH
    template = scratch / "base-template.docx"
    scratch.mkdir(parents=True, exist_ok=True)
    build_base_resume(template)
    doc = docx.Document(template)
    paragraphs = doc.paragraphs

    set_plain(
        paragraphs[1],
        "PAID SEARCH STRATEGY & PERFORMANCE MARKETING",
        size=11.5,
        bold=True,
        color=RGBColor(40, 70, 110),
    )
    set_plain(
        paragraphs[4],
        "Hands-on paid search and ecommerce marketer with 14+ years turning channel data into profitable growth, clear "
        "client recommendations, and disciplined testing plans. Agency experience includes building and managing 75+ "
        "Google Ads accounts totaling more than $276K per month, advising clients on media allocation, and presenting "
        "consolidated performance reporting. Deep experience across Google, Bing, YouTube, Amazon, Shopping, bidding, "
        "forecasting, attribution, landing-page optimization, and full-funnel measurement, with a record of improving "
        "monthly volume from $200K to $800K while raising ROAS from 1.5 to 3.5.",
    )

    skills = {
        6: ("Paid Search Strategy: ", "Google Ads, Bing Ads, YouTube, Amazon, Shopping, Performance Max, search and display, remarketing, keyword strategy, account structure, bidding, budget pacing, campaign launches, and optimization."),
        7: ("Experimentation & Optimization: ", "A/B and multivariate testing, keywords, bid strategies, ad copy, creative, landing pages, offers, audiences, attribution, conversion paths, CRO, and structured test planning."),
        8: ("Analytics & Forecasting: ", "Excel, GA4, Google Tag Manager, Tableau, Looker Studio, Adobe Analytics, Funnel.io, ROAS, CAC, LTV, CPA, revenue reporting, regression analysis, forecasting, dashboards, and KPI development."),
        9: ("Client & Cross-Channel Leadership: ", "Client consultation, strategic recommendations, performance presentations, stakeholder communication, ecommerce and retail strategy, creative and web collaboration, risk identification, and project management."),
        10: ("Automation & AI Workflows: ", "Python, SQL, Databricks, JavaScript, custom scripts, Google Ads API, ChatGPT, Claude, Perplexity, Codex, Cursor, and AntiGravity for analysis, reporting, monitoring, and workflow acceleration."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(paragraphs[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Search Strategy & Testing: ", "Analyzed max CPC versus smart bidding, brand and non-brand CPA, audiences, promotions, and the mix of Performance Max and Google Shopping to guide channel decisions."),
        13: ("Forecasting & Investment: ", "Built regression-based scenarios to forecast outcomes from holdouts, promotions, scaling decisions, and cross-channel budget reallocations, including an additional $10M investment question."),
        14: ("Full-Funnel Measurement: ", "Evaluated attribution, LTV, reach, comparison, conversion, Click-to-Call, and iSpot data to connect channel performance with customer and business outcomes."),
        15: ("Reporting Automation: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms."),
        16: ("Performance Growth: ", "Managed Google, Bing, Amazon, Meta, Instagram, and TikTok with a $400K monthly budget; increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5."),
        17: ("Measurement Infrastructure: ", "Implemented custom GA4 and Google Tag Manager reporting and built Looker Studio KPIs supporting web, email, inventory, engineering, management, and budget decisions."),
        18: ("Ecommerce Optimization: ", "Guided on-page SEO and website improvements while using product, inventory, channel, and performance data to support cross-functional planning."),
        19: ("Channel Ownership: ", "Managed interconnected paid media, ecommerce, analytics, and reporting platforms while balancing growth goals, efficiency, product availability, and operating needs."),
        21: ("Retail & Ecommerce Leadership: ", "Led ecommerce and marketing for a large distributor, adding multiple B2C platforms while supporting 650+ retail partners and a complex B2B operation."),
        22: ("Marketplace Growth: ", "Expanded Amazon Vendor and Seller Central operations into CastleGate, Target.com, Costco.com, and other retail channels while developing ecommerce-specific products."),
        23: ("Commercial Analysis: ", "Performed daily financial analysis to identify product niches, guide development, and evaluate marketing initiatives through project-level cost/benefit decisions."),
        24: ("Cross-Functional Collaboration: ", "Worked with IT, operations, finance, product development, HR, and sales leaders while managing changing priorities, reporting, and process improvement."),
        25: ("Agency Search Portfolio: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month across a diverse client portfolio."),
        26: ("Client Strategy: ", "Advised clients directly on allocating marketing funds across paid search, display, remarketing, YouTube, social, SEO, email, and website development based on business needs."),
        27: ("Reporting & Recommendations: ", "Consolidated data through Funnel.io and presented Looker Studio reporting, translating account findings into clear channel, budget, and optimization recommendations."),
        28: ("Testing & Quality: ", "Created conversion and attribution models, multivariate tests, automated monitoring scripts, and a standardized quality system adopted across the agency."),
        29: ("Ecommerce Team Leadership: ", "Led an eight-person ecommerce department responsible for paid search, outreach, lead generation, and customer acquisition across the United States, Canada, and the UK."),
        30: ("Revenue & Campaign Scale: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue—35% of company revenue."),
        31: ("Hands-On Optimization: ", "Conducted keyword, audience, competitive, funnel, and conversion-path analysis; developed bid strategies and experiments; and optimized landing pages and ad creative."),
        32: ("Cross-Channel Execution: ", "Managed search, Shopping, display, remarketing, video, email, social, and local campaigns while using Google Ads Editor, Bing Ads Editor, Excel, and analytics platforms."),
        33: ("Planning & Stakeholders: ", "Set annual goals, projections, and KPIs with senior management and partnered with web development to align campaigns, site changes, promotions, and business goals."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(paragraphs[index], lead, body)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


if __name__ == "__main__":
    build_resume(OUTPUT)
    export_and_validate(OUTPUT, PDF, SCRATCH)
