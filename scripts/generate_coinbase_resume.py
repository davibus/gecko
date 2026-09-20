"""Build and validate the Gecko resume for Coinbase job 5890507483."""

from pathlib import Path
import docx
from docx.oxml.ns import qn
from docx.shared import RGBColor

from generate_marksmen_growth_resume import build_resume as build_base_resume
from generate_vitality_medical_resume import NAVY, export_and_validate, set_run


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "5890507483"
COMPANY = "Coinbase"
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
        "SENIOR PERFORMANCE MARKETING | PAID SOCIAL & MOBILE",
        size=11.5,
        bold=True,
        color=RGBColor(40, 70, 110),
    )
    set_plain(
        paragraphs[4],
        "Performance marketing leader with 14+ years of hands-on experience scaling B2C customer acquisition "
        "across paid social, mobile, search, video, display, and ecommerce. Combines strategy with direct execution "
        "across Meta, TikTok, audience development, creative and landing-page testing, attribution, budget allocation, "
        "and performance reporting. Proven managing large media portfolios, improving acquisition efficiency, and "
        "turning complex data into clear investment decisions. Builds practical automation and AI-assisted workflows "
        "while maintaining human review, disciplined experimentation, and strong cross-functional partnership.",
    )

    skills = {
        6: ("Paid Social & Mobile Acquisition: ", "Meta/Facebook/Instagram, TikTok, Snapchat, YouTube, Google Ads, Bing Ads, Amazon, display, mobile campaigns, remarketing, audience development, bidding strategy, and budget allocation."),
        7: ("Measurement & Experimentation: ", "GA4, Google Tag Manager, conversion tracking, data-driven attribution, holdouts, incremental CPA analysis, LTV, CAC, ROAS, funnels, conversion paths, A/B and multivariate testing."),
        8: ("Analytics & Reporting: ", "Tableau, Looker Studio, Funnel.io, Adobe Analytics, Excel, Python, SQL, Databricks, regression analysis, forecasting, automated reporting, KPI dashboards, and performance narratives."),
        9: ("Creative & Conversion: ", "Creative strategy, ad copy and design, audience and message testing, landing-page optimization, CRO, offers, promotions, full-funnel analysis, and website collaboration."),
        10: ("Leadership, Automation & AI: ", "Team leadership, executive communication, cross-functional delivery, project management, JavaScript, Google Ads API, ChatGPT, Claude, Perplexity, Codex, Cursor, AntiGravity, and marketing automation."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(paragraphs[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Portfolio & Team Leadership: ", "Managed $30 million per month with a team of four, using channel, customer, and financial analysis to guide investment, acquisition, and portfolio decisions."),
        13: ("Experimentation Strategy: ", "Evaluated brand holdouts, geo promotions, scale changes, max-CPC versus smart bidding, audiences, lifetime value, data-driven attribution, and full-funnel tests."),
        14: ("Investment Modeling: ", "Built five-year projections and regression-based scenarios to forecast outcomes and recommend how an additional $10 million should be allocated across channels, promotions, and tests."),
        15: ("Analytics Automation: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to blend data and automate accurate weekly reporting across more than 10 marketing platforms."),
        16: ("Paid Social Ownership: ", "Managed Facebook, Instagram, and TikTok alongside Google, Bing, and Amazon across a $400K monthly marketing budget, personally connecting channel activity to growth goals."),
        17: ("Acquisition Efficiency: ", "Increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5 through hands-on analysis, testing, and optimization."),
        18: ("Measurement & Dashboards: ", "Implemented custom GA4 and Google Tag Manager reporting and built Looker Studio KPIs connecting acquisition results with inventory, engineering, and management priorities."),
        19: ("Cross-Functional Execution: ", "Partnered across inventory, engineering, management, web development, and email while guiding SEO, website optimization, planning, and cross-platform budget decisions."),
        21: ("Growth-System Development: ", "Led all aspects of ecommerce and marketing for a large B2B distributor, built a functional digital environment, and expanded into B2C channels while supporting 650+ retail partners."),
        22: ("Opportunity Analysis: ", "Used daily financial and market analysis and project-by-project cost/benefit decisions to identify niches, guide product development, evaluate channel economics, and prioritize revenue opportunities."),
        23: ("Platform Expansion: ", "Developed ecommerce-specific products with manufacturers, improved supply-chain processes, and expanded Amazon operations into CastleGate, Target.com, Costco.com, and other channels."),
        24: ("Cross-Functional Leadership: ", "Worked with IT, operations, finance, product development, HR, and sales to implement technology, process, cultural, and operating change and improve collaboration."),
        25: ("Multi-Channel Acquisition: ", "Advised clients on paid search, display, mobile, remarketing, YouTube, social, websites, SEO, and email, translating business needs and analytical findings into channel plans."),
        26: ("Hands-On Campaign Scale: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month and created a standardized quality system adopted agency-wide across clients of different sizes."),
        27: ("Attribution & Testing: ", "Developed conversion and attribution models and multivariate tests to improve audience, message, channel, and landing-page decisions, then consolidated reporting in Funnel.io and Looker Studio."),
        28: ("Campaign Automation: ", "Created custom scripts for continuous monitoring of client marketing activity, budget oversight, and faster identification of performance problems across a multi-account portfolio."),
        29: ("Multi-Market Acquisition: ", "Led an eight-person ecommerce team responsible for paid search, outreach, lead generation, and customer acquisition in the United States, Canada, and the UK."),
        30: ("Revenue Impact: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue - 35% of company revenue - through disciplined acquisition management."),
        31: ("Creative & Channel Execution: ", "Performed keyword, audience, channel, trend, and competitive research; created ad copy and creative with Adobe tools; and managed display, mobile, video, social, email, shopping, and remarketing programs."),
        32: ("Conversion Optimization: ", "Built attribution models, analyzed funnels and conversion paths, optimized landing pages, developed bid strategies and experiments, and ran A/B and multivariate tests to improve acquisition performance."),
        33: ("Performance Management: ", "Established annual goals, projections, and KPIs with senior management and reported large volumes of business data using Google Analytics, Magento, ACCTivate, QuickBooks, Excel, and platform analytics."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(paragraphs[index], lead, body)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


if __name__ == "__main__":
    build_resume(OUTPUT)
    export_and_validate(OUTPUT, PDF, SCRATCH)
