"""Build and validate the Gecko resume for Boostability job 5860301709."""

from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.shared import RGBColor

from generate_marksmen_growth_resume import build_resume as build_base_resume
from generate_vitality_medical_resume import NAVY, export_and_validate, set_run


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "5860301709"
COMPANY = "Boostability"
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


def build_resume(path: Path):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    build_base_resume(TEMPLATE)
    doc = docx.Document(TEMPLATE)
    paragraphs = doc.paragraphs

    set_plain(
        paragraphs[1],
        "SENIOR GROWTH MARKETING | B2B DEMAND GENERATION",
        size=11.5,
        bold=True,
        color=RGBColor(40, 70, 110),
    )
    set_plain(
        paragraphs[4],
        "Hands-on growth marketing leader with 14+ years of experience turning customer insight, campaign data, "
        "and cross-functional strategy into measurable acquisition and revenue growth. Combines B2B and B2C "
        "leadership with direct execution across demand generation, audience segmentation, paid media, email, "
        "CRM, content, web, automation, testing, and conversion optimization. Experienced coordinating complex "
        "initiatives across sales, operations, finance, product, technology, and executive stakeholders while "
        "building dashboards and recommendations that connect marketing activity to business outcomes.",
    )

    skills = {
        6: ("Growth & Demand Generation: ", "Integrated campaign strategy and execution, customer acquisition, lead generation, audience and customer segmentation, demographic and psychographic analysis, positioning, messaging, offers, content strategy, lifecycle marketing, CRO, and A/B/multivariate testing."),
        7: ("B2B Go-to-Market & Leadership: ", "B2B and B2C strategy, account and relationship management, client consulting, product and channel launches, sales support, cross-functional planning, project management, financial analysis, and executive communication."),
        8: ("CRM, Email & Automation: ", "HubSpot, Salesforce, Marketo, Pardot, Zoho CRM, Salesforce Marketing Cloud, Adobe Campaign, Mailchimp, Klaviyo, email automation, segmentation, retention, deliverability, and email testing."),
        9: ("Analytics & Pipeline Measurement: ", "GA4, Google Tag Manager, Tableau, Looker Studio, Funnel.io, Adobe Analytics, SQL, Python, Excel, attribution, funnel analysis, LTV, CAC, ROI, revenue tracking, dashboards, and forecasting."),
        10: ("Paid Media, Web & AI: ", "Google Ads, LinkedIn, Meta Ads, Bing Ads, Amazon, WordPress, Shopify, Magento, HTML5, CSS3, JavaScript, ChatGPT, Claude, Perplexity, Codex, Cursor, and AntiGravity."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(paragraphs[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Portfolio & Team Leadership: ", "Managed $30 million per month with a team of four, using customer, channel, and financial analysis to guide investment and acquisition decisions."),
        13: ("Growth Planning: ", "Built regression-based scenarios to determine where an additional $10 million should be invested, evaluating holdouts, promotions, scale changes, and cross-channel reallocations."),
        14: ("Audience & Funnel Analysis: ", "Analyzed attribution, lifetime value, audiences, bidding, promotions, and full-funnel reach-to-conversion tests to identify actionable growth opportunities."),
        15: ("Automated Reporting: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms."),
        16: ("Revenue Growth: ", "Increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5 across a $400K monthly marketing budget."),
        17: ("Integrated Channel Ownership: ", "Managed Google, Bing, Amazon, Facebook, Instagram, and TikTok while guiding SEO, website optimization, email effectiveness, and cross-platform budget decisions."),
        18: ("Cross-Functional Visibility: ", "Built Looker Studio KPIs connecting marketing performance with inventory, engineering, management, web development, email, and operating priorities."),
        19: ("Measurement Infrastructure: ", "Implemented custom GA4 and Google Tag Manager reporting and created a planning methodology used across multiple departments."),
        21: ("B2B Growth & Transformation: ", "Led ecommerce and marketing for a large B2B distributor, building a functional digital environment and expanding into B2C platforms while supporting 650+ retail partners."),
        22: ("Go-to-Market Expansion: ", "Developed ecommerce-specific products with manufacturers, improved supply-chain processes, and expanded Amazon operations into CastleGate, Target.com, Costco.com, and other channels."),
        23: ("Market Opportunity Analysis: ", "Performed daily financial and market analysis to identify niches, guide product development, and evaluate initiatives through project-level cost/benefit decisions."),
        24: ("Sales & Operations Alignment: ", "Worked with IT, operations, finance, product development, HR, and sales leaders to drive technology, process, cultural, and operating change."),
        25: ("Client Campaign Strategy: ", "Advised clients on allocating marketing funds across websites, SEO, email, paid search, display, mobile, remarketing, YouTube, and social based on business needs."),
        26: ("Multi-Account Execution: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month while maintaining a standardized service-quality system adopted agency-wide."),
        27: ("Campaign Optimization: ", "Created conversion and attribution models and multivariate tests to improve audience, message, channel, and landing-page decisions."),
        28: ("Marketing Automation: ", "Developed custom scripts for continuous campaign monitoring, budget oversight, and faster performance issue identification."),
        29: ("Acquisition Leadership: ", "Led an eight-person ecommerce team responsible for paid search, outreach, lead generation, and customer acquisition in the United States, Canada, and the UK."),
        30: ("Revenue Impact: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue—35% of company revenue."),
        31: ("Multi-Channel Campaigns: ", "Performed audience, keyword, channel, and competitive research; created ad copy and creative; and managed email, shopping, video, social, local, and remarketing programs."),
        32: ("Funnel & Conversion Testing: ", "Built attribution models, analyzed funnels and conversion paths, optimized landing pages, and ran A/B and multivariate tests to improve acquisition performance."),
        33: ("Executive Planning: ", "Established annual goals, projections, and KPIs with senior management and reported business performance using Magento, Google Analytics, ACCTivate, and QuickBooks."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(paragraphs[index], lead, body)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


if __name__ == "__main__":
    build_resume(OUTPUT)
    export_and_validate(OUTPUT, PDF, SCRATCH)
