"""Build and validate Scout 701's resume for Incorta."""

from pathlib import Path

import docx
from docx.shared import RGBColor

from generate_wpromote_resume import build_resume as build_paid_media_resume
from generate_wpromote_resume import set_labeled, set_plain
from generate_vitality_medical_resume import NAVY, export_and_validate


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "f813a666-81a8-45be-ba2f-9f447edce30e"
COMPANY = "Incorta"
SCRATCH = ROOT / "scratch" / f"{COMPANY}+{JOB_KEY}"
OUTPUT = ROOT / "output" / "resumes" / f"Dave-Call+{COMPANY}+{JOB_KEY}.docx"
PDF = SCRATCH / "resume-preview.pdf"


def build_resume(path: Path = OUTPUT):
    build_paid_media_resume(path, scratch_dir=SCRATCH)
    doc = docx.Document(path)
    paragraphs = doc.paragraphs
    set_plain(paragraphs[1], "WEB & DIGITAL MARKETING MANAGER | PAID MEDIA & ANALYTICS",
              size=11.5, bold=True, color=RGBColor(40, 70, 110))
    set_plain(paragraphs[2],
              "Lehi, UT 84043 • (530) 507-8269 • mdavidcall@gmail.com • linkedin.com/in/mdavidcall",
              size=9.5)
    set_plain(paragraphs[4],
              "Hands-on web and digital marketing leader with 14+ years managing paid media, ecommerce, analytics, SEO, "
              "web platforms, and technical marketing operations. Built and managed 75+ Google Ads accounts totaling "
              "more than $276K per month, led $400K monthly programs, and created reporting systems that connect web "
              "behavior, conversion paths, channel performance, and budget decisions. Brings practical fluency in GA4, "
              "Google Tag Manager, HTML, CSS, JavaScript, Python, SQL, WordPress, Magento, HubSpot, Salesforce, and automation.")

    skills = {
        6: ("Web & Technical Marketing: ", "HTML5, CSS3, JavaScript, PHP, WordPress, Magento, Shopify, website management, web development collaboration, landing pages, responsive experiences, UX, SEO, metadata, and site structure."),
        7: ("Digital Advertising: ", "Google Ads, Microsoft/Bing Ads, Meta/Facebook Ads, Instagram, LinkedIn, TikTok, Search, Shopping, Performance Max, Display, Remarketing, Video, audience targeting, and budget management."),
        8: ("Analytics & Measurement: ", "GA4, Google Analytics, Google Tag Manager, Adobe Analytics, Tableau, Looker Studio, Funnel.io, Excel, SQL, Databricks, attribution, conversion analysis, forecasting, dashboards, and KPI development."),
        9: ("MarTech & Data Operations: ", "HubSpot, Salesforce, Pardot, marketing automation, databases, CRM-aware lead generation, Google Ads API, reporting workflows, data quality, and cross-functional technology delivery."),
        10: ("CRO, Automation & AI: ", "A/B and multivariate testing, conversion paths, landing-page optimization, Python, VBA, monitoring scripts, statistical modeling, machine learning, ChatGPT, Claude, Perplexity, Codex, Cursor, and AntiGravity."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(paragraphs[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Web & Channel Analysis: ", "Analyzed max CPC versus smart bidding, audiences, attribution, lifetime value, Performance Max, Google Shopping, and conversion behavior to guide channel and budget decisions."),
        13: ("Reporting Architecture: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms."),
        14: ("Forecasting & ROI: ", "Built regression-based scenarios for holdouts, geo-promotional offers, scale-ups, scale-downs, and channel reallocations, including an additional $10M investment question."),
        15: ("Funnel Measurement: ", "Tested reach, comparison, micro-conversion, conversion, click-to-call, and internal LTV outcomes to connect web and media activity with business value."),
        16: ("Paid Media Leadership: ", "Managed Google, Bing, Amazon, Meta, Instagram, and TikTok with a $400K monthly budget; increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5."),
        17: ("GA4 & GTM Implementation: ", "Implemented custom GA4 and Google Tag Manager reporting and built Looker Studio KPIs supporting website, email, inventory, engineering, management, and budget decisions."),
        18: ("Technical SEO: ", "Advised the webmaster on SEO best practices and on-page optimization, connecting site changes, content, conversion paths, organic search, and paid performance."),
        19: ("Automation & Data Quality: ", "Applied statistical modeling, custom monitoring scripts, JavaScript automation, databases, and repeatable reporting processes to improve efficiency and decision quality."),
        21: ("B2B Web Transformation: ", "Led ecommerce and marketing for a large B2B distributor, lifting the company from a traditional operating model into a functional digital environment."),
        22: ("Ecommerce Platform Delivery: ", "Expanded multiple B2C ecommerce platforms while supporting 650+ retailers, Amazon Vendor and Seller Central, CastleGate, Target.com, Costco.com, and related systems."),
        23: ("Web & Database Operations: ", "Managed multiple databases and ERP information architecture, improving consistency among departments and producing accurate financial and marketing reports."),
        24: ("Cross-Functional Technology: ", "Worked with IT, operations, finance, product development, HR, sales, web development, and senior management on changing priorities and process improvement."),
        25: ("Agency Advertising Portfolio: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month across clients with different industries, budgets, audiences, and objectives."),
        26: ("Integrated Campaign Strategy: ", "Worked directly with clients to allocate funds across paid search, display, remarketing, YouTube, social, SEO, email, and website development based on business needs."),
        27: ("Dashboards & Attribution: ", "Consolidated data through Funnel.io, presented Looker Studio reporting, and created conversion and attribution models to clarify performance and next steps."),
        28: ("CRO & Testing: ", "Created multivariate tests, bid experiments, conversion-path analyses, landing-page improvements, and a standardized advertising quality system adopted across the agency."),
        29: ("Web-Connected Team Leadership: ", "Led an eight-person ecommerce department responsible for paid search, outreach, lead generation, customer acquisition, web coordination, and reporting."),
        30: ("Revenue & Scale: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue—35% of company revenue."),
        31: ("Front-End Marketing Execution: ", "Conducted keyword, audience, competitive, funnel, and conversion-path analysis; developed ad copy, bid strategies, experiments, and landing-page recommendations."),
        32: ("Full-Funnel Programs: ", "Managed Search, Shopping, Display, Remarketing, Video, email, social, local, and mobile campaigns using advertising editors, Excel, and analytics platforms."),
        33: ("Executive Reporting: ", "Set goals, annual projections, and KPIs with senior management and translated large quantities of technical and performance data into practical decisions."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(paragraphs[index], lead, body)
    doc.save(path)


if __name__ == "__main__":
    build_resume()
    export_and_validate(OUTPUT, PDF, SCRATCH)
