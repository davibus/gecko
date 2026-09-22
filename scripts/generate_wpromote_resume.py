"""Build and validate the Gecko resume for Wpromote job 0ff8aaeb-a07a-40d6-b0b4-e5ff5025a592."""

from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.shared import RGBColor

from generate_marksmen_growth_resume import build_resume as build_base_resume
from generate_vitality_medical_resume import NAVY, export_and_validate, set_run


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "0ff8aaeb-a07a-40d6-b0b4-e5ff5025a592"
COMPANY = "Wpromote"
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
        "PAID SEARCH MANAGER & PERFORMANCE MARKETER",
        size=11.5,
        bold=True,
        color=RGBColor(40, 70, 110),
    )
    set_plain(
        paragraphs[4],
        "Hands-on paid search and performance marketing leader with 14+ years managing complex client portfolios, "
        "direct-response programs, and ecommerce acquisition. Agency experience includes building and managing 75+ "
        "Google Ads accounts totaling more than $276K per month, developing campaign strategies, advising clients, and "
        "turning analysis into clear budget and optimization decisions. Deep experience across Google Ads, Microsoft/Bing "
        "Ads, Search, Shopping, Display, Remarketing, Video, A/B testing, Google Analytics, LTV, CPA, ROAS, forecasting, "
        "automation, and cross-channel collaboration.",
    )

    skills = {
        6: ("Paid Search & Direct Response: ", "Google Ads, Microsoft/Bing Ads, Search, Shopping, Performance Max, Display, Remarketing, Video, Amazon, keyword research, ad copy, bidding, account structure, budget pacing, campaign launches, and optimization."),
        7: ("Testing & Measurement: ", "A/B and multivariate testing, Google Analytics, GA4, Google Tag Manager, attribution, conversion paths, audiences, landing pages, offers, LTV, CPA, ROAS, CRO, and full-funnel measurement."),
        8: ("Analytics & Excel: ", "Advanced Excel, pivot tables, VBA, statistical modeling, Tableau, Looker Studio, Adobe Analytics, Funnel.io, regression analysis, forecasting, dashboards, charting, and KPI development."),
        9: ("Client & Cross-Channel Strategy: ", "Client consultation, performance presentations, stakeholder communication, expectation management, SEO, social advertising, web usability, ecommerce, project management, and cross-functional planning."),
        10: ("Automation & AI Workflows: ", "Python, SQL, Databricks, JavaScript, custom monitoring scripts, Google Ads API, ChatGPT, Claude, Perplexity, Codex, Cursor, and AntiGravity for analysis, reporting, troubleshooting, and optimization."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(paragraphs[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Paid Search Analysis: ", "Evaluated max CPC versus smart bidding, brand and non-brand CPA, audiences, promotions, and the mix of Performance Max and Google Shopping to guide optimization decisions."),
        13: ("LTV & Profitability: ", "Analyzed customer lifetime value, attribution, affiliate economics, promotional performance, bidding, and acquisition efficiency to connect channel decisions with business value."),
        14: ("Forecasting & Budgets: ", "Built regression-based scenarios to predict results from holdouts, promotions, scaling decisions, and cross-channel reallocations, including an additional $10M investment question."),
        15: ("Reporting Automation: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms."),
        16: ("Direct-Response Growth: ", "Managed Google, Bing, Amazon, Meta, Instagram, and TikTok with a $400K monthly budget; increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5."),
        17: ("Analytics Implementation: ", "Implemented custom GA4 and Google Tag Manager reporting and built Looker Studio KPIs supporting web, email, inventory, engineering, management, and budget decisions."),
        18: ("Web & SEO Collaboration: ", "Guided on-page SEO and website optimization while connecting channel, product, inventory, conversion, and email performance across departments."),
        19: ("Campaign Ownership: ", "Managed interconnected paid media, ecommerce, analytics, and reporting platforms while balancing growth, efficiency, product availability, and operating priorities."),
        21: ("Ecommerce Leadership: ", "Led ecommerce and marketing for a large distributor, adding multiple B2C platforms while supporting 650+ retail partners and a complex B2B operation."),
        22: ("Marketplace Expansion: ", "Expanded Amazon Vendor and Seller Central operations into CastleGate, Target.com, Costco.com, and other channels while developing ecommerce-specific products."),
        23: ("Financial Analysis: ", "Performed daily analysis to identify product niches, guide development, and evaluate marketing initiatives through project-level cost/benefit decisions."),
        24: ("Cross-Functional Delivery: ", "Worked with IT, operations, finance, product development, HR, and sales leaders while managing changing priorities, reporting needs, and process improvement."),
        25: ("Agency Portfolio Management: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month across clients with different budgets, objectives, and business needs."),
        26: ("Client Strategy: ", "Advised clients on allocating funds across paid search, display, remarketing, YouTube, social, SEO, email, and website development and translated account data into recommendations."),
        27: ("Reporting & Presentations: ", "Consolidated data through Funnel.io and presented Looker Studio reporting to explain performance, budget priorities, and next-step optimization opportunities."),
        28: ("Testing & Automation: ", "Created conversion and attribution models, multivariate tests, continuous monitoring scripts, and a standardized quality system adopted across the agency."),
        29: ("Team & Channel Leadership: ", "Led an eight-person ecommerce department responsible for paid search, outreach, lead generation, and customer acquisition across the United States, Canada, and the UK."),
        30: ("Revenue & Scale: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue—35% of company revenue."),
        31: ("Hands-On SEM: ", "Conducted keyword, audience, competitive, funnel, and conversion-path analysis; developed bid strategies and experiments; and optimized landing pages and ad creative."),
        32: ("Cross-Channel Execution: ", "Managed search, Shopping, Display, Remarketing, Video, email, social, and local campaigns using Google Ads Editor, Bing Ads Editor, Excel, and analytics platforms."),
        33: ("Planning & Stakeholders: ", "Set goals, annual projections, and KPIs with senior management and partnered with web development to align campaigns, site changes, promotions, and business goals."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(paragraphs[index], lead, body)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


if __name__ == "__main__":
    build_resume(OUTPUT)
    export_and_validate(OUTPUT, PDF, SCRATCH)
