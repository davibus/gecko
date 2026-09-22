"""Build and validate the Gecko resume for EnableComp job 97ba8981-d1ad-4a81-ae0a-458dcf9c573d."""

from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.shared import RGBColor

from generate_marksmen_growth_resume import build_resume as build_base_resume
from generate_vitality_medical_resume import NAVY, export_and_validate, set_run


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "97ba8981-d1ad-4a81-ae0a-458dcf9c573d"
COMPANY = "EnableComp"
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
        "GROWTH MARKETING MANAGER | DEMAND GENERATION & ANALYTICS",
        size=11.5,
        bold=True,
        color=RGBColor(40, 70, 110),
    )
    set_plain(
        paragraphs[2],
        "Lehi, UT 84043 • (530) 507-8269 • mdavidcall@gmail.com • linkedin.com/in/mdavidcall",
        size=9.5,
    )
    set_plain(
        paragraphs[4],
        "Hands-on growth marketer with 14+ years building and optimizing multi-channel acquisition programs across SEM, "
        "paid social, retargeting, email, organic search, landing pages, and ecommerce. Combines campaign strategy and "
        "content execution with disciplined budget management, funnel analysis, attribution, and automated reporting. "
        "Experienced with HubSpot, GA4, GTM, Python, SQL, dashboards, and AI-assisted workflows, with a record of turning "
        "complex data into clear priorities for sales, marketing, technical, and executive stakeholders.",
    )

    skills = {
        6: ("Demand Generation & Paid Media: ", "SEM, Google Ads, Microsoft/Bing Ads, LinkedIn, Meta, paid social, retargeting, Shopping, Display, Video, organic search, audience targeting, campaign launches, budget pacing, and optimization."),
        7: ("Content & Conversion: ", "Landing pages, email and ad copy, offers, calls-to-action, keyword research, SEO, conversion paths, web usability, A/B and multivariate testing, customer journeys, and lead generation."),
        8: ("Marketing Automation & Operations: ", "HubSpot, email marketing, campaign workflows, Google Tag Manager, databases, reusable processes, monitoring scripts, project management, and cross-functional delivery."),
        9: ("Analytics & Revenue Measurement: ", "GA4, Google Analytics, attribution, LTV, CPA, ROAS, conversion rate, Tableau, Looker Studio, Adobe Analytics, Funnel.io, Excel, forecasting, and KPI dashboards."),
        10: ("Technical & AI Workflows: ", "Python, SQL, Databricks, JavaScript, VBA, Google Ads API, reporting automation, statistical modeling, ChatGPT, Claude, Perplexity, Codex, Cursor, and AntiGravity."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(paragraphs[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Growth Investment: ", "Managed $30M per month with a team of four, evaluating bids, audiences, promotions, acquisition efficiency, and channel mix to guide growth decisions."),
        13: ("Funnel Economics: ", "Analyzed lifetime value, attribution, conversion behavior, affiliate economics, promotional performance, and CPA to connect marketing activity with durable customer value."),
        14: ("Forecasting & Experimentation: ", "Built regression-based scenarios for holdouts, promotions, scaling decisions, and cross-channel reallocations, including an additional $10M investment question."),
        15: ("Reporting Automation: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms."),
        16: ("Multi-Channel Growth: ", "Managed Google, Bing, Amazon, Meta, Instagram, and TikTok with a $400K monthly budget; increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5."),
        17: ("Campaign Measurement: ", "Implemented custom GA4 and Google Tag Manager reporting and built Looker Studio KPIs supporting website, email, inventory, engineering, management, and budget decisions."),
        18: ("Content & Conversion: ", "Directed on-page SEO and website optimization, aligning keywords, product content, landing experiences, email, promotions, and measurement across teams."),
        19: ("Operating Rhythm: ", "Managed interconnected paid media, ecommerce, analytics, email, and reporting workstreams while balancing growth, efficiency, deadlines, and changing priorities."),
        21: ("Complex B2B Marketing: ", "Led ecommerce and marketing for a large distributor, expanding B2C platforms while supporting 650+ retail partners and a complex B2B operation."),
        22: ("Channel Expansion: ", "Expanded owned ecommerce and Amazon Vendor and Seller Central operations into CastleGate, Target.com, Costco.com, and additional customer-acquisition channels."),
        23: ("Data-Driven Planning: ", "Built and managed databases, analyzed performance daily, identified product niches, and evaluated marketing initiatives through project-level cost/benefit decisions."),
        24: ("Cross-Functional Delivery: ", "Partnered with IT, operations, finance, product development, HR, and sales leaders to deliver marketing, reporting, and process improvements."),
        25: ("Campaign Portfolio: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month across clients with different audiences, messages, objectives, and budgets."),
        26: ("Integrated Programs: ", "Advised clients on paid search, display, remarketing, YouTube, social, SEO, email, and website development, translating performance data into campaign priorities."),
        27: ("Reporting & Attribution: ", "Consolidated data with Funnel.io, presented Looker Studio reporting, and developed attribution and conversion models to clarify channel performance and next steps."),
        28: ("Testing & Automation: ", "Designed multivariate tests, built continuous monitoring scripts, and created a standardized quality system adopted across the agency."),
        29: ("Acquisition Leadership: ", "Led an eight-person ecommerce department responsible for paid search, outreach, lead generation, and customer acquisition across the United States, Canada, and the UK."),
        30: ("Revenue & Scale: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue—35% of company revenue."),
        31: ("Conversion Content: ", "Analyzed keywords, audiences, competitors, funnels, and conversion paths; developed tests; and optimized landing pages, offers, ad copy, and creative."),
        32: ("Cross-Channel Execution: ", "Managed search, Shopping, Display, Remarketing, Video, email, social, and local campaigns using advertising editors, Excel, and analytics platforms."),
        33: ("Planning & Stakeholders: ", "Set goals, annual projections, and KPIs with senior management and partnered with web development on site changes, promotions, measurement, and business priorities."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(paragraphs[index], lead, body)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


if __name__ == "__main__":
    build_resume(OUTPUT)
    export_and_validate(OUTPUT, PDF, SCRATCH)
