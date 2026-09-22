"""Build and validate the Gecko resume for Compass job 5825304044."""

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
JOB_KEY = "5825304044"
COMPANY = "Compass"
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
        p.add_run("STRATEGIC GROWTH | B2B RELATIONSHIPS & TECHNOLOGY"),
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
        "Growth and technology leader with 14+ years of experience helping organizations identify opportunities, "
        "translate business needs into practical solutions, and connect marketing investment to revenue. Brings "
        "hands-on B2B and B2C leadership, client consulting, executive communication, financial analysis, and "
        "cross-functional delivery. Known as a self-directed, analytical partner who can explain complex technology "
        "clearly, manage competing priorities, and build alignment around growth decisions."
    ))

    section_header("Core Competencies & Technical Skills")
    skill("Strategic Growth & Consulting: ", "Business discovery, opportunity analysis, B2B/B2C growth strategy, client consulting, relationship management, market and competitive research, positioning, and customer acquisition.")
    skill("Executive Communication & Leadership: ", "Technology-focused presentations, stakeholder alignment, team leadership, cross-functional planning, project management, vendor management, and change leadership.")
    skill("Revenue & Performance Analysis: ", "Financial analysis, forecasting, cost/benefit decisions, revenue tracking, LTV, CAC, ROAS, attribution, Tableau, Looker Studio, Excel, Python, and SQL.")
    skill("Technology & Growth Platforms: ", "Salesforce, HubSpot, Zoho CRM, marketing automation, Magento, Shopify, WordPress, GA4, GTM, Adobe Analytics, APIs, ChatGPT, Claude, Perplexity, Codex, Cursor, and AntiGravity.", after=1.2)

    section_header("Professional Experience")
    job_header("Marketing Strategist / Analyst", "1-800 Contacts", "Draper, UT")
    bullet("Portfolio & Team Leadership: ", "Managed $30 million per month with a team of four, translating customer, channel, and financial evidence into investment and growth recommendations.")
    bullet("Strategic Decision Support: ", "Built regression-based scenarios to advise management where an additional $10 million should be invested across promotions, holdouts, scale changes, and channel reallocations.")
    bullet("Business Intelligence: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 platforms and improve decision visibility.")

    job_header("Director of Digital Marketing", "GRIP6", "Midvale, UT")
    bullet("Revenue Growth: ", "Increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5 across a $400K monthly marketing budget.")
    bullet("Technology & Value Communication: ", "Built shared Looker Studio KPIs connecting marketing results with inventory, engineering, management, web development, email, and budget decisions.")
    bullet("Cross-Functional Execution: ", "Led growth activity across Google, Bing, Amazon, Meta, Instagram, and TikTok while coordinating website, SEO, analytics, and inventory-planning priorities.")

    doc.add_page_break()

    job_header("Director of E-Commerce & Marketing", "Intercon Inc.", "Salt Lake City, UT", before=0)
    bullet("B2B Growth Leadership: ", "Led ecommerce and marketing for a large B2B distributor, modernizing its digital environment while supporting relationships with more than 650 retail partners.")
    bullet("Commercial Expansion: ", "Developed ecommerce-specific products with manufacturers and expanded into Amazon, CastleGate, Target.com, Costco.com, and other channels.")
    bullet("Opportunity & Financial Analysis: ", "Performed daily analysis to identify market niches, guide product development, and evaluate growth initiatives through project-level cost/benefit decisions.")
    bullet("Organizational Influence: ", "Partnered with IT, operations, finance, product development, HR, and sales leaders to implement technology, process, and cultural change.")

    job_header("SEM Manager / Project Manager", "The Infinite Agency", "Dallas, TX")
    bullet("Consultative Client Discovery: ", "Advised clients on allocating funds across websites, SEO, email, paid search, display, mobile, remarketing, YouTube, and social based on their business needs.")
    bullet("Client Portfolio Management: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month while maintaining consistent service quality across different client sizes.")
    bullet("Presentation & Recommendations: ", "Consolidated performance data with Funnel.io and Looker Studio, converting analytical findings into client-facing recommendations and action plans.")
    bullet("Process Improvement: ", "Created monitoring scripts and a standardized account-management system that was adopted across the agency.")

    job_header("E-Commerce Manager", "LifeSpan Fitness", "Salt Lake City, UT")
    bullet("Team & Market Leadership: ", "Led an eight-person ecommerce team responsible for outreach, lead generation, and customer acquisition across the United States, Canada, and the UK.")
    bullet("Revenue Performance: ", "Managed 150+ campaigns and a $400K budget that produced more than $9M in revenue—35% of company revenue.")
    bullet("Executive Planning: ", "Established annual goals, projections, and KPIs with senior management and presented business performance using marketing, ecommerce, inventory, and financial data.")

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
