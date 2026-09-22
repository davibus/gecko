"""Build and validate the Gecko resume for Unicity USA Inc job -1765374300165839452."""

from pathlib import Path

import docx
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Inches, Pt, RGBColor

from generate_vitality_medical_resume import (
    BODY_SIZE, FONT, LINE_SPACING, MUTED, NAVY, TEXT, export_and_validate,
    keep_table_together, remove_table_borders, set_cell_margins, set_run,
)


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "-1765374300165839452"
COMPANY = "Unicity-USA-Inc"
OUTPUT = ROOT / "output" / "resumes" / f"Dave-Call+{COMPANY}+{JOB_KEY}.docx"
SCRATCH = ROOT / "scratch" / f"{COMPANY}+{JOB_KEY}"
PDF = SCRATCH / "resume-preview.pdf"


def build_resume(path: Path):
    doc = docx.Document()
    for section in doc.sections:
        section.top_margin = Inches(0.36)
        section.bottom_margin = Inches(0.36)
        section.left_margin = Inches(0.48)
        section.right_margin = Inches(0.48)
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(BODY_SIZE)
    normal.font.color.rgb = TEXT
    normal.paragraph_format.line_spacing = LINE_SPACING
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)
    doc.styles["List Bullet"].font.name = FONT
    doc.styles["List Bullet"].font.size = Pt(BODY_SIZE)

    def paragraph(after=0, before=0, keep=False, align=None):
        p = doc.add_paragraph()
        p.paragraph_format.line_spacing = LINE_SPACING
        p.paragraph_format.space_before = Pt(before)
        p.paragraph_format.space_after = Pt(after)
        p.paragraph_format.keep_with_next = keep
        if align is not None:
            p.alignment = align
        return p

    def section_header(title, before=3.0):
        p = paragraph(after=1.5, before=before, keep=True)
        set_run(p.add_run(title.upper()), size=11, bold=True, color=NAVY)
        p._p.get_or_add_pPr().append(parse_xml(
            f'<w:pBdr {nsdecls("w")}><w:bottom w:val="single" '
            'w:sz="6" w:space="1" w:color="102C57"/></w:pBdr>'
        ))

    def job_header(title, company, location, before=1.0):
        table = doc.add_table(rows=1, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        remove_table_borders(table)
        keep_table_together(table)
        for index, width in enumerate((Inches(5.95), Inches(1.55))):
            cell = table.cell(0, index)
            cell.width = width
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell)
        left = table.cell(0, 0).paragraphs[0]
        left.paragraph_format.space_before = Pt(before)
        left.paragraph_format.space_after = Pt(0.5)
        left.paragraph_format.line_spacing = LINE_SPACING
        left.paragraph_format.keep_with_next = True
        set_run(left.add_run(title), bold=True, color=NAVY)
        set_run(left.add_run(" | "), color=MUTED)
        set_run(left.add_run(f"{company} — {location}"), bold=True)
        right = table.cell(0, 1).paragraphs[0]
        right.paragraph_format.space_before = Pt(before)
        right.paragraph_format.space_after = Pt(0.5)
        right.paragraph_format.keep_with_next = True
        # Intentionally blank: preserve Gecko's right-side date cell without visible dates.

    def bullet(lead, body, after=0.2):
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.left_indent = Inches(0.18)
        p.paragraph_format.first_line_indent = Inches(-0.02)
        p.paragraph_format.line_spacing = LINE_SPACING
        p.paragraph_format.space_after = Pt(after)
        set_run(p.add_run(lead), bold=True)
        set_run(p.add_run(body))

    def skill(lead, body, after=0.8):
        p = paragraph(after=after)
        p.paragraph_format.left_indent = Inches(0.10)
        set_run(p.add_run(lead), bold=True, color=NAVY)
        set_run(p.add_run(body))

    p = paragraph(after=0.5, align=WD_ALIGN_PARAGRAPH.CENTER)
    set_run(p.add_run("DAVE CALL"), size=19, bold=True, color=NAVY)
    p = paragraph(after=1.2, align=WD_ALIGN_PARAGRAPH.CENTER)
    set_run(
        p.add_run("GROWTH MARKETING MANAGER | ECOMMERCE, CRO & ANALYTICS"),
        size=11.5, bold=True, color=RGBColor(40, 70, 110),
    )
    p = paragraph(after=3.0, align=WD_ALIGN_PARAGRAPH.CENTER)
    set_run(
        p.add_run(
            "Lehi, UT 84043   •   (530) 507-8269   •   mdavidcall@gmail.com   •   "
            "linkedin.com/in/mdavidcall"
        ),
        size=9.5, color=MUTED,
    )

    section_header("Professional Summary", before=2.0)
    p = paragraph(after=2.0)
    set_run(p.add_run(
        "Hands-on growth and ecommerce leader with 14+ years of experience improving customer journeys from "
        "acquisition and landing pages through conversion, retention, and lifetime value. Combines structured A/B "
        "and multivariate testing with GA4/GTM instrumentation, funnel analysis, qualitative customer insight, and "
        "clear reporting. Experienced with DTC and B2B commerce, affiliate strategy, product and promotion launches, "
        "HTML/CSS troubleshooting, and close collaboration with design, web, product, and operating teams."
    ))

    section_header("Core Competencies & Technical Skills")
    skill("Ecommerce Growth & CRO: ", "Conversion funnels, landing-page optimization, customer journeys, A/B and multivariate testing, testing roadmaps, product launches, promotions, retention, reactivation, and LTV.")
    skill("Analytics & Instrumentation: ", "GA4, Google Tag Manager, Adobe Analytics, Tableau, Looker Studio, Funnel.io, Excel, SQL, Python, Databricks, attribution, conversion paths, AOV, CAC, CPA, ROAS, and forecasting.")
    skill("Web, Commerce & CRM: ", "Shopify, Magento, WordPress, HTML5, CSS3, JavaScript, Salesforce, HubSpot, Marketo, Pardot, Zoho CRM, email automation, segmentation, and customer-retention campaigns.")
    skill("Creative & Workflow Collaboration: ", "Adobe Creative Suite, copywriting, content development, creative and landing-page production, web-team collaboration, project management, ChatGPT, Claude, Perplexity, Codex, Cursor, and AntiGravity.", after=1.2)

    section_header("Professional Experience")
    job_header("Marketing Strategist / Analyst", "1-800 Contacts", "Draper, UT")
    bullet("Funnel & Customer Value Analysis: ", "Evaluated reach-to-conversion funnels, micro-conversions, lifetime value, audiences, promotions, attribution, and incremental CPA to guide growth decisions.")
    bullet("Experimentation & Forecasting: ", "Analyzed holdouts, geo promotions, scale changes, bidding tests, and regression scenarios to prioritize investment and predict outcomes.")
    bullet("Affiliate & Reporting Analysis: ", "Reviewed affiliate commissions and discount negotiations and used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate reporting across more than 10 platforms.")

    job_header("Director of Digital Marketing", "GRIP6", "Midvale, UT")
    bullet("Ecommerce Growth: ", "Increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5 across a $400K monthly marketing budget.")
    bullet("Website & Measurement: ", "Guided website and on-page SEO improvements while implementing custom GA4 and GTM reporting for campaign and onsite performance.")
    bullet("Cross-Functional Optimization: ", "Built shared Looker Studio KPIs connecting marketing, inventory, engineering, management, web development, email, and budget decisions.")

    doc.add_page_break()

    job_header("Director of E-Commerce & Marketing", "Intercon Inc.", "Salt Lake City, UT", before=0)
    bullet("Ecommerce Transformation: ", "Led ecommerce and marketing for a large B2B distributor, creating a functional digital environment and adding multiple B2C platforms while supporting 650+ retail partners.")
    bullet("Product & Channel Launches: ", "Developed ecommerce-specific products with manufacturers and expanded Amazon operations into CastleGate, Target.com, Costco.com, and other channels.")
    bullet("Customer & Financial Insight: ", "Performed daily analysis to identify market niches, guide product development, and evaluate initiatives through project-level cost/benefit decisions.")
    bullet("Cross-Functional Delivery: ", "Partnered with IT, operations, finance, product development, HR, and sales to implement technology, process, and organizational change.")

    job_header("SEM Manager / Project Manager", "The Infinite Agency", "Dallas, TX")
    bullet("Customer Journey Strategy: ", "Advised clients on websites, SEO, email, paid search, display, mobile, remarketing, video, and social based on business needs and analytical findings.")
    bullet("Testing & Conversion: ", "Created conversion and attribution models and multivariate tests to improve audience, message, channel, and landing-page decisions.")
    bullet("Reporting & Automation: ", "Built Funnel.io and Looker Studio reporting and developed scripts for continuous campaign monitoring and faster issue identification.")

    job_header("E-Commerce Manager", "LifeSpan Fitness", "Salt Lake City, UT")
    bullet("Revenue & Funnel Ownership: ", "Led an eight-person ecommerce team and managed 150+ campaigns with a $400K budget, producing more than $9M in revenue—35% of company revenue.")
    bullet("CRO & Experimentation: ", "Analyzed funnels and conversion paths, optimized landing pages, created attribution models, and ran A/B and multivariate tests across acquisition programs.")
    bullet("Affiliate & Retention Foundations: ", "Created an affiliate-program strategy and managed email, remarketing, social, shopping, video, and mobile programs across the United States, Canada, and the UK.")
    bullet("Creative & Web Collaboration: ", "Developed search and display copy and creative with Adobe tools and partnered with the web-development team on ecommerce and SEO improvements.")

    section_header("Education, Languages & Certifications", before=1.5)
    p = paragraph(after=0.6)
    set_run(p.add_run("Brigham Young University — Bachelor of Science in Business Management (2008)"), bold=True)
    set_run(p.add_run("  |  Entrepreneur of the Year team; Regional Business Plan Competition winner, two consecutive years"), color=MUTED)
    p = paragraph(after=0.6)
    set_run(p.add_run("Languages: "), bold=True, color=NAVY)
    set_run(p.add_run("English (Native)  •  Spanish (Fluent)"))
    p = paragraph(after=0)
    set_run(p.add_run("Certifications: "), bold=True, color=NAVY)
    set_run(p.add_run("Google Ads  •  Google Analytics  •  Facebook Blueprint  •  Bing Ads  •  Amazon Marketing Services"))

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


if __name__ == "__main__":
    build_resume(OUTPUT)
    export_and_validate(OUTPUT, PDF, SCRATCH)
