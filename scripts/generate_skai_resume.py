"""Build and validate the Gecko resume for Skai job 892595661388929024."""

from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.shared import RGBColor

from generate_marksmen_growth_resume import build_resume as build_base_resume
from generate_vitality_medical_resume import NAVY, export_and_validate, set_run


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "892595661388929024"
COMPANY = "Skai"
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
        "PAID SEARCH & PERFORMANCE MARKETING LEADER",
        size=11.5,
        bold=True,
        color=RGBColor(40, 70, 110),
    )
    set_plain(
        paragraphs[4],
        "Hands-on paid search and performance marketing leader with 14+ years managing complex acquisition programs, "
        "advising clients, and translating data into clear campaign decisions. Deep experience across Google Ads, Bing "
        "Ads, Shopping, Performance Max, bid strategy, reporting, and conversion measurement. Built and managed 75+ "
        "client accounts totaling more than $276K per month and led ecommerce programs producing more than $9M in "
        "revenue. Combines campaign execution, strategic consulting, analytics, automation, and cross-functional "
        "communication to improve performance and client outcomes.",
    )

    skills = {
        6: ("Paid Search & Shopping: ", "Google Ads, Bing/Microsoft Ads, Google Shopping, Performance Max, search and display, remarketing, keyword strategy, bid management, account structure, campaign implementation, optimization, and media planning."),
        7: ("Analytics & Measurement: ", "Excel, GA4, Google Tag Manager, Tableau, Looker Studio, Adobe Analytics, Funnel.io, attribution, LTV, CPA, ROAS, conversion paths, regression analysis, forecasting, dashboards, and performance reporting."),
        8: ("Client Strategy & Service: ", "Client consultation, strategic recommendations, campaign reporting, stakeholder presentations, account management, problem solving, training, cross-functional planning, and distributed-team collaboration."),
        9: ("Data, Automation & Platforms: ", "Python, SQL, Databricks, JavaScript, Google Ads API, custom scripts, workflow automation, Google Workspace, Microsoft Office, Salesforce, HubSpot, Magento, Shopify, and WordPress."),
        10: ("AI-Assisted Workflows: ", "ChatGPT, Claude, Perplexity, Codex, Cursor, and AntiGravity for analysis, research, scripting, reporting, troubleshooting, content support, and workflow acceleration."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(paragraphs[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Search & Shopping Analysis: ", "Evaluated max CPC versus smart bidding, brand and non-brand CPA, audience performance, and the mix of Performance Max and Google Shopping to guide optimization decisions."),
        13: ("Portfolio & Team Leadership: ", "Managed $30 million per month with a team of four, using customer, channel, and financial analysis to guide investment, testing, and acquisition decisions."),
        14: ("Forecasting & Attribution: ", "Built regression-based investment scenarios and analyzed data-driven attribution, customer lifetime value, promotions, holdouts, and cross-channel reallocations."),
        15: ("Reporting Automation: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms."),
        16: ("Paid Media Growth: ", "Managed Google Ads, Bing Ads, Amazon, Meta, Instagram, and TikTok with a $400K monthly budget; increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5."),
        17: ("Measurement & Optimization: ", "Implemented custom GA4 and Google Tag Manager reporting and used performance insights to guide channel, website, email, inventory, and budget decisions."),
        18: ("Cross-Functional Reporting: ", "Built Looker Studio KPIs that gave inventory, engineering, management, web development, and email teams visibility into marketing performance."),
        19: ("Operational Planning: ", "Created a robust inventory-planning methodology used across multiple departments to connect product availability, operating priorities, and marketing decisions."),
        21: ("Ecommerce & Retail Leadership: ", "Led ecommerce and marketing for a large distributor, adding multiple B2C platforms while supporting 650+ retail partners and a complex B2B operation."),
        22: ("Marketplace Expansion: ", "Developed ecommerce-specific products with manufacturers and expanded Amazon operations into CastleGate, Target.com, Costco.com, and other retail channels."),
        23: ("Commercial Analysis: ", "Performed daily financial analysis to identify product niches, guide development, and evaluate marketing initiatives through project-level cost/benefit decisions."),
        24: ("Cross-Functional Collaboration: ", "Worked with IT, operations, finance, product development, HR, and sales leaders while managing changing priorities, systems, reporting, and process improvement."),
        25: ("Client Search Strategy: ", "Advised clients directly on allocating marketing funds across paid search, Shopping, display, remarketing, YouTube, social, SEO, email, and website development based on business needs."),
        26: ("Agency Account Scale: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month and created a standardized quality system adopted across the agency."),
        27: ("Performance Communication: ", "Translated account analysis into client recommendations and presented consolidated Funnel.io and Looker Studio reporting to guide campaign and channel decisions."),
        28: ("Testing & Automation: ", "Created conversion and attribution models, multivariate tests, and custom scripts for continuous campaign monitoring and faster performance issue identification."),
        29: ("Search Team Leadership: ", "Led an eight-person ecommerce department responsible for paid search, outreach, lead generation, and customer acquisition across the United States, Canada, and the UK."),
        30: ("Revenue & Campaign Scale: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue—35% of company revenue."),
        31: ("Hands-On Optimization: ", "Conducted keyword, audience, competitive, funnel, and conversion-path analysis; developed bid strategies and experiments; and optimized landing pages and ad creative."),
        32: ("Paid Search Operations: ", "Used Google Ads Editor, Bing Ads Editor, Excel, Google Analytics, Magento, and Amazon analytics while managing search, Shopping, display, remarketing, video, social, local, and email programs."),
        33: ("Planning & Stakeholder Alignment: ", "Set annual goals, projections, and KPIs with senior management and partnered with web development to align campaigns, site changes, promotions, and business goals."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(paragraphs[index], lead, body)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


if __name__ == "__main__":
    build_resume(OUTPUT)
    export_and_validate(OUTPUT, PDF, SCRATCH)
