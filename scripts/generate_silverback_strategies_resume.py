"""Build Scout 705's resume using the established paid-media layout."""

from pathlib import Path

import docx
from docx.shared import RGBColor

from generate_wpromote_resume import build_resume as build_paid_media_resume
from generate_wpromote_resume import set_labeled, set_plain
from generate_vitality_medical_resume import NAVY, export_and_validate


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "55b2b02b-5435-4046-8101-f4c59e56145b"
COMPANY = "Silverback-Strategies"
SCRATCH = ROOT / "scratch" / f"{COMPANY}+{JOB_KEY}"
OUTPUT = ROOT / "output" / "resumes" / f"Dave-Call+{COMPANY}+{JOB_KEY}.docx"
PDF = SCRATCH / "resume-preview.pdf"


def build_resume(path: Path = OUTPUT):
    build_paid_media_resume(path, scratch_dir=SCRATCH)
    doc = docx.Document(path)
    paragraphs = doc.paragraphs
    set_plain(paragraphs[1], "PAID MEDIA MANAGER | SEARCH, SOCIAL & CLIENT STRATEGY",
              size=11.5, bold=True, color=RGBColor(40, 70, 110))
    set_plain(paragraphs[2],
              "Lehi, UT 84043 • (530) 507-8269 • mdavidcall@gmail.com • linkedin.com/in/mdavidcall",
              size=9.5)
    set_plain(paragraphs[4],
              "Hands-on paid media marketer with 14+ years across digital marketing, ecommerce, and analytics. "
              "Agency experience includes building and managing 75+ Google Ads accounts totaling more than $276K "
              "per month, advising clients on channel strategy, and presenting performance recommendations. "
              "Combines Google and Meta campaign management with LinkedIn, TikTok, GA4, advanced Excel, creative "
              "testing, and budget analysis to connect media performance with client revenue and business goals.")

    skills = {
        6: ("Paid Search & Social: ", "Google Ads, Meta/Facebook Ads, Instagram, LinkedIn, TikTok, Microsoft/Bing Ads, Search, Shopping, Performance Max, Display, Remarketing, Video, audience targeting, and campaign optimization."),
        7: ("Client & Account Management: ", "Client consultation, channel strategy, budget allocation, performance presentations, business-needs analysis, account management, project timelines, stakeholder communication, and prioritization."),
        8: ("Analytics & Business Impact: ", "GA4, Google Tag Manager, advanced Excel, pivot tables, Tableau, Looker Studio, Funnel.io, attribution, conversion analysis, LTV, CPA, ROAS, forecasting, dashboards, and KPI development."),
        9: ("Creative Testing & Collaboration: ", "Ad copy, Adobe Creative Suite, keyword research, audience analysis, A/B and multivariate testing, landing pages, offers, conversion paths, SEO, web development, and cross-functional planning."),
        10: ("Automation & Technical Tools: ", "Python, SQL, Databricks, JavaScript, VBA, Google Ads API, monitoring scripts, reporting automation, and AI-assisted analysis using ChatGPT, Claude, Perplexity, Codex, Cursor, and AntiGravity."),
    }
    for index, (lead, body) in skills.items():
        set_labeled(paragraphs[index], lead, body, lead_color=NAVY)

    bullets = {
        12: ("Search & Audience Strategy: ", "Evaluated max CPC versus smart bidding, brand and non-brand CPA, audiences, promotions, and the mix of Performance Max and Google Shopping to guide optimization decisions."),
        16: ("Search & Social Growth: ", "Managed Google, Bing, Amazon, Meta, Instagram, and TikTok with a $400K monthly budget; increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5."),
        18: ("SEO & Web Collaboration: ", "Advised the webmaster on SEO best practices and on-page optimization, connecting website changes with channel performance and business priorities."),
        19: ("Cross-Functional Planning: ", "Created a shared inventory-planning spreadsheet and used performance reporting to support product availability, email effectiveness, and cross-platform budget decisions."),
        25: ("Agency Account Management: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month, developing recommendations around each client's business needs, budget, and performance."),
        26: ("Direct Client Strategy: ", "Worked directly with clients to allocate funds across search, display, remarketing, YouTube, social, SEO, email, and website development based on their business needs."),
        27: ("Client Reporting: ", "Consolidated data through Funnel.io and presented Looker Studio reports, translating account analysis into clear channel, budget, and optimization recommendations."),
        28: ("Testing & Quality Control: ", "Created conversion and attribution models, multivariate tests, and continuous monitoring scripts; developed a standardized Google Ads quality system adopted across the agency."),
        31: ("Ad Creative & Testing: ", "Created search and display ad copy using Adobe design software; tested bids, landing pages, and conversion paths using keyword, audience, and competitive analysis."),
    }
    for index, (lead, body) in bullets.items():
        set_labeled(paragraphs[index], lead, body)
    doc.save(path)


if __name__ == "__main__":
    build_resume()
    export_and_validate(OUTPUT, PDF, SCRATCH)
