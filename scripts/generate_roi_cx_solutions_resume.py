"""Build and validate the Gecko resume for ROI CX Solutions job 8e3a51cb94d9deee."""

from __future__ import annotations

import os
import html
import base64
from pathlib import Path

import docx
import fitz
import win32com.client
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "8e3a51cb94d9deee"
COMPANY = "ROI-CX-Solutions"
OUTPUT = ROOT / "output" / "resumes" / f"Dave-Call+{COMPANY}+{JOB_KEY}.docx"
SCRATCH = ROOT / "scratch" / f"ROI-CX-Solutions+{JOB_KEY}"
PDF = SCRATCH / "resume-preview.pdf"

NAVY = RGBColor(16, 44, 87)
TEXT = RGBColor(38, 38, 38)
MUTED = RGBColor(82, 82, 82)
FONT = "Calibri"
BODY_SIZE = 11.0
LINE_SPACING = 1.15


def set_cell_margins(cell, top=0, bottom=0, left=0, right=0):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for name, value in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        node = OxmlElement(f"w:{name}")
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")
        tc_mar.append(node)


def remove_table_borders(table):
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        '<w:top w:val="none"/><w:left w:val="none"/>'
        '<w:bottom w:val="none"/><w:right w:val="none"/>'
        '<w:insideH w:val="none"/><w:insideV w:val="none"/>'
        "</w:tblBorders>"
    )
    table._tbl.tblPr.append(borders)


def keep_table_together(table):
    for row in table.rows:
        row._tr.get_or_add_trPr().append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))


def set_run(run, size=BODY_SIZE, bold=False, color=TEXT):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.bold = bold
    run.font.color.rgb = color


def build_resume(path: Path):
    doc = docx.Document()
    for section in doc.sections:
        section.top_margin = Inches(0.40)
        section.bottom_margin = Inches(0.40)
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

    bullet_style = doc.styles["List Bullet"]
    bullet_style.font.name = FONT
    bullet_style.font.size = Pt(BODY_SIZE)

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

    def job_header(title, company, location, before=1.5):
        table = doc.add_table(rows=1, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        remove_table_borders(table)
        keep_table_together(table)
        widths = (Inches(5.95), Inches(1.55))
        for index, width in enumerate(widths):
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
        # Intentionally blank: Gecko preserves the date cell without visible dates.

    def bullet(lead, body, after=0.4):
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
        set_run(p.add_run(lead), size=11, bold=True, color=NAVY)
        set_run(p.add_run(body), size=11)

    # Header
    p = paragraph(after=0.5, align=WD_ALIGN_PARAGRAPH.CENTER)
    set_run(p.add_run("DAVE CALL"), size=19, bold=True, color=NAVY)
    p = paragraph(after=1.2, align=WD_ALIGN_PARAGRAPH.CENTER)
    set_run(p.add_run("HEAD OF DIGITAL MARKETING | B2B GROWTH & ANALYTICS"), size=11.5, bold=True, color=RGBColor(40, 70, 110))
    p = paragraph(after=3.0, align=WD_ALIGN_PARAGRAPH.CENTER)
    set_run(
        p.add_run(
            "Lehi, UT 84043   •   (530) 507-8269   •   mdavidcall@gmail.com   •   "
            "linkedin.com/in/mdavidcall   •   Spanish: Fluent"
        ),
        size=9.5,
        color=MUTED,
    )

    section_header("Professional Summary", before=2.0)
    p = paragraph(after=2.0)
    set_run(
        p.add_run(
            "Hands-on digital marketing leader with 14+ years across B2B and B2C growth, lead generation, paid "
            "media, SEO, analytics, automation, and conversion. Experienced owning budgets, leading teams, "
            "modernizing a large B2B distributor, and translating performance data into practical campaign, "
            "website, and investment decisions."
        )
    )

    section_header("Core Competencies & Technical Skills")
    skill("Growth & Demand: ", "B2B/B2C strategy, lead generation, paid search and social, content, email, customer acquisition, CRO, and budget ownership.")
    skill("Search & Measurement: ", "Technical SEO, schema, site architecture, keyword research, GA4, GTM, Search Console, Semrush, attribution, LTV, CAC/CPA, ROAS, and KPI reporting.")
    skill("Platforms & Automation: ", "Salesforce, HubSpot, Magento, WordPress, Tableau, Looker Studio, Funnel.io, HTML/CSS/JavaScript, Python, SQL, APIs, and testing.")
    skill("AI-Assisted Marketing: ", "ChatGPT, Claude, Perplexity, Codex, Cursor, and AntiGravity for research, analysis, scripting, content support, and workflow acceleration.", after=1.2)

    section_header("Professional Experience")
    job_header("Marketing Strategist / Analyst", "1-800 Contacts", "Draper, UT")
    bullet("Portfolio Leadership: ", "Managed $30 million per month with a team of four, using performance analysis to guide cross-channel investment, testing, acquisition, and budget-allocation decisions.")
    bullet("Analytics & Planning: ", "Evaluated attribution, lifetime value, audience performance, CPA, bidding, and investment scenarios using predictive and regression models.")
    bullet("Reporting Automation: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate weekly reporting across more than 10 marketing platforms.")

    job_header("Director of Digital Marketing", "GRIP6", "Midvale, UT")
    bullet("Growth & Budget Ownership: ", "Managed Google, Bing, Amazon, Meta, Instagram, and TikTok with a $400K monthly budget; increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5.")
    bullet("Search & Measurement: ", "Guided on-page SEO and website optimization while implementing custom GA4, GTM, and Looker Studio reporting.")
    bullet("Cross-Functional Planning: ", "Connected campaign, inventory, engineering, website, email, and budget decisions through shared KPIs and a new planning methodology.")

    # Explicit page break makes page count stable while allowing both pages to be well filled.
    doc.add_page_break()

    job_header("Director of E-Commerce & Marketing", "Intercon Inc.", "Salt Lake City, UT", before=0)
    bullet("B2B Marketing Transformation: ", "Led ecommerce and marketing for a large B2B distributor, building a functional digital environment and adding multiple B2C platforms while supporting 650+ retail partners.")
    bullet("Systems & Reporting: ", "Established information architecture and ERP workflows and maintained databases supporting accurate financial and marketing reporting.")
    bullet("Cross-Functional Ownership: ", "Partnered with IT, operations, finance, product, HR, and sales while evaluating initiatives through project-level cost/benefit analysis.")
    bullet("Marketplace Expansion: ", "Expanded Amazon Vendor/Seller operations into CastleGate, Target.com, Costco.com, and other channels.")

    job_header("SEM Manager / Project Manager", "The Infinite Agency", "Dallas, TX")
    bullet("Integrated Growth Strategy: ", "Advised clients on website development, SEO, email, paid search, display, mobile, remarketing, YouTube, and social based on business needs and analytical findings.")
    bullet("Scale & Execution: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month and created a standardized quality system adopted across the agency.")
    bullet("Measurement & Automation: ", "Created attribution models, multivariate tests, Funnel.io/Looker Studio reporting, and scripts for continuous performance monitoring.")

    job_header("E-Commerce Manager", "LifeSpan Fitness", "Salt Lake City, UT")
    bullet("E-Commerce Leadership: ", "Led an eight-person ecommerce department responsible for paid search, outreach, lead generation, and customer acquisition across the United States, Canada, and the UK.")
    bullet("Revenue & Campaign Scale: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue—35% of company revenue.")
    bullet("SEO, Content & CRO: ", "Performed keyword and competitive research, optimized landing pages, developed ad creative, and ran A/B and multivariate tests.")
    bullet("Full-Funnel Analytics: ", "Used Magento, Google Analytics, Amazon analytics, and conversion-path analysis across search, display, video, email, shopping, social, and remarketing.")

    section_header("Education, Languages & Certifications", before=2.2)
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


def export_and_validate(docx_path: Path, pdf_path: Path, scratch_dir: Path | None = None):
    scratch = Path(scratch_dir) if scratch_dir is not None else SCRATCH
    scratch.mkdir(parents=True, exist_ok=True)
    word_pages = None
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        try:
            document = word.Documents.Open(str(docx_path.resolve()))
            document.Repaginate()
            word_pages = document.ComputeStatistics(2)
            document.ExportAsFixedFormat(str(pdf_path.resolve()), 17)
            document.Close(False)
        finally:
            word.Quit()
    except Exception as exc:
        print(f"Word automation unavailable ({exc}); using faithful HTML/CSS fallback.")
        render_fallback_pdf(docx_path, pdf_path, scratch)

    pdf = fitz.open(pdf_path)
    pdf_pages = len(pdf)
    for i, page in enumerate(pdf):
        pix = page.get_pixmap(dpi=160, alpha=False)
        pix.save(scratch / f"resume-page-{i + 1}.png")
    pdf.close()

    if (word_pages is not None and word_pages != 2) or pdf_pages != 2:
        raise RuntimeError(f"Resume must be exactly 2 pages; Word={word_pages}, PDF={pdf_pages}")
    print(f"Saved: {docx_path}")
    print(f"Validated: Word={word_pages} pages, PDF={pdf_pages} pages")
    print(f"Preview: {pdf_path}")


def render_fallback_pdf(docx_path: Path, pdf_path: Path, scratch_dir: Path | None = None):
    """Render a close CSS representation when desktop Word cannot run in the session."""
    scratch = Path(scratch_dir) if scratch_dir is not None else SCRATCH
    source = docx.Document(docx_path)

    def formatted_runs(paragraph):
        parts = []
        for run in paragraph.runs:
            value = html.escape(run.text)
            if not value:
                continue
            if run.bold:
                value = f"<strong>{value}</strong>"
            parts.append(value)
        return "".join(parts)

    blocks = []
    para_index = 0
    for child in source.element.body.iterchildren():
        if child.tag == qn("w:p"):
            p = docx.text.paragraph.Paragraph(child, source)
            if child.xpath('.//w:br[@w:type="page"]'):
                blocks.append('<div class="hard-break"></div>')
                continue
            content = formatted_runs(p)
            if not content:
                continue
            style = p.style.name if p.style else ""
            text_value = p.text.strip()
            if para_index == 0:
                cls = "name"
            elif para_index == 1:
                cls = "title"
            elif para_index == 2:
                cls = "contact"
            elif text_value.isupper() and len(text_value) < 60:
                cls = "section"
            elif style == "List Bullet":
                cls = "bullet"
            else:
                cls = "body"
            blocks.append(f'<div class="{cls}">{content}</div>')
            para_index += 1
        elif child.tag == qn("w:tbl"):
            table = docx.table.Table(child, source)
            left = formatted_runs(table.cell(0, 0).paragraphs[0])
            blocks.append(f'<div class="job"><div>{left}</div><div></div></div>')

    preview_html = scratch / "resume-preview.html"
    css = """
      @page { size: 8.5in 11in; margin: 0.40in 0.48in; }
      * { box-sizing: border-box; }
      body { margin: 0; color: #262626; background: white; font-family: Calibri, Arial, sans-serif;
             font-size: 11pt; line-height: 1.15; }
      .name { text-align: center; color: #102c57; font-size: 19pt; font-weight: 700; line-height: 1.15; margin: 0 0 .5pt; }
      .title { text-align: center; color: #28466e; font-size: 11.5pt; font-weight: 700; margin: 0 0 1.2pt; }
      .contact { text-align: center; color: #525252; font-size: 9.5pt; margin: 0 0 3pt; }
      .section { color: #102c57; font-size: 11pt; font-weight: 700; border-bottom: .75pt solid #102c57;
                 margin: 3pt 0 1.5pt; padding-bottom: 1pt; break-after: avoid; }
      .body { margin: 0 0 .8pt .10in; }
      .job { display: grid; grid-template-columns: 5.95in 1.55in; margin: 1.5pt 0 .5pt;
             break-after: avoid; font-size: 11pt; line-height: 1.15; }
      .bullet { position: relative; margin: 0 0 .4pt .18in; padding-left: .10in; }
      .bullet:before { content: "•"; position: absolute; left: -.08in; }
      .hard-break { height: 0; break-after: page; }
      strong { font-weight: 700; }
    """
    page = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{''.join(blocks)}</body></html>"
    preview_html.write_text(page, encoding="utf-8")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1400,1200")
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(preview_html.resolve().as_uri())
        result = driver.execute_cdp_cmd(
            "Page.printToPDF",
            {"printBackground": True, "preferCSSPageSize": True},
        )
        pdf_path.write_bytes(base64.b64decode(result["data"]))
    finally:
        driver.quit()


if __name__ == "__main__":
    build_resume(OUTPUT)
    export_and_validate(OUTPUT, PDF, SCRATCH)
