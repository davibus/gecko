import os
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
import win32com.client
import fitz

def set_cell_margins(cell, top=0, bottom=0, left=0, right=0):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

def remove_table_borders(table):
    tblPr = table._tbl.tblPr
    tblBorders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>\n'
        f'  <w:top w:val="none" w:sz="0" w:space="0" w:color="auto"/>\n'
        f'  <w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>\n'
        f'  <w:bottom w:val="none" w:sz="0" w:space="0" w:color="auto"/>\n'
        f'  <w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>\n'
        f'  <w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>\n'
        f'  <w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>\n'
        f'</w:tblBorders>'
    )
    tblPr.append(tblBorders)

def build_omni_resume(output_path, font_size_pt=10.0, margin_in=0.42, bullet_space_p2=0.8, job_space_p2=2.0):
    doc = docx.Document()
    
    for section in doc.sections:
        section.top_margin = Inches(margin_in)
        section.bottom_margin = Inches(margin_in)
        section.left_margin = Inches(0.45)
        section.right_margin = Inches(0.45)
        section.page_width = Inches(8.5)
        section.page_height = Inches(11.0)
    
    line_spacing = 1.15
    
    normal_style = doc.styles['Normal']
    normal_style.font.name = 'Calibri'
    normal_style.font.size = Pt(font_size_pt)
    normal_style.font.color.rgb = RGBColor(30, 30, 30)
    normal_style.paragraph_format.line_spacing = line_spacing
    normal_style.paragraph_format.space_after = Pt(0)
    normal_style.paragraph_format.space_before = Pt(0)

    # 1. HEADER
    p_name = doc.add_paragraph()
    p_name.paragraph_format.space_before = Pt(0)
    p_name.paragraph_format.space_after = Pt(1)
    p_name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_name = p_name.add_run("DAVE CALL")
    run_name.bold = True
    run_name.font.size = Pt(19)
    run_name.font.color.rgb = RGBColor(16, 44, 87) # Deep Navy

    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(2.5)
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_title = p_title.add_run("SEARCH ENGINE MARKETING (SEM) & PAID SEARCH SPECIALIST")
    run_title.bold = True
    run_title.font.size = Pt(11.0)
    run_title.font.color.rgb = RGBColor(40, 70, 110)

    p_contact = doc.add_paragraph()
    p_contact.paragraph_format.space_before = Pt(0)
    p_contact.paragraph_format.space_after = Pt(4.5)
    p_contact.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_contact = p_contact.add_run("Lehi, UT 84043   •   (530) 507-8269   •   mdavidcall@gmail.com   •   linkedin.com/in/mdavidcall   •   Spanish: Fluent")
    run_contact.font.size = Pt(9.5)
    run_contact.font.color.rgb = RGBColor(70, 70, 70)

    # Section Divider
    def add_section_header(title, space_before=4.0):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(space_before)
        p.paragraph_format.space_after = Pt(2.0)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(title.upper())
        run.bold = True
        run.font.size = Pt(10.5)
        run.font.color.rgb = RGBColor(16, 44, 87)
        
        pBdr = parse_xml(
            f'<w:pBdr {nsdecls("w")}>\n'
            f'  <w:bottom w:val="single" w:sz="6" w:space="1" w:color="102C57"/>\n'
            f'</w:pBdr>'
        )
        p._p.get_or_add_pPr().append(pBdr)

    # Job Header (2-column table: Left Title/Company, Right Date space)
    def add_job_header(title, company, location, space_before=2.5):
        table = doc.add_table(rows=1, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        remove_table_borders(table)
        
        col_widths = [Inches(5.8), Inches(1.8)]
        for row in table.rows:
            trPr = row._tr.get_or_add_trPr()
            trPr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))
            for idx, width in enumerate(col_widths):
                row.cells[idx].width = width
                set_cell_margins(row.cells[idx], top=0, bottom=0, left=0, right=0)
        
        cell_left = table.cell(0, 0)
        p_left = cell_left.paragraphs[0]
        p_left.paragraph_format.space_before = Pt(space_before)
        p_left.paragraph_format.space_after = Pt(1)
        p_left.paragraph_format.line_spacing = line_spacing
        p_left.paragraph_format.keep_with_next = True
        
        r_title = p_left.add_run(title)
        r_title.bold = True
        r_title.font.size = Pt(font_size_pt)
        r_title.font.color.rgb = RGBColor(16, 44, 87)
        
        r_sep = p_left.add_run(" | ")
        r_sep.font.size = Pt(font_size_pt)
        r_sep.font.color.rgb = RGBColor(120, 120, 120)
        
        r_comp = p_left.add_run(f"{company} — {location}")
        r_comp.bold = True
        r_comp.font.size = Pt(font_size_pt)
        r_comp.font.color.rgb = RGBColor(50, 50, 50)
        
        # Right Cell (Preserved date space per Gecko specification)
        cell_right = table.cell(0, 1)
        p_right = cell_right.paragraphs[0]
        p_right.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p_right.paragraph_format.space_before = Pt(space_before)
        p_right.paragraph_format.space_after = Pt(1)
        p_right.paragraph_format.line_spacing = line_spacing
        p_right.paragraph_format.keep_with_next = True

    # Bullet Points
    def add_bullet(lead_text, body_text, space_after=1.2):
        p = doc.add_paragraph(style='List Bullet')
        p.paragraph_format.left_indent = Inches(0.18)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.line_spacing = line_spacing
        
        if lead_text:
            r_lead = p.add_run(lead_text)
            r_lead.bold = True
            r_lead.font.size = Pt(font_size_pt)
            r_lead.font.color.rgb = RGBColor(25, 25, 25)
        
        r_body = p.add_run(body_text)
        r_body.font.size = Pt(font_size_pt)
        r_body.font.color.rgb = RGBColor(40, 40, 40)

    # 2. PROFESSIONAL SUMMARY
    add_section_header("Professional Summary", space_before=3.0)
    p_sum = doc.add_paragraph()
    p_sum.paragraph_format.space_before = Pt(1)
    p_sum.paragraph_format.space_after = Pt(3.5)
    p_sum.paragraph_format.line_spacing = line_spacing
    r_sum = p_sum.add_run(
        "Highly analytical and results-driven SEM Specialist and Paid Search Expert with 15+ years of hands-on experience building, "
        "managing, and scaling high-performing Google Ads and multi-channel PPC campaigns across multi-location accounts and agency portfolios. "
        "Expert in executing granular keyword research, intent-driven match type architecture, rigorous negative keyword hygiene, and "
        "continuous quality score optimization to maximize qualified lead generation (calls, form fills, chats, and dealership appointment requests). "
        "Proven agency track record managing 75+ client accounts simultaneously, executing dynamic inventory and promotional ad copy refreshes, "
        "and building automated bid monitoring scripts. Deep technical mastery across Google Ads (Search, Display, Video, Shopping/PMax), "
        "Bing Ads, Google Analytics (GA4), Google Tag Manager (GTM), Google Looker Studio, and modern AI automation tools (ChatGPT, Claude, Codex, "
        "AntiGravity) to streamline cross-channel reporting, conduct account audits, and deliver actionable performance insights."
    )
    r_sum.font.size = Pt(font_size_pt)

    # 3. CORE COMPETENCIES & TECHNICAL EXPERTISE
    add_section_header("Core Competencies & Technical Skills", space_before=4.0)
    
    comp_data = [
        ("Search Engine Marketing (SEM) & Paid Ads: ", "Google Ads (Search, Display, Video, Performance Max, Vehicle Listing Ads/VLAs), Bing Ads, Meta Ads (Facebook & Instagram), Keyword Intent Sculpting, Negative Keyword Management, Bid Management & Smart Bidding Experiments, Quality Score Optimization."),
        ("Lead Tracking & Conversion Optimization: ", "Click-to-Call Systems, Phone Call Tracking, Digital Form Lead Capture, Live Chat Tracking, Landing Page A/B Testing, Conversion Rate Optimization (CRO), Local Geo-Fencing & Radius Targeting."),
        ("Analytics, Tracking & Reporting: ", "Google Analytics 4 (GA4), Universal Analytics, Google Tag Manager (GTM Container Setup & Custom Event Tracking), Google Looker Studio, Tableau, SQL, Python, Excel/Sheets Advanced Modeling (Pivot Tables, VLOOKUP/XLOOKUP), Funnel.io."),
        ("Multi-Account & Agency Operations: ", "Multi-Location Client Account Management, Account Audits & Restructuring, Budget Pacing & Allocation, Monthly Promotional & Inventory Ad Copy Updates, Competitor Intelligence & Search Query Mining."),
        ("AI & Workflow Automation: ", "ChatGPT, Claude, Perplexity, Codex, Cursor, AntiGravity (Search Query Analysis, Ad Copy Generation, Automated Audits, Custom Scripting, and Campaign Optimization)."),
        ("Creative, CMS & Web Tools: ", "Adobe Creative Suite (Photoshop, InDesign, Illustrator), HTML5, CSS3, JavaScript Tracking Scripts, WordPress, Shopify, Magento, HubSpot CRM.")
    ]
    for cat, desc in comp_data:
        p_c = doc.add_paragraph()
        p_c.paragraph_format.left_indent = Inches(0.12)
        p_c.paragraph_format.space_before = Pt(0)
        p_c.paragraph_format.space_after = Pt(2.0)
        p_c.paragraph_format.line_spacing = line_spacing
        
        r_c_lead = p_c.add_run(cat)
        r_c_lead.bold = True
        r_c_lead.font.size = Pt(font_size_pt - 0.3)
        r_c_lead.font.color.rgb = RGBColor(16, 44, 87)
        
        r_c_body = p_c.add_run(desc)
        r_c_body.font.size = Pt(font_size_pt - 0.3)
        r_c_body.font.color.rgb = RGBColor(40, 40, 40)

    # 4. PROFESSIONAL EXPERIENCE
    add_section_header("Professional Experience", space_before=4.0)

    # Job 1: 1-800 Contacts (Page 1)
    add_job_header("Marketing Strategist / Senior Analyst", "1-800 Contacts", "Draper, UT", space_before=2.0)
    add_bullet("Scale & Portfolio Governance: ", "Managed $30 million per month in advertising spend with a high-performing team of 4, steering complex search budget pacing and performance efficiency across high-volume acquisition funnels.", space_after=1.8)
    add_bullet("Paid Search Optimization & Testing: ", "Engineered and optimized large-scale Google Ads and paid search campaigns; analyzed Max CPC vs. smart bidding, Brand vs. Non-Brand target CPAs, and keyword match type structures to eliminate ad waste.", space_after=1.8)
    add_bullet("Lead & Call Tracking Systems: ", "Conducted comprehensive assessments of Click-to-Call tracking systems, phone lead conversion paths, and multi-touch attribution to accurately credit search touchpoints.", space_after=1.8)
    add_bullet("Attribution & Predictive Regression: ", "Executed Data-Driven Attribution (DDA) modeling, Customer Lifetime Value (LTV) evaluations, and 5-year predictive regression projections to forecast campaign returns and direct high-yield budget reallocations.", space_after=1.8)
    add_bullet("Automated Cross-Channel Reporting: ", "Built automated reporting pipelines leveraging Python, SQL, Funnel.io, and Tableau/Looker Studio, consolidating live performance metrics across 10+ paid channels into unified client dashboards.", space_after=1.8)
    add_bullet("AI-Assisted Operations: ", "Integrated modern AI tools including ChatGPT, Claude, and Codex to accelerate query analysis, negative keyword discovery, and rapid ad copy variations.", space_after=1.8)

    # PAGE 2 STARTS HERE CLEANLY
    doc.add_page_break()

    # Job 2: GRIP6 (Page 2)
    add_job_header("Director of Digital Marketing", "GRIP6", "Midvale, UT", space_before=0)
    add_bullet("Multi-Channel Paid Search & ROAS Growth: ", "Directed all paid search and digital media channels (Google Ads, Bing Ads, Amazon, Facebook, Instagram, TikTok) with a $400k/month budget; scaled monthly revenue 4x from $200k/month to $800k/month while increasing ROAS from 1.5 to 3.5.", space_after=bullet_space_p2)
    add_bullet("Measurement & Tracking Infrastructure: ", "Architected executive and operational KPI dashboards in Google Looker Studio; configured custom GA4 event tracking and Google Tag Manager (GTM) containers for granular cross-channel attribution.", space_after=bullet_space_p2)
    add_bullet("Landing Page CRO & Search Quality: ", "Established rigorous landing page conversion rate optimization (CRO), negative keyword sculpting, and on-page SEO best practices to maximize Quality Scores and lower cost-per-click (CPC).", space_after=bullet_space_p2)
    add_bullet("Cross-Platform Budget Allocation: ", "Developed dynamic budget allocation models aligning ad spend directly with real-time product inventory velocity and seasonal promotional calendars.", space_after=bullet_space_p2)

    # Job 3: Intercon Inc.
    add_job_header("Director of E-Commerce & Marketing", "Intercon Inc.", "Salt Lake City, UT", space_before=job_space_p2)
    add_bullet("Multi-Location & Dealer Marketing: ", "Led complete digital marketing and commercial transformation for a major distributor, supporting digital promotional initiatives across 650+ retail and dealer partners nationwide.", space_after=bullet_space_p2)
    add_bullet("Product Feeds & Architecture: ", "Structured comprehensive informational and product database architectures (ERP/product catalog feeds) to support multi-channel digital advertising and marketplace listing campaigns.", space_after=bullet_space_p2)
    add_bullet("Creative & Promotional Alignment: ", "Directed multi-platform digital advertising, direct promotional outreach, and print/catalog collateral development utilizing Adobe Creative Suite (Photoshop, InDesign, Illustrator).", space_after=bullet_space_p2)
    add_bullet("Financial & Reporting Systems: ", "Conducted ongoing cost/benefit and margin analyses to allocate marketing budgets dynamically, building relational databases for accurate cross-department performance tracking.", space_after=bullet_space_p2)

    # Job 4: The Infinite Agency
    add_job_header("SEM Manager / Project Manager", "The Infinite Agency", "Dallas, TX", space_before=job_space_p2)
    add_bullet("Agency Portfolio Management (75+ Accounts): ", "Built, launched, and managed 75+ Google Ads and paid search accounts with total monthly spend surpassing $276,000, consistently achieving top-tier conversion rates and client ROI benchmarks.", space_after=bullet_space_p2)
    add_bullet("High-Intent Search & Account Sculpting: ", "Structured high-intent search campaigns with precise keyword match types, negative keyword scrubbing, ad copy A/B testing, location extensions, and targeted landing page experiences.", space_after=bullet_space_p2)
    add_bullet("Automated Campaign Monitoring Scripts: ", "Programmed custom scripts in JavaScript/Python to automate real-time bid monitoring, budget pacing, and performance anomaly alerts, a system adopted agency-wide.", space_after=bullet_space_p2)
    add_bullet("Reporting & Client Performance Reviews: ", "Built unified client reporting in Funnel.io and Google Data Studio (Looker Studio), counseling clients across SEO, paid search, remarketing, and monthly promotional campaigns.", space_after=bullet_space_p2)

    # Job 5: LifeSpan Fitness
    add_job_header("E-Commerce & Digital Marketing Manager", "LifeSpan Fitness", "Salt Lake City, UT", space_before=job_space_p2)
    add_bullet("Departmental Leadership & Revenue Impact: ", "Led an 8-person e-commerce and marketing department; managed $400,000+ paid search and advertising budgets generating $9,000,000+ in revenue (35% of total company revenue).", space_after=bullet_space_p2)
    add_bullet("Paid Search Campaign Architecture: ", "Built and managed 150+ high-converting campaigns across Google Ads, Bing Ads, Gemini, and Amazon; conducted keyword research, custom attribution modeling, and multivariate landing page CRO.", space_after=bullet_space_p2)
    add_bullet("Automated Campaign Adjustments: ", "Built automated customer acquisition funnels and developed custom JavaScript automations to optimize promotional ad copy and bidding based on real-time business targets.", space_after=bullet_space_p2)
    add_bullet("Executive Analytics & Reporting: ", "Monitored and reported core KPIs (CPA, ROAS, conversion paths) using Google Analytics, AdWords Editor, Bing Editor, and QuickBooks to guide performance forecasting.", space_after=bullet_space_p2)

    # 5. EDUCATION, LANGUAGES & CERTIFICATIONS
    add_section_header("Education, Languages & Certifications", space_before=job_space_p2 + 0.5)

    p_edu = doc.add_paragraph()
    p_edu.paragraph_format.left_indent = Inches(0.12)
    p_edu.paragraph_format.space_before = Pt(1.0)
    p_edu.paragraph_format.space_after = Pt(1.5)
    p_edu.paragraph_format.line_spacing = line_spacing
    
    r_deg_b = p_edu.add_run("Brigham Young University — Bachelor of Science (B.S.) in Business Management (2008)")
    r_deg_b.bold = True
    r_deg_b.font.size = Pt(font_size_pt - 0.3)
    
    r_deg_honors = p_edu.add_run("  |  Honors: Entrepreneur of the Year Award; Regional Business Plan Competition (Winner, 2 consecutive years)")
    r_deg_honors.font.size = Pt(font_size_pt - 0.3)
    r_deg_honors.font.color.rgb = RGBColor(80, 80, 80)

    p_lang = doc.add_paragraph()
    p_lang.paragraph_format.left_indent = Inches(0.12)
    p_lang.paragraph_format.space_before = Pt(0)
    p_lang.paragraph_format.space_after = Pt(1.5)
    p_lang.paragraph_format.line_spacing = line_spacing
    
    r_lang_h = p_lang.add_run("Languages: ")
    r_lang_h.bold = True
    r_lang_h.font.size = Pt(font_size_pt - 0.3)
    r_lang_h.font.color.rgb = RGBColor(16, 44, 87)
    
    r_lang_b = p_lang.add_run("English (Native)  •  Spanish (Fluent — Professional proficiency for bilingual search marketing and copy translation)")
    r_lang_b.font.size = Pt(font_size_pt - 0.3)

    p_cert = doc.add_paragraph()
    p_cert.paragraph_format.left_indent = Inches(0.12)
    p_cert.paragraph_format.space_before = Pt(0)
    p_cert.paragraph_format.space_after = Pt(1.5)
    p_cert.paragraph_format.line_spacing = line_spacing
    
    r_cert_h = p_cert.add_run("Certifications: ")
    r_cert_h.bold = True
    r_cert_h.font.size = Pt(font_size_pt - 0.3)
    r_cert_h.font.color.rgb = RGBColor(16, 44, 87)
    
    r_cert_b = p_cert.add_run("Google Ads Certified  •  Google Analytics (GA4) Certified  •  Facebook Blueprint Certified (FBC)  •  Bing Ads Certified  •  Amazon Marketing Services (AMS)")
    r_cert_b.font.size = Pt(font_size_pt - 0.3)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.save(output_path)
    print(f"Saved resume to {output_path}")

def render_and_verify():
    docx_p = r"c:\Users\DCALL\Desktop\gecko\output\resumes\Dave-Call+0cf063f21b71b21c.docx"
    pdf_p = r"c:\Users\DCALL\Desktop\gecko\scratch\preview_omni.pdf"
    
    build_omni_resume(docx_p, font_size_pt=10.0, margin_in=0.42, bullet_space_p2=0.8, job_space_p2=2.0)
    
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(os.path.abspath(docx_p))
        doc.Repaginate()
        pages = doc.ComputeStatistics(2)
        doc.SaveAs(os.path.abspath(pdf_p), FileFormat=17)
        doc.Close(False)
    finally:
        word.Quit()
        
    pdf = fitz.open(pdf_p)
    print(f"Word pages: {pages}, PDF pages: {len(pdf)}")
    for i, page in enumerate(pdf):
        pix = page.get_pixmap(dpi=150)
        img_path = f"c:\\Users\\DCALL\\Desktop\\gecko\\scratch\\omni_page_{i+1}.png"
        pix.save(img_path)
        print(f"Saved {img_path}")

if __name__ == "__main__":
    render_and_verify()
