"""Build the source-grounded performance marketing resume for Scout 723."""

from pathlib import Path

import docx
from docx.shared import Inches, RGBColor

from generate_wpromote_resume import build_resume as build_base_resume
from generate_wpromote_resume import set_labeled, set_plain
from generate_vitality_medical_resume import NAVY

ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "ea0ef6ae-ff42-4637-a9d9-3d23286980c1"
COMPANY = "CSC-Generation"
SCRATCH = ROOT / "scratch" / f"{COMPANY}+{JOB_KEY}"
OUTPUT = ROOT / "output" / "resumes" / f"Dave-Call+{COMPANY}+{JOB_KEY}.docx"


def build_resume(path: Path = OUTPUT):
    build_base_resume(path, scratch_dir=SCRATCH)
    doc = docx.Document(path)
    for section in doc.sections:
        section.top_margin = Inches(0.45)
        section.bottom_margin = Inches(0.45)
    p = doc.paragraphs
    set_plain(p[1], "PERFORMANCE MARKETING & ECOMMERCE LEADER", size=11.5,
              bold=True, color=RGBColor(40, 70, 110))
    set_plain(p[2], "Lehi, UT  |  (530) 507-8269  |  mdavidcall@gmail.com  |  linkedin.com/in/mdavidcall", size=9.5)
    set_plain(p[4],
              "Performance marketing leader with 14+ years across paid media, ecommerce, and analytics. "
              "Managed up to $30 million per month with a team of four. Combines hands-on Google and Meta campaign "
              "management with incrementality analysis, customer lifetime value, forecasting, and reporting automation. "
              "Led an eight-person ecommerce department and partnered with senior management, product, finance, "
              "and web teams to connect acquisition strategy with revenue, inventory, and customer experience.")

    skills = {
        6: ("Paid Media & Acquisition: ", "Google Ads, Meta, Microsoft Ads, Amazon, Instagram, TikTok, paid search, paid social, Shopping, Performance Max, display, remarketing, video, and affiliate marketing."),
        7: ("Measurement & Testing: ", "Incremental testing, holdouts, LTV, CPA, ROAS, attribution, A/B and multivariate testing, audience analysis, landing pages, and conversion optimization."),
        8: ("Analytics & Planning: ", "GA4, Google Tag Manager, Tableau, Looker Studio, Funnel.io, Excel, regression models, forecasting, budget allocation, KPI development, and performance reporting."),
        9: ("Leadership & Commerce: ", "Team management, client strategy, cross-functional collaboration, inventory reporting, product investment analysis, financial reporting, Magento, Shopify, and Amazon Marketing Services."),
        10: ("Automation & Account Operations: ", "Python, SQL, Databricks, automated reporting, campaign monitoring scripts, Google Ads Editor, campaign activation, quality assurance, budget pacing, and daily optimization."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(p[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Investment Strategy: ", "Used regression models, holdouts, geo tests, scale-up/down analysis, and budget reallocation scenarios to forecast outcomes and present investment recommendations."),
        13: ("Incrementality & Customer Value: ", "Analyzed incremental CPA, customer lifetime value, data-driven attribution, brand/non-brand bidding, audience performance, and the Performance Max/Shopping mix."),
        14: ("Customer Journey Analysis: ", "Evaluated reach, micro-conversions, purchase, click-to-call, and lifetime value to identify opportunities to scale search performance and improve budget decisions."),
        15: ("Reporting Automation: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms."),
        16: ("Paid Media Growth: ", "Managed Google, Microsoft Ads, Amazon, Meta, Instagram, and TikTok with an approximately $400K monthly budget; increased monthly volume fourfold while improving ROAS from 1.5 to 3.5."),
        17: ("Business Visibility: ", "Built Looker Studio KPI dashboards supporting campaign pacing, website performance, inventory planning, and leadership decisions."),
        18: ("Measurement & Optimization: ", "Configured GA4 and Google Tag Manager measurement; improved results through bidding strategy, audience analysis, campaign testing, and conversion review."),
        19: ("Cross-Functional Delivery: ", "Coordinated search and broader channel strategy with website, SEO, operations, and creative priorities to support efficient delivery and profitable growth."),
        21: ("Commerce Leadership: ", "Led ecommerce and marketing for a large B2B distributor, adding multiple B2C platforms while supporting 650+ retail partners."),
        22: ("Systems & Reporting: ", "Maintained marketing databases, financial reporting, and cross-channel systems to improve budget visibility, data consistency, collaboration, and decisions."),
        23: ("Commercial Decisions: ", "Applied project-by-project cost-benefit analysis to prioritize growth initiatives, marketplace opportunities, product investments, and operational improvements."),
        24: ("Cross-Functional Leadership: ", "Coordinated marketing execution and reporting with sales, operations, finance, IT, and product teams while modernizing the company's digital environment."),
        25: ("Agency Account Portfolio: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month across clients with distinct business needs and budgets."),
        26: ("Channel Strategy: ", "Advised clients on allocating funds across search, display, remarketing, YouTube, social, SEO, email, and website development based on business goals and account analysis."),
        27: ("Performance Communication: ", "Consolidated data through Funnel.io and presented Looker Studio reports to support client decisions about performance and marketing investment."),
        28: ("Testing & Quality Standards: ", "Created conversion, attribution, A/B and multivariate testing frameworks, automated monitoring scripts, and a repeatable account-management system adopted across the agency."),
        29: ("Team & Acquisition Leadership: ", "Led an eight-person ecommerce team responsible for paid search, customer acquisition, campaign delivery, website performance, and growth in the United States, Canada, and UK."),
        30: ("Revenue & Scale: ", "Managed 150+ campaigns with approximately $400K in monthly spend, generating more than $9M in revenue and 35% of company sales."),
        31: ("Creative & Conversion Testing: ", "Directed keyword strategy, bid experiments, landing-page optimization, ad copy, audience analysis, conversion optimization, attribution, and A/B and multivariate testing."),
        32: ("Channel Execution: ", "Managed Google Ads, Microsoft Ads, and Amazon campaigns across search, shopping, display, video, remarketing, mobile, social, local, and email."),
        33: ("Executive Planning: ", "Created annual projections and KPI reporting with senior leadership; used platform, analytics, Magento, accounting, and competitive data to guide budget and campaign decisions."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(p[index], lead, body)
    set_plain(p[34], "EDUCATION & CERTIFICATIONS", bold=True, color=NAVY)
    set_plain(p[35], "Bachelor of Science, Business Management — Brigham Young University", bold=True)
    p[36]._element.getparent().remove(p[36]._element)
    set_labeled(p[37], "Certifications: ", "Google Ads • Google Analytics • Microsoft Ads • Meta Blueprint • Amazon Marketing Services", lead_color=NAVY)
    doc.save(path)
    print(path)


if __name__ == "__main__":
    build_resume()
