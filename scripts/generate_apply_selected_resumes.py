"""Generate the reviewed Apply? selections with direct master-DOCX evidence."""

import argparse
import json
from pathlib import Path

import docx
from docx.shared import Inches, RGBColor

from generate_wpromote_resume import build_resume as build_layout
from generate_wpromote_resume import set_labeled, set_plain
from generate_vitality_medical_resume import NAVY
from gecko_v2 import source_text, source_hashes, extract_evidence, master_identity, master_jobs

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {
    708: {
        "company": "Jobscan", "key": "103299c7-8c4d-4ccd-b281-da31b5b0beb6",
        "headline": "GROWTH MARKETING | CONVERSION, ANALYTICS & ACQUISITION",
        "summary": "Digital marketing professional with 14+ years across customer acquisition, ecommerce, and multi-channel growth. Combines keyword research, ad copy, SEO collaboration, landing-page optimization, and conversion testing with GA4 and performance analysis. Led an eight-person ecommerce team, advised agency clients on website and channel strategy, and helped expand a B2B distributor into multiple B2C channels. Brings a hands-on approach to translating customer journey data into tests, priorities, and measurable business results.",
        "skills": [
            ["Conversion & Customer Journeys: ", "Landing-page optimization, conversion rate optimization, A/B and multivariate testing, attribution, micro-conversions, LTV, customer acquisition, and audience analysis."],
            ["Search & Messaging: ", "SEO, keyword and competitive research, ad copy, targeting and messaging recommendations, paid search, audience segmentation, and website strategy."],
            ["Analytics & Reporting: ", "GA4, Google Tag Manager, Looker Studio, Tableau, Funnel.io, Excel, KPI reporting, regression models, forecasting, and financial analysis."],
            ["Commerce & Collaboration: ", "B2B/B2C ecommerce, Shopify, Magento, email channel experience, client presentations, team leadership, cross-functional coordination, and documentation of learnings."],
            ["Execution & Automation: ", "Python, SQL, Databricks, automated reporting, monitoring scripts, campaign quality assurance, Google Ads, Microsoft Ads, Meta, and Amazon."],
        ],
        "order": [[1,2,3,0],[1,2,3,0],[1,0,2,3],[2,1,3,0],[2,0,3,1]],
    },
    37: {
        "company": "Bamboo-Insurance", "key": "5846794031",
        "headline": "DIRECTOR OF PERFORMANCE MARKETING | STRATEGY & ANALYTICS",
        "summary": "Performance marketing leader with 14+ years across paid search, ecommerce, and multi-channel acquisition. Managed up to $30 million per month in paid media with a four-person team. Combines hands-on Google, Microsoft Ads, and Meta execution with attribution, customer journey analysis, forecasting, and budget allocation. Experienced in ad copy, audience and bidding tests, reporting automation, and presenting investment recommendations, with a practical focus on acquisition efficiency and revenue growth.",
        "skills": [
            ["Paid Media & Acquisition: ", "Google Ads, Microsoft Ads, Meta, Amazon, Instagram, TikTok, Search, Shopping, Performance Max, Display, YouTube, remarketing, and SEO."],
            ["Testing & Creative: ", "Ad copy, keyword and competitive research, audience segmentation, targeting and messaging recommendations, bid experiments, landing pages, A/B testing, and multivariate testing."],
            ["Measurement & Economics: ", "GA4, Google Tag Manager, attribution, CPC, CPA, ROAS, LTV, conversion tracking, incremental testing, holdouts, regression models, forecasting, and budget scenarios."],
            ["Reporting & Automation: ", "Excel, Tableau, Looker Studio, Funnel.io, Python, SQL, Databricks, automated reporting, campaign monitoring, KPI development, and financial analysis."],
            ["Leadership & Delivery: ", "Budget allocation, senior leadership reporting, client consultation, cross-functional collaboration, team management, campaign builds, quality assurance, pacing, and daily optimization."],
        ],
        "order": [[3,0,1,2],[0,1,2,3],[3,2,0,1],[1,2,3,0],[2,3,0,1]],
    },
}

LABELS = [
    ["Bidding & Audience Analysis: ", "Customer Journey Analysis: ", "Reporting Automation: ", "Investment Planning: "],
    ["Channel Ownership: ", "Growth & Efficiency: ", "Measurement & Visibility: ", "Cross-Functional Execution: "],
    ["Digital Leadership: ", "B2C Expansion: ", "Data & Reporting: ", "Commercial Priorities: "],
    ["Agency Account Scale: ", "Client Strategy: ", "Research & Testing: ", "Reporting & Repeatable Processes: "],
    ["Team Leadership: ", "Campaign Execution: ", "Conversion Optimization: ", "Executive Planning: "],
]


def build_resume(scout_id: int):
    cfg = CONFIG[scout_id]
    scratch = ROOT / "scratch" / f"{cfg['company']}+{cfg['key']}"
    output = ROOT / "output/resumes" / f"Dave-Call+{cfg['company']}+{cfg['key']}.docx"
    # Re-read the authoritative DOCX for each job, including all tables.
    source = source_text()
    evidence = extract_evidence(source)
    identity, jobs = master_identity(), master_jobs()
    build_layout(output, scratch_dir=scratch)
    doc = docx.Document(output)
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Inches(.45)
    p = doc.paragraphs
    set_plain(p[0], identity["name"], size=19, bold=True, color=NAVY)
    set_plain(p[1], cfg["headline"], size=11.5, bold=True, color=RGBColor(40,70,110))
    set_plain(p[2], identity["contact"], size=9.5)
    for index, title in [(3,"PROFESSIONAL SUMMARY"),(5,"CORE COMPETENCIES & TECHNICAL SKILLS"),(11,"PROFESSIONAL EXPERIENCE"),(34,"EDUCATION & CERTIFICATIONS")]:
        set_plain(p[index], title, bold=True, color=NAVY)
    set_plain(p[4], cfg["summary"])
    for index,(lead,body) in enumerate(cfg["skills"],6):
        set_labeled(p[index],lead,body,lead_color=NAVY)
    used=[]
    for job_index,start in enumerate([12,16,21,25,29]):
        pool=[e for e in evidence[:20] if e["job"]==job_index]
        assert len(pool)==4
        for offset,source_index in enumerate(cfg["order"][job_index]):
            e=pool[source_index]
            set_labeled(p[start+offset],LABELS[job_index][source_index],e["quote"])
            used.append(e)
    # Selected-results evidence explicitly supports this metric at LifeSpan.
    result=evidence[23]
    set_labeled(p[33],"Revenue Impact: ",result["quote"])
    used.append(result)
    for table,job in zip(doc.tables,jobs,strict=True):
        set_plain(table.cell(0,0).paragraphs[0],f"{job['title']} | {job['company']} — {job['location']}",bold=True,color=NAVY)
        table.cell(0,1).text=""
    set_plain(p[35],identity["education"],bold=True)
    p[36]._element.getparent().remove(p[36]._element)
    set_plain(p[37],identity["certifications"])
    doc.save(output)
    (scratch/"generation-evidence.json").write_text(json.dumps({"scout_id":scout_id,"source_hashes":source_hashes(),"config":cfg,"selected_evidence":used},indent=2),encoding="utf-8")
    print(output)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("scout_id",type=int,choices=list(CONFIG))
    build_resume(parser.parse_args().scout_id)
