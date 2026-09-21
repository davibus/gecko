"""Build and validate the Gecko resume for Trove Brands job 5750188863."""

from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.shared import RGBColor

from generate_marksmen_growth_resume import build_resume as build_base_resume
from generate_vitality_medical_resume import NAVY, export_and_validate, set_run


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "5750188863"
COMPANY = "Trove-Brands"
OUTPUT = ROOT / "output" / "resumes" / f"Dave-Call+{COMPANY}+{JOB_KEY}.docx"
SCRATCH = ROOT / "scratch" / f"{COMPANY}+{JOB_KEY}"
TEMPLATE = SCRATCH / "base-template.docx"
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
        "DIGITAL MARKETING & E-COMMERCE GROWTH LEADER",
        size=11.5,
        bold=True,
        color=RGBColor(40, 70, 110),
    )
    set_plain(
        paragraphs[4],
        "Strategic, hands-on digital marketing and ecommerce leader with 14+ years driving measurable acquisition, "
        "revenue, and channel growth for consumer and B2B businesses. Leads teams, budgets, forecasting, and full-funnel "
        "programs across paid media, website performance, SEO, email, conversion optimization, and analytics. Proven at "
        "scaling monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5, managing programs producing "
        "more than $9M in revenue, and translating attribution, customer value, and performance data into decisions for "
        "senior leaders and cross-functional partners.",
    )

    skills = {
        6: ("Digital Growth Strategy: ", "Ecommerce and B2C growth, acquisition, retention, lifecycle marketing, website performance, channel planning, budget allocation, revenue forecasting, KPI development, customer journeys, and executive recommendations."),
        7: ("Channels & Optimization: ", "Google Ads, Bing Ads, Meta Ads, Amazon, Instagram, TikTok, paid search and social, display, shopping, video, remarketing, email, SEO, content strategy, landing pages, CRO, and A/B/multivariate testing."),
        8: ("Analytics & Performance: ", "GA4, Google Tag Manager, Tableau, Looker Studio, Adobe Analytics, Funnel.io, Excel, SQL, Python, Databricks, attribution, LTV, CAC, ROAS, conversion paths, dashboards, regression analysis, and forecasting."),
        9: ("Commerce & Marketing Platforms: ", "Magento, Shopify, WordPress, Klaviyo, HubSpot, Salesforce, Marketo, Amazon Vendor and Seller Central, Meta Ads Manager, Google Search Console, Semrush, Moz, and SimilarWeb."),
        10: ("Leadership & Operations: ", "Team development, cross-functional planning, creative and web collaboration, product and retail alignment, project management, financial analysis, reporting cadence, process automation, and executive communication."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(paragraphs[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Portfolio & Team Leadership: ", "Managed $30 million per month with a team of four, using customer, channel, and financial analysis to guide investment and acquisition decisions."),
        13: ("Forecasting & Allocation: ", "Built regression-based scenarios to determine where an additional $10 million should be invested, evaluating holdouts, promotions, scale changes, and cross-channel reallocations."),
        14: ("Attribution & Customer Value: ", "Analyzed data-driven attribution, lifetime value, audiences, bidding, promotions, brand/non-brand CPA, and full-funnel reach-to-conversion tests."),
        15: ("Performance Reporting: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms."),
        16: ("Ecommerce Revenue Growth: ", "Increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5 across a $400K monthly marketing budget."),
        17: ("Digital Ecosystem Ownership: ", "Managed Google, Bing, Amazon, Facebook, Instagram, and TikTok while guiding SEO, website optimization, email effectiveness, and cross-platform budget decisions."),
        18: ("Cross-Functional KPIs: ", "Built Looker Studio reporting that connected marketing performance with inventory, engineering, management, web development, email, and operating priorities."),
        19: ("Measurement Infrastructure: ", "Implemented custom GA4 and Google Tag Manager reporting and created an inventory-planning methodology used across multiple departments."),
        21: ("Ecommerce Transformation: ", "Led ecommerce and marketing for a large distributor, building a functional digital environment and adding multiple B2C platforms while supporting 650+ retail partners."),
        22: ("Commerce Expansion: ", "Developed ecommerce-specific products with manufacturers and expanded Amazon operations into CastleGate, Target.com, Costco.com, and other channels."),
        23: ("Commercial Planning: ", "Performed daily financial analysis to identify product niches, guide development, and evaluate marketing initiatives through project-level cost/benefit decisions."),
        24: ("Cross-Functional Leadership: ", "Worked with IT, operations, finance, product development, HR, and sales leaders while managing changing priorities, systems, reporting, and process improvement."),
        25: ("Full-Funnel Strategy: ", "Advised clients on allocating marketing funds across websites, SEO, email, paid search, display, mobile, remarketing, YouTube, and social based on business needs."),
        26: ("Paid Media Scale: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month and created a standardized quality system adopted across the agency."),
        27: ("Testing & Conversion: ", "Created conversion and attribution models and multivariate tests to improve audience, channel, message, and landing-page decisions."),
        28: ("Marketing Automation: ", "Developed custom scripts for continuous campaign monitoring, budget oversight, and faster performance issue identification."),
        29: ("Ecommerce Team Leadership: ", "Led an eight-person ecommerce department responsible for paid search, outreach, lead generation, and customer acquisition in the United States, Canada, and the UK."),
        30: ("Revenue & Budget Impact: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue—35% of company revenue."),
        31: ("Omnichannel Acquisition: ", "Managed display, mobile, remarketing, search, video, email, shopping, social, and local programs while conducting keyword, channel, and competitive research."),
        32: ("Website & CRO: ", "Analyzed funnels and conversion paths, optimized landing pages, and ran A/B and multivariate tests while partnering with web development and monitoring SEO/SEM."),
        33: ("Executive Planning: ", "Set annual goals, projections, and KPIs with senior management and reported performance using Magento, Google Analytics, ACCTivate, and QuickBooks."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(paragraphs[index], lead, body)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


if __name__ == "__main__":
    build_resume(OUTPUT)
    export_and_validate(OUTPUT, PDF, SCRATCH)
