"""Build and validate the Gecko resume for CHG Healthcare job 5846006026."""

from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.shared import RGBColor

from generate_marksmen_growth_resume import build_resume as build_base_resume
from generate_vitality_medical_resume import NAVY, export_and_validate, set_run


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "5846006026"
COMPANY = "CHG-Healthcare"
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
        "GROWTH MARKETING | INTEGRATED CAMPAIGNS & ANALYTICS",
        size=11.5,
        bold=True,
        color=RGBColor(40, 70, 110),
    )
    set_plain(
        paragraphs[4],
        "Hands-on growth and performance marketing leader with 14+ years of experience turning customer insight, "
        "campaign data, and cross-functional strategy into measurable acquisition and revenue growth. Builds and "
        "optimizes integrated programs across paid media, email, web, SEO, content, and conversion, with advanced "
        "experience in analytics, segmentation, attribution, testing, and automation. Proven at coordinating complex "
        "initiatives across creative, sales, technology, operations, finance, and executive stakeholders while "
        "connecting channel performance to clear business outcomes.",
    )

    skills = {
        6: ("Integrated Growth Campaigns: ", "Campaign strategy and execution, audience definition, channel mix, positioning, messaging, offers, promotions, acquisition, retention, lead generation, customer segmentation, lifecycle marketing, project management, and post-campaign analysis."),
        7: ("Full-Funnel Channels: ", "Paid search, paid social, display, shopping, video, mobile, remarketing, email, websites, SEO, content strategy, landing-page optimization, CRO, A/B and multivariate testing, and conversion-path analysis."),
        8: ("Analytics & Performance: ", "CPA, CAC, LTV, ROAS, conversion tracking, attribution, GA4, Adobe Analytics, Google Tag Manager, Tableau, Looker Studio, Funnel.io, Excel, SQL, Python, Databricks, dashboards, forecasting, and revenue tracking."),
        9: ("Cross-Functional Leadership: ", "Creative, paid media, web, email, analytics, sales, product, finance, operations, IT, vendors, executive communication, team leadership, relationship management, and multi-project delivery."),
        10: ("Automation & AI: ", "Marketing automation, JavaScript, Google Ads API, ChatGPT, Claude, Perplexity, Codex, Cursor, AntiGravity, machine learning, statistical modeling, and human-reviewed AI workflows."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(paragraphs[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Portfolio & Team Leadership: ", "Managed $30 million per month with a team of four, using customer, channel, and financial analysis to guide investment and acquisition decisions."),
        13: ("Growth Planning: ", "Built regression-based scenarios to determine where an additional $10 million should be invested, evaluating holdouts, promotions, scale changes, and cross-channel reallocations."),
        14: ("Full-Funnel Experimentation: ", "Analyzed attribution, lifetime value, audiences, bidding, promotions, and reach-to-conversion tests to identify friction and guide optimization."),
        15: ("Automated Decision Support: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms."),
        16: ("Revenue Growth: ", "Increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5 across a $400K monthly marketing budget."),
        17: ("Integrated Channel Ownership: ", "Managed Google, Bing, Amazon, Facebook, Instagram, and TikTok while guiding SEO, website optimization, email effectiveness, and cross-platform budget decisions."),
        18: ("Cross-Functional Visibility: ", "Built Looker Studio KPIs connecting marketing performance with inventory, engineering, management, web development, email, and operating priorities."),
        19: ("Measurement Infrastructure: ", "Implemented custom GA4 and Google Tag Manager reporting and created a planning methodology used across multiple departments."),
        21: ("B2B Growth & Digital Transformation: ", "Led ecommerce and marketing for a large B2B distributor, building a functional digital environment and expanding into B2C platforms while supporting 650+ retail partners."),
        22: ("Market & Channel Expansion: ", "Developed ecommerce-specific products with manufacturers, improved supply-chain processes, and expanded Amazon operations into CastleGate, Target.com, Costco.com, and other channels."),
        23: ("Opportunity Analysis: ", "Performed daily financial and market analysis to identify niches, guide product development, and evaluate initiatives through project-level cost/benefit decisions."),
        24: ("Stakeholder Alignment: ", "Worked with IT, operations, finance, product development, HR, and sales leaders to drive technology, process, cultural, and operating change."),
        25: ("Client Campaign Strategy: ", "Advised clients on allocating marketing funds across websites, SEO, email, paid search, display, mobile, remarketing, YouTube, and social based on business needs."),
        26: ("Multi-Account Execution: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month while maintaining a standardized service-quality system adopted agency-wide."),
        27: ("Campaign Testing: ", "Created conversion and attribution models and multivariate tests to improve audience, message, channel, and landing-page decisions."),
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
