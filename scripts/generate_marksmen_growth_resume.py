"""Build and validate the Gecko resume for Marksmen Inc. job fa82cf050ba15a2a."""

from pathlib import Path

import docx
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Inches, Pt, RGBColor

from generate_vitality_medical_resume import (
    BODY_SIZE,
    FONT,
    LINE_SPACING,
    MUTED,
    NAVY,
    TEXT,
    export_and_validate,
    keep_table_together,
    remove_table_borders,
    set_cell_margins,
    set_run,
)


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "fa82cf050ba15a2a"
COMPANY = "Marksmen-Inc"
OUTPUT = ROOT / "output" / "resumes" / f"Dave-Call+{COMPANY}+{JOB_KEY}.docx"
SCRATCH = ROOT / "scratch" / f"{COMPANY}+{JOB_KEY}"
PDF = SCRATCH / "resume-preview.pdf"


def build_resume(path: Path):
    doc = docx.Document()
    for section in doc.sections:
        section.top_margin = Inches(0.34)
        section.bottom_margin = Inches(0.34)
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
        p._p.get_or_add_pPr().append(
            parse_xml(
                f'<w:pBdr {nsdecls("w")}><w:bottom w:val="single" '
                'w:sz="6" w:space="1" w:color="102C57"/></w:pBdr>'
            )
        )

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
        # Gecko preserves this blank right-side date cell without visible dates.

    def bullet(lead, body, after=0.2):
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.left_indent = Inches(0.18)
        p.paragraph_format.first_line_indent = Inches(-0.02)
        p.paragraph_format.line_spacing = LINE_SPACING
        p.paragraph_format.space_before = Pt(0)
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
        p.add_run("DIRECTOR OF GROWTH MARKETING | B2B DEMAND GENERATION"),
        size=11.5,
        bold=True,
        color=RGBColor(40, 70, 110),
    )
    p = paragraph(after=3.0, align=WD_ALIGN_PARAGRAPH.CENTER)
    set_run(
        p.add_run(
            "Lehi, UT 84043   •   (530) 507-8269   •   mdavidcall@gmail.com   •   "
            "linkedin.com/in/mdavidcall"
        ),
        size=9.5,
        color=MUTED,
    )

    section_header("Professional Summary", before=2.0)
    p = paragraph(after=2.0)
    set_run(
        p.add_run(
            "Entrepreneurial growth marketing leader with 14+ years of hands-on experience turning customer insight, "
            "data, and creative ideas into measurable acquisition and revenue growth. Combines B2B and B2C strategy "
            "with direct execution across demand generation, campaign development, positioning, copy and content, "
            "email, CRM, segmentation, automation, digital media, testing, and conversion optimization. Proven at "
            "leading teams and collaborating with executives while remaining close to campaign setup, analysis, and "
            "continuous improvement. Advanced in analytics, automation, and AI-assisted workflows, with a practical focus on "
            "qualified opportunities, customer value, and revenue rather than vanity metrics."
        )
    )

    section_header("Core Competencies & Technical Skills")
    skill("Growth & Demand Generation: ", "Customer acquisition, lead generation, campaign strategy and execution, positioning, messaging, offers, copywriting, content strategy, audience research, customer retention, lifecycle marketing, CRO, and A/B/multivariate testing.")
    skill("B2B Leadership & Go-to-Market: ", "B2B and B2C strategy, client consulting, account and relationship management, product/program launches, cross-functional planning, vendor management, financial analysis, project management, and executive communication.")
    skill("CRM, Email & Automation: ", "HubSpot, Salesforce, Marketo, Pardot, Zoho CRM, Salesforce Marketing Cloud, Adobe Campaign, Mailchimp, Klaviyo, Constant Contact, email automation, segmentation, deliverability, retention campaigns, and email A/B testing.")
    skill("Analytics & Optimization: ", "GA4, Google Tag Manager, Tableau, Looker Studio, Adobe Analytics, Funnel.io, SQL, Python, Excel, attribution, regression analysis, LTV, CAC, conversion paths, revenue tracking, dashboards, and forecasting.")
    skill("AI & Digital Tools: ", "ChatGPT, Claude, Perplexity, Codex, Cursor, AntiGravity, Google Ads, Bing Ads, Meta Ads, Amazon, LinkedIn, WordPress, Shopify, Magento, HTML5, CSS3, and JavaScript.", after=1.2)

    section_header("Professional Experience")
    job_header("Marketing Strategist / Analyst", "1-800 Contacts", "Draper, UT")
    bullet("Portfolio & Team Leadership: ", "Managed $30 million per month with a team of four, using customer, channel, and financial analysis to guide investment and acquisition decisions.")
    bullet("Growth Planning: ", "Built regression-based scenarios to answer where an additional $10 million should be invested, evaluating holdouts, promotions, scale changes, and cross-channel reallocations.")
    bullet("Experimentation & Customer Value: ", "Analyzed data-driven attribution, lifetime value, audiences, bidding, brand/non-brand performance, promotions, and full-funnel reach-to-conversion tests.")
    bullet("Automated Decision Support: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms.")

    job_header("Director of Digital Marketing", "GRIP6", "Midvale, UT")
    bullet("Revenue Growth: ", "Increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5 across a $400K monthly marketing budget.")
    bullet("Hands-On Channel Ownership: ", "Managed Google, Bing, Amazon, Facebook, Instagram, and TikTok while guiding SEO, website optimization, email effectiveness, and cross-platform budget decisions.")
    bullet("Executive Visibility: ", "Built Looker Studio KPIs that connected marketing results with inventory, engineering, management, web development, and other operating priorities.")
    bullet("Measurement & Planning: ", "Implemented custom GA4/GTM reporting and created an inventory-planning methodology used across multiple departments.")

    doc.add_page_break()

    job_header("Director of E-Commerce & Marketing", "Intercon Inc.", "Salt Lake City, UT", before=0)
    bullet("B2B Growth & Transformation: ", "Led ecommerce and marketing for a large B2B distributor, creating a functional digital environment and expanding into multiple B2C platforms while supporting 650+ retail partners.")
    bullet("Entrepreneurial Expansion: ", "Developed ecommerce-specific products with manufacturers, improved supply-chain processes, and expanded Amazon operations into CastleGate, Target.com, Costco.com, and other channels.")
    bullet("Commercial Opportunity Analysis: ", "Performed daily financial analysis to identify market niches, guide product development, and evaluate projects through cost/benefit decisions.")
    bullet("Cross-Functional Leadership: ", "Worked with IT, operations, finance, product development, HR, and sales leaders to drive technology, process, cultural, and operating change.")

    job_header("SEM Manager / Project Manager", "The Infinite Agency", "Dallas, TX")
    bullet("Client Growth Strategy: ", "Advised clients on allocating marketing funds across websites, SEO, email, paid search, display, mobile, remarketing, YouTube, and social based on their business needs.")
    bullet("Hands-On Campaign Scale: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month while maintaining a standardized service-quality system adopted agency-wide.")
    bullet("Testing & Optimization: ", "Created conversion and attribution models and multivariate tests to improve audience, message, channel, and landing-page decisions.")
    bullet("Marketing Automation: ", "Developed custom scripts for continuous campaign monitoring, budget oversight, and faster performance issue identification.")

    job_header("E-Commerce Manager", "LifeSpan Fitness", "Salt Lake City, UT")
    bullet("Department Leadership: ", "Led an eight-person ecommerce team responsible for paid search, outreach, lead generation, and customer acquisition in the United States, Canada, and the UK.")
    bullet("Revenue Impact: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue—35% of company revenue.")
    bullet("Campaign Development: ", "Performed keyword, channel, and competitive research; created search and display ad copy and creative; and managed email, shopping, video, social, local, and remarketing programs.")
    bullet("Testing & Conversion: ", "Built attribution models, analyzed funnels and conversion paths, optimized landing pages, and ran A/B and multivariate tests to improve acquisition performance.")
    bullet("Executive Planning: ", "Established annual goals, projections, and KPIs with senior management and reported business performance using Magento, Google Analytics, ACCTivate, and QuickBooks.")

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
