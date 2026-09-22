"""Build and validate the Gecko resume for CampusWorks job fa9aebd0-e27c-4df6-b8ad-a425fc672971."""

from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.shared import RGBColor

from generate_marksmen_growth_resume import build_resume as build_base_resume
from generate_vitality_medical_resume import NAVY, export_and_validate, set_run


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "fa9aebd0-e27c-4df6-b8ad-a425fc672971"
COMPANY = "CampusWorks-Inc"
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
        "DIGITAL MARKETING MANAGER | SEO, CRO & MARKETING OPERATIONS",
        size=11.5,
        bold=True,
        color=RGBColor(40, 70, 110),
    )
    set_plain(
        paragraphs[4],
        "Hands-on digital marketing leader with 14+ years connecting website, SEO, conversion optimization, paid media, "
        "email, analytics, and reporting to revenue outcomes. Experience leading ecommerce and agency programs, managing "
        "WordPress and other web platforms, improving conversion paths through A/B and multivariate testing, and building "
        "decision-ready dashboards and automated reporting. Combines technical fluency in HTML, CSS, JavaScript, Python, "
        "SQL, GA4, GTM, and HubSpot with disciplined campaign ownership and cross-functional execution.",
    )

    skills = {
        6: ("Website & SEO Operations: ", "WordPress, Magento, Shopify, HTML5, CSS3, JavaScript, PHP, responsive web experiences, on-page and technical SEO, keyword research, metadata, site structure, Search Console, Moz, and Semrush."),
        7: ("CRO & Customer Journey: ", "A/B and multivariate testing, landing pages, forms, calls-to-action, conversion paths, funnel analysis, web usability, audience research, attribution, and continuous optimization."),
        8: ("Analytics & Reporting: ", "GA4, Google Tag Manager, Adobe Analytics, Tableau, Looker Studio, Excel, Funnel.io, SQL, Databricks, forecasting, KPI development, dashboards, and statistical modeling."),
        9: ("Campaign & Marketing Operations: ", "Google Ads, Microsoft/Bing Ads, LinkedIn, Meta, email marketing, HubSpot, campaign planning, audience targeting, budget pacing, CRM-aware lead generation, and cross-channel measurement."),
        10: ("Automation & Technical Delivery: ", "Python, JavaScript, VBA, Google Ads API, reporting automation, custom monitoring scripts, database workflows, reusable processes, project management, and AI-assisted analysis."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(paragraphs[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Measurement Strategy: ", "Evaluated bidding, brand and non-brand CPA, audiences, promotions, attribution, and the mix of Performance Max and Google Shopping to guide acquisition decisions."),
        13: ("Pipeline Economics: ", "Analyzed lifetime value, conversion behavior, affiliate economics, and promotional performance to connect channel investment with durable customer value."),
        14: ("Forecasting & Optimization: ", "Built regression-based scenarios for holdouts, promotions, scaling decisions, and cross-channel reallocations, including an additional $10M investment question."),
        15: ("Reporting Infrastructure: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms."),
        16: ("Full-Funnel Growth: ", "Managed Google, Bing, Amazon, Meta, Instagram, and TikTok with a $400K monthly budget; increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5."),
        17: ("Web Analytics: ", "Implemented custom GA4 and Google Tag Manager reporting and built Looker Studio KPIs supporting website, email, inventory, engineering, management, and budget decisions."),
        18: ("SEO & Conversion: ", "Directed on-page SEO and website optimization, aligning keywords, content, product availability, landing experiences, promotions, and measurement across teams."),
        19: ("Operational Ownership: ", "Managed interconnected paid media, ecommerce, analytics, email, and reporting workstreams while balancing growth, efficiency, deadlines, and changing priorities."),
        21: ("Digital Commerce Leadership: ", "Led ecommerce and marketing for a large distributor, expanding B2C platforms while supporting 650+ retail partners and a complex B2B operation."),
        22: ("Web & Marketplace Expansion: ", "Expanded owned ecommerce and Amazon Vendor and Seller Central operations into CastleGate, Target.com, Costco.com, and other channels."),
        23: ("Data & Process Improvement: ", "Built and managed databases, analyzed performance daily, identified product niches, and evaluated marketing initiatives through project-level cost/benefit decisions."),
        24: ("Cross-Functional Delivery: ", "Partnered with IT, operations, finance, product development, HR, and sales leaders to deliver web, marketing, reporting, and process improvements."),
        25: ("Agency Portfolio Management: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month across clients with different audiences, objectives, budgets, and websites."),
        26: ("Integrated Digital Strategy: ", "Advised clients on paid search, display, remarketing, YouTube, social, SEO, email, and website development, translating performance data into priorities."),
        27: ("Dashboards & Attribution: ", "Consolidated data with Funnel.io, presented Looker Studio reporting, and developed attribution and conversion models to clarify channel performance and next steps."),
        28: ("Testing & Automation: ", "Designed multivariate tests, built continuous monitoring scripts, and created a standardized quality system adopted across the agency."),
        29: ("Team & Channel Leadership: ", "Led an eight-person ecommerce department responsible for paid search, outreach, lead generation, and customer acquisition across the United States, Canada, and the UK."),
        30: ("Revenue & Scale: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue—35% of company revenue."),
        31: ("CRO Execution: ", "Analyzed keywords, audiences, competitors, funnels, and conversion paths; developed experiments; and optimized landing pages, bids, offers, and ad creative."),
        32: ("Cross-Channel Programs: ", "Managed search, Shopping, Display, Remarketing, Video, email, social, and local campaigns using advertising editors, Excel, and analytics platforms."),
        33: ("Planning & Stakeholders: ", "Set goals, annual projections, and KPIs with senior management and partnered with web development on site changes, promotions, measurement, and business priorities."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(paragraphs[index], lead, body)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


if __name__ == "__main__":
    build_resume(OUTPUT)
    export_and_validate(OUTPUT, PDF, SCRATCH)
