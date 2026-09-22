"""Build and validate Scout 690's resume for Seer Interactive."""

from pathlib import Path

import docx
from docx.shared import RGBColor

from generate_wpromote_resume import build_resume as build_paid_media_resume
from generate_wpromote_resume import set_labeled, set_plain
from generate_vitality_medical_resume import NAVY, export_and_validate


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "2a3b6025-e0c8-4afa-b7c3-072c6d034579"
COMPANY = "Seer-Interactive"
SCRATCH = ROOT / "scratch" / f"{COMPANY}+{JOB_KEY}"
OUTPUT = ROOT / "output" / "resumes" / f"Dave-Call+{COMPANY}+{JOB_KEY}.docx"
PDF = SCRATCH / "resume-preview.pdf"


def build_resume(path: Path = OUTPUT):
    build_paid_media_resume(path, scratch_dir=SCRATCH)
    doc = docx.Document(path)
    paragraphs = doc.paragraphs
    set_plain(paragraphs[1], "SENIOR PAID SEARCH ACCOUNT MANAGER | DATA & AI-DRIVEN MEDIA",
              size=11.5, bold=True, color=RGBColor(40, 70, 110))
    set_plain(paragraphs[2],
              "Lehi, UT 84043 • (530) 507-8269 • mdavidcall@gmail.com • linkedin.com/in/mdavidcall",
              size=9.5)
    set_plain(paragraphs[4],
              "Senior paid media and digital marketing leader with 14+ years across paid search, paid social, ecommerce, "
              "analytics, SEO, and client strategy. Built and managed 75+ Google Ads accounts totaling more than $276K "
              "per month, advised clients on integrated channel investment, and translated large data sets into clear "
              "recommendations. Hands-on across Google, Meta, Microsoft/Bing, LinkedIn, TikTok, GA4, Excel, Tableau, "
              "Looker Studio, Python, SQL, automation, and AI-assisted workflows.")

    skills = {
        6: ("Paid Search & Cross-Channel Media: ", "Google Ads, Microsoft/Bing Ads, Meta/Facebook Ads, Instagram, LinkedIn, TikTok, Search, Shopping, Performance Max, Display, Remarketing, Video, audience targeting, and campaign optimization."),
        7: ("Client Consulting & Strategy: ", "Client consultation, account ownership, business objectives, budget allocation, KPI alignment, performance presentations, stakeholder communication, project management, and cross-functional delivery."),
        8: ("Analytics & Data Literacy: ", "GA4, Google Tag Manager, advanced Excel, pivot tables, Tableau, Looker Studio, Funnel.io, attribution, conversion analysis, LTV, CPA, ROAS, forecasting, dashboards, and KPI development."),
        9: ("Integrated Search & Testing: ", "SEO collaboration, keyword research, ad copy, landing-page recommendations, A/B and multivariate testing, conversion paths, offers, competitive analysis, and web usability."),
        10: ("Automation, AI & Technical Tools: ", "Python, SQL, Databricks, JavaScript, VBA, Google Ads API, monitoring scripts, reporting automation, machine learning, ChatGPT, Claude, Perplexity, Codex, Cursor, and AntiGravity."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(paragraphs[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Large-Scale Analysis: ", "Analyzed max CPC versus smart bidding, brand and non-brand CPA, audiences, promotions, attribution, lifetime value, Performance Max, and Google Shopping to guide media decisions."),
        13: ("Data & Forecasting: ", "Built regression-based scenarios for holdouts, geo-promotional offers, scale-ups, scale-downs, and channel reallocations, including an additional $10M investment question."),
        14: ("Automated Reporting: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms."),
        15: ("Funnel Measurement: ", "Tested reach, comparison, micro-conversion, conversion, click-to-call, and internal LTV outcomes to connect media activity with business value."),
        16: ("Paid Media Growth: ", "Managed Google, Bing, Amazon, Meta, Instagram, and TikTok with a $400K monthly budget; increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5."),
        17: ("Analytics Implementation: ", "Implemented custom GA4 and Google Tag Manager reporting and built Looker Studio KPIs supporting website, email, inventory, engineering, management, and budget decisions."),
        18: ("SEO Integration: ", "Advised the webmaster on SEO best practices and on-page optimization, connecting organic search, website changes, paid media, and business priorities."),
        19: ("AI & Automation: ", "Applied AI marketing tools, statistical modeling, custom monitoring scripts, and human-assisted JavaScript automation to improve efficiency and decision quality."),
        21: ("Ecommerce & Lead Gen: ", "Led ecommerce and marketing for a large distributor and managed paid search, outreach, lead generation, and customer acquisition across the United States, Canada, and the UK."),
        22: ("Complex Business Context: ", "Supported a complex B2B operation with 650+ retailers while expanding B2C platforms, marketplace operations, databases, and cross-functional reporting."),
        23: ("Client Portfolio: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month across clients with different industries, budgets, audiences, and objectives."),
        24: ("Integrated Recommendations: ", "Worked directly with clients to allocate funds across paid search, display, remarketing, YouTube, social, SEO, email, and website development based on business needs."),
        25: ("Client Reporting: ", "Consolidated data through Funnel.io and presented Looker Studio reporting, translating account analysis into actionable channel, budget, and optimization recommendations."),
        26: ("Testing & Attribution: ", "Created conversion and attribution models, multivariate tests, and continuous monitoring scripts; developed a standardized quality system adopted across the agency."),
        27: ("Ad Copy & Landing Pages: ", "Created search and display ad copy using Adobe design software and optimized landing pages, bids, offers, and conversion paths through keyword and audience analysis."),
        28: ("Creative Collaboration: ", "Partnered with web development and other departments on site changes, promotions, measurement, content alignment, and customer-acquisition priorities."),
        29: ("Team Leadership: ", "Led an eight-person ecommerce department and coached cross-functional stakeholders while managing paid search, outreach, lead generation, and customer acquisition."),
        30: ("Revenue & Scale: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue—35% of company revenue."),
        31: ("Account Optimization: ", "Conducted keyword, audience, competitive, funnel, and conversion-path analysis; developed bid strategies and experiments; and monitored campaign performance."),
        32: ("Cross-Channel Execution: ", "Managed Search, Shopping, Display, Remarketing, Video, email, social, local, and mobile campaigns using advertising editors, Excel, and analytics platforms."),
        33: ("Client-Facing Leadership: ", "Set goals, annual projections, and KPIs with senior management and translated large quantities of marketing data into practical decisions for technical and business teams."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(paragraphs[index], lead, body)
    doc.save(path)


if __name__ == "__main__":
    build_resume()
    export_and_validate(OUTPUT, PDF, SCRATCH)
