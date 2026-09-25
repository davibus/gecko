"""Build and validate the Gecko resume for Vitality Medical job b1e13fda0b6ba9cb."""

from __future__ import annotations

import os
import html
import base64
import json
import subprocess
from pathlib import Path

from silent_subprocess import windows_creationflags

import docx
import fitz
import win32com.client
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
JOB_KEY = "b1e13fda0b6ba9cb"
COMPANY = "Vitality-Medical"
OUTPUT = ROOT / "output" / "resumes" / f"Dave-Call+{COMPANY}+{JOB_KEY}.docx"
SCRATCH = ROOT / "scratch" / f"Vitality-Medical+{JOB_KEY}"
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
    set_run(p.add_run("E-COMMERCE SEO & DIGITAL MARKETING MANAGER"), size=11.5, bold=True, color=RGBColor(40, 70, 110))
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
            "Hands-on e-commerce SEO and digital marketing leader with 14+ years spanning technical SEO, "
            "catalog and platform operations, analytics, automation, and customer acquisition. Experienced "
            "leading ecommerce functions, modernizing a large B2B distributor with multiple B2C platforms, "
            "and optimizing websites through keyword research, metadata, schema markup, content, site taxonomy, "
            "on-page and off-page SEO, conversion testing, and performance measurement. Combines Magento, GA4, "
            "Google Tag Manager, Search Console, Semrush, HTML/CSS/JavaScript, Python, SQL, and API knowledge with "
            "cross-functional leadership across catalog, product, web development, IT, finance, operations, and sales."
        )
    )

    section_header("Core Competencies & Technical Skills")
    skill("E-Commerce SEO: ", "Technical and on-page SEO, SEO audits, keyword and competitor research, metadata, taxonomy, schema markup, content strategy, link building, off-page SEO, internal content promotion, local/mobile SEO, conversion rate optimization, and website management.")
    skill("Commerce & Catalog Platforms: ", "Magento, Shopify, WordPress, Amazon Vendor Central and Seller Central (FBA/FBM), ecommerce analytics, ERP workflows, customer databases, and B2B/B2C operations.")
    skill("Analytics & Measurement: ", "Google Analytics 4 and Universal Analytics, Google Tag Manager, Search Console, Keyword Planner, Google Trends, Looker Studio, Tableau, Adobe Analytics, Funnel.io, Semrush, Moz, SimilarWeb, attribution, regression analysis, and KPI reporting.")
    skill("Web, Data & Automation: ", "HTML5, CSS3, JavaScript, Python, SQL, VBA, APIs, Git/GitHub, relational databases, data visualization, workflow automation, and multivariate testing.")
    skill("AI-Assisted Workflows: ", "ChatGPT, Claude, Perplexity, Codex, Cursor, and AntiGravity for research, analysis, prompt development, scripting, content support, reporting, and workflow acceleration.", after=1.2)

    section_header("Professional Experience")
    job_header("Marketing Strategist / Analyst", "1-800 Contacts", "Draper, UT")
    bullet("Portfolio Leadership: ", "Managed $30 million per month with a team of four, using performance analysis to guide cross-channel investment, testing, and acquisition decisions.")
    bullet("Advanced Analytics: ", "Evaluated data-driven attribution, customer lifetime value, keyword and audience performance, brand/non-brand CPA, bidding approaches, and five-year projections using predictive and regression models.")
    bullet("Reporting Automation: ", "Used Python, SQL, Databricks, Excel, Funnel.io, and Tableau to automate accurate weekly reporting across more than 10 marketing platforms.")
    bullet("Journey Measurement: ", "Led reach, comparison, conversion, and lifetime-value testing and assessed Click-to-Call and iSpot attribution systems.")

    job_header("Director of Digital Marketing", "GRIP6", "Midvale, UT")
    bullet("E-Commerce Growth: ", "Managed Google, Bing, Amazon, Meta, Instagram, and TikTok with a $400K monthly budget; increased monthly volume from $200K to $800K while improving ROAS from 1.5 to 3.5.")
    bullet("SEO & Measurement: ", "Guided on-page SEO and optimization while implementing custom GA4 reporting and Google Tag Manager configurations.")
    bullet("Operational Reporting: ", "Built Looker Studio KPIs supporting inventory, engineering, management, web development, email, and cross-platform budget decisions.")
    bullet("Inventory Planning: ", "Created a robust planning methodology used across departments to connect product availability, operating needs, and marketing decisions.")

    # Explicit page break makes page count stable while allowing both pages to be well filled.
    doc.add_page_break()

    job_header("Director of E-Commerce & Marketing", "Intercon Inc.", "Salt Lake City, UT", before=0)
    bullet("Digital & Commerce Transformation: ", "Led ecommerce and marketing for a large B2B distributor, building a functional digital environment and adding multiple B2C platforms while supporting 650+ retail partners.")
    bullet("Catalog & Systems Operations: ", "Established information architecture and ERP workflows, introduced systems for transparency and collaboration, and maintained databases used for accurate financial and marketing reporting.")
    bullet("Product & Marketplace Expansion: ", "Developed ecommerce-specific products with manufacturers and expanded Amazon Vendor/Seller operations into CastleGate, Target.com, Costco.com, and other channels.")
    bullet("Cross-Functional Ownership: ", "Worked with IT, operations, finance, product development, HR, and sales leaders while managing changing priorities and project-based cost/benefit decisions.")
    bullet("Commercial Analysis: ", "Performed daily financial analysis to identify product niches, guide development opportunities, and evaluate marketing investments against expected business value.")

    job_header("SEM Manager / Project Manager", "The Infinite Agency", "Dallas, TX")
    bullet("Integrated Search Strategy: ", "Advised clients on website development, SEO, email, paid search, display, mobile, remarketing, YouTube, and social based on business needs and analytical findings.")
    bullet("Scale & Execution: ", "Built and managed 75+ Google Ads accounts totaling more than $276K per month and created a standardized quality system adopted across the agency.")
    bullet("Testing & Measurement: ", "Created conversion and attribution models, multivariate tests, consolidated Funnel.io reporting, and Looker Studio presentations.")
    bullet("Automation: ", "Developed custom scripts for continuous monitoring of client marketing performance and faster issue identification.")
    bullet("Data-Driven Recommendations: ", "Used industry analytical platforms to assess each account and translate findings into channel, website, SEO, and campaign priorities for clients.")

    job_header("E-Commerce Manager", "LifeSpan Fitness", "Salt Lake City, UT")
    bullet("E-Commerce Leadership: ", "Led an eight-person ecommerce department responsible for paid search, outreach, lead generation, and customer acquisition across the United States, Canada, and the UK.")
    bullet("Revenue & Campaign Scale: ", "Managed 150+ campaigns and a $400K budget across Google, Bing, Gemini, and Amazon, producing more than $9M in revenue—35% of company revenue.")
    bullet("SEO, Content & CRO: ", "Performed keyword and competitive research, monitored SEO/SEM with multiple tools, optimized landing pages, developed ad copy and creative, and ran A/B and multivariate conversion tests.")
    bullet("Platforms & Analytics: ", "Used Magento, Google Analytics, ACCTivate, QuickBooks, editors, and Amazon analytics to report KPIs, conversion paths, projections, and business performance.")
    bullet("Web Collaboration: ", "Partnered with the web development team and used JavaScript-assisted automation to align campaigns and site work with promotions and business goals.")
    bullet("Full-Funnel Channels: ", "Managed display, mobile, remarketing, search, video, email, shopping, social, local, and commercial real estate campaigns across the customer journey.")
    bullet("Planning & Governance: ", "Set business goals, annual projections, and KPIs with senior management and used competitive analysis to improve campaign positioning and performance.")

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
    word_error = None
    native_status = None

    def request_native_validation():
        validator = ROOT / "scripts" / "validate_word_native.ps1"
        result_path = scratch / "validation-status.json"
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(validator),
                "-DocxPath",
                str(docx_path.resolve()),
                "-PdfPath",
                str(pdf_path.resolve()),
                "-ResultPath",
                str(result_path.resolve()),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            creationflags=windows_creationflags(),
        )

    running_in_sandbox = "codexsandbox" in os.environ.get("USERNAME", "").lower()
    if running_in_sandbox:
        print("Requesting native pagination through the interactive Word validation bridge.")
        completed = request_native_validation()
        if completed.returncode == 0:
            if completed.stdout.strip():
                print(completed.stdout.strip())
            result_path = scratch / "validation-status.json"
            native_status = json.loads(result_path.read_text(encoding="utf-8-sig"))
            word_pages = native_status.get("word_pages")
        else:
            bridge_message = (completed.stderr or completed.stdout).strip()
            word_error = bridge_message or "Interactive Word validation bridge unavailable."
            if bridge_message:
                print(bridge_message)
            render_fallback_pdf(docx_path, pdf_path, scratch)
    else:
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
            word_error = str(exc)
            print("Direct Word automation failed; requesting the interactive Word validation bridge.")
            completed = request_native_validation()
            if completed.returncode == 0:
                if completed.stdout.strip():
                    print(completed.stdout.strip())
                result_path = scratch / "validation-status.json"
                native_status = json.loads(result_path.read_text(encoding="utf-8-sig"))
                word_pages = native_status.get("word_pages")
                word_error = None
            else:
                bridge_message = (completed.stderr or completed.stdout).strip()
                word_error = bridge_message or word_error
                if bridge_message:
                    print(bridge_message)
                render_fallback_pdf(docx_path, pdf_path, scratch)

    pdf = fitz.open(pdf_path)
    pdf_pages = len(pdf)
    for i, page in enumerate(pdf):
        pix = page.get_pixmap(dpi=160, alpha=False)
        pix.save(scratch / f"resume-page-{i + 1}.png")
    pdf.close()

    status = native_status or {
        "status": "native-valid" if word_pages == 2 and pdf_pages == 2 else "native-pending",
        "docx": str(docx_path.resolve()),
        "pdf": str(pdf_path.resolve()),
        "word_pages": word_pages,
        "pdf_pages": pdf_pages,
        "word_error": word_error,
    }
    status["pdf_pages"] = pdf_pages
    (scratch / "validation-status.json").write_text(
        json.dumps(status, indent=2), encoding="utf-8"
    )

    if (word_pages is not None and word_pages != 2) or pdf_pages != 2:
        raise RuntimeError(f"Resume must be exactly 2 pages; Word={word_pages}, PDF={pdf_pages}")
    print(f"Saved: {docx_path}")
    if word_pages is None:
        print(
            f"Fallback-only pagination check: PDF={pdf_pages} pages. "
            "Native Microsoft Word validation is still required."
        )
    else:
        print(f"Validated: Word={word_pages} pages, PDF={pdf_pages} pages")
    print(f"Preview: {pdf_path}")
    return status


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
    service = Service(popen_kw={"creation_flags": windows_creationflags()})
    driver = webdriver.Chrome(options=options, service=service)
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
