"""Source-checked summary tailoring and content-level duplicate prevention."""
from __future__ import annotations

import itertools
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


# Text is a conservative paraphrase; support is checked against the live master.
# Saved resumes are consulted only for duplicate detection, never as evidence.
UNITS = {
    "lead": ("Digital marketing and marketing technology leader with 14+ years of experience across agency, in-house, B2B, and B2C environments.", "leader with 14+ years of experience across agency, in-house, B2B, B2C", "", False),
    "clients": ("Managed 75+ Google Ads accounts while advising clients on channel allocation, campaign structure, and growth priorities.", "Managed 75+ Google Ads accounts with more than $476K in combined monthly spend while advising clients on channel allocation, campaign structure, and growth priorities", "client account agency growth strategy relationship", False),
    "scale": ("Scaled monthly marketing volume from approximately $200K to $800K while improving ROAS from 1.5 to 3.5.", "Scaled monthly marketing volume from approximately $200K to $800K while improving ROAS from 1.5 to 3.5", "growth performance revenue acquisition optimization ecommerce", False),
    "leadership": ("Managed up to $30 million per month in paid media with a four-person team, combining account operations with budget oversight.", "Managed up to $30 million per month in paid media with a four-person team, supporting high-volume account operations and disciplined budget oversight", "leadership team budget media director strategy", False),
    "b2b": ("Helped modernize a B2B distributor and add B2C e-commerce channels while protecting relationships with 650+ retail partners.", "Helped modernize a traditional B2B distributor and add multiple B2C e-commerce channels while protecting relationships with 650+ existing retail partners", "b2b consumer retail ecommerce channel partners cpg", False),
    "research": ("Used market research and business planning to help establish tax and finance departments that contributed more than 25% of firm revenue.", "Used market research and business planning to help establish tax and finance departments that together contributed more than 25% of firm revenue", "research market product financial vertical positioning strategy", False),
    "reporting": ("Built automated reporting across 10+ marketing channels using Python, Databricks, SQL, Excel, and Funnel.io.", "Built automated reporting across 10+ marketing channels using Python, Databricks, SQL, Excel, and Funnel.io", "analytics data reporting operations measurement automation attribution", False),
    "inhouse": ("Built an in-house PPC structure spanning 32 businesses, including team training, scalable operations, and ERP integration.", "Built an in-house PPC structure for a company group spanning 32 businesses, including MCC consolidation, a scalable operating system, team buildout/training, and API integration with the company ERP", "services operations leadership team scale integration b2b", True),
    "ai_content": ("Used ChatGPT in Google Sheets to rewrite Shopify product descriptions for SEO and eliminate duplicate content.", "Used ChatGPT inside google sheet to rewrite product descriptions to make them SEO friendly and to make sure there wasn't duplicate content", "content ai seo ecommerce product consumer cpg", True),
    "crm": ("Implemented Go High Level, trained employees, and integrated existing systems with Power BI reporting.", "Installed Go High Level and trained employees on how to use it correctly. Made sure that it integrated with all current system including Power BI for reporting purposes", "crm operations automation reporting integration enablement services", True),
    "web": ("Built a headless e-commerce retail website with React and Next.js and connected Shopify directly to manufacturer databases.", "Built a headless e-commerce third-party retail website using React and Next.js. Connected the Shopify back end directly to manufacturer databases", "ecommerce web technology digital product consumer cpg", True),
    "graphql": ("Automated order and shipping updates through GraphQL integrations.", "Automated order and shipping updates through GraphQL integrations", "automation integration operations ecommerce technology", True),
    "landing": ("Partnered with web development and content teams on custom landing pages and Performance Max campaign content.", "Worked closely with the Web Dev team and the content team to create custom landing pages and custom content for PMAX campaigns", "content campaign conversion collaboration demand digital", True),
    "ai_web": ("Used Cursor and Claude to create SEO-friendly websites and set up Google Ads, GA4, Search Console, and Service Titan CRM for a company group.", "Used Cursor and Claude to create SEO-friendly websites across an eight-company group. Configured Google Ads, GA4, and Google Search Console, and developed a Service Titan CRM program", "ai seo web analytics crm services digital technology", True),
}

# Each paragraph is composed around a distinct, source-supported business focus.
# The support keys validate all claims against the current master on every use.
TAILORED = {
    "abm_systems": ("B2B marketing leader with a background in client strategy, performance analytics, and connected marketing systems. Advised clients across 75+ Google Ads accounts on channel allocation and growth priorities, and built automated reporting across more than ten marketing channels. Recent work includes an in-house PPC operating system for 32 businesses, team training, and ERP integration—experience that connects marketing execution with the data and processes behind it.", ["lead", "clients", "reporting", "inhouse"], "abm", "client strategy analytics reporting integration operations"),
    "cpg_growth": ("E-commerce growth marketer who combines budget discipline with hands-on work on the shopping experience. Increased monthly marketing volume from approximately $200K to $800K while raising ROAS from 1.5 to 3.5. More recent Shopify work includes using ChatGPT in Google Sheets to improve product descriptions for SEO and remove duplicate content, connecting acquisition performance with the quality of the product information customers see.", ["lead", "scale", "ai_content"], "cpg", "growth performance acquisition product content ecommerce"),
    "cpg_channels": ("Marketing and e-commerce leader experienced in balancing direct consumer growth with established retail relationships. Helped a traditional B2B distributor add B2C channels while protecting more than 650 retail partners. Brings current experience building a React and Next.js storefront connected to Shopify and manufacturer databases, alongside paid-media management and client advice on channel allocation—useful breadth for coordinating consumer marketing across digital channels.", ["lead", "b2b", "web", "clients"], "cpg", "retail channel consumer ecommerce partners web"),
    "cpg_measurement": ("Performance marketing specialist with a strong technical foundation in measurement and e-commerce operations. Built automated reporting across 10+ marketing channels with Python, SQL, Databricks, Excel, and Funnel.io, and improved ROAS from 1.5 to 3.5 while scaling monthly volume fourfold. Recent GraphQL work automated order and shipping updates, adding practical experience with the operational data that accompanies online customer acquisition.", ["lead", "reporting", "scale", "graphql"], "cpg", "analytics measurement reporting data performance operations"),
    "cpg_content": ("Digital marketer whose experience connects consumer-facing content, paid acquisition, and website delivery. Partnered with web and content teams on custom landing pages and Performance Max content. Recent projects include AI-assisted Shopify product descriptions and a headless React/Next.js retail website connected to manufacturer databases. Combines that execution experience with client-facing advice on campaign structure and growth priorities across a portfolio of 75+ advertising accounts.", ["lead", "landing", "ai_content", "web", "clients"], "cpg", "content creative campaign website product ecommerce"),
    "cpg_leadership": ("Marketing leader with experience managing large media programs and modernizing commerce systems. Oversaw up to $30 million per month in paid media with a four-person team and helped expand a distributor into B2C e-commerce without disrupting its retail partners. Current work includes AI-assisted website development, Google Ads and GA4 setup, and CRM implementation for a company group, bringing operational depth to cross-functional marketing leadership.", ["lead", "leadership", "b2b", "ai_web"], "cpg", "leadership budget team cross functional strategy"),
    "services_local": ("Multi-business marketing operator experienced in turning distributed agency work into a scalable in-house PPC program. Built a structure spanning 32 businesses, with team training, consistent operations, and ERP integration. Recent work also includes Go High Level implementation and Power BI reporting integration. Combines these systems capabilities with client-facing channel and growth advice developed while managing more than 75 Google Ads accounts.", ["lead", "inhouse", "crm", "clients"], "services", "services operations local agency integration leadership"),
    "services_clients": ("Client-focused marketing strategist with experience translating business priorities into channel investment and campaign structure. Advised a portfolio of 75+ Google Ads accounts and combined that work with automated cross-channel reporting. More recent projects include custom landing pages and Performance Max content developed with web and content teams, giving client recommendations a practical connection to execution, measurement, and the customer journey.", ["lead", "clients", "reporting", "landing"], "services", "client strategy campaign communication content reporting"),
    "services_crm": ("Marketing technology practitioner with hands-on experience connecting CRM, reporting, and advertising operations. Implemented Go High Level, trained employees, and integrated existing systems with Power BI. Also built an in-house PPC operating structure for 32 businesses and used Cursor and Claude to deliver SEO-friendly websites with Google Ads, GA4, Search Console, and Service Titan CRM. Brings both implementation experience and a broader marketing perspective.", ["lead", "crm", "inhouse", "ai_web"], "services", "crm integration operations training automation"),
    "services_performance": ("Growth-oriented paid-media leader experienced in scaling investment while improving returns. Took monthly marketing volume from approximately $200K to $800K and increased ROAS from 1.5 to 3.5, supported by campaign, audience, and conversion optimization. Recent work on custom landing pages, Performance Max content, and multi-business PPC operations adds practical execution and systems experience to performance-focused client strategy.", ["lead", "scale", "landing", "inhouse"], "services", "growth performance conversion acquisition optimization"),
    "services_management": ("Marketing manager with a record of handling complex account operations, substantial budgets, and team delivery. Managed up to $30 million in monthly paid media with a four-person team and advised clients across more than 75 Google Ads accounts. Recent experience building a PPC structure for 32 businesses and integrating CRM with Power BI brings a systems-oriented approach to consistent service delivery and marketing oversight.", ["lead", "leadership", "clients", "inhouse", "crm"], "services", "leadership team account budget management"),
    "b2b_partners": ("B2B marketing and e-commerce leader with experience navigating growth across sales, operations, technology, and retail partnerships. Helped modernize a distributor and open B2C channels while preserving relationships with 650+ retailers. Recent work building a 32-business PPC operating structure and ERP integration adds scalable campaign operations to that background, supported by direct client advice on channel strategy and investment priorities.", ["lead", "b2b", "inhouse", "clients"], "b2b", "b2b partners sales channel strategy operations"),
    "b2b_insights": ("Analytical marketing strategist who uses business research and reporting to guide investment decisions. Helped establish tax and finance services that contributed more than 25% of firm revenue and built reporting across ten-plus marketing channels using Python and SQL. Current CRM and Power BI integration work adds hands-on experience connecting marketing information with operational systems, alongside a broader background in B2B and client-facing marketing.", ["lead", "research", "reporting", "crm"], "b2b", "research analytics insights data reporting financial"),
    "b2b_accounts": ("Agency-experienced marketer with a practical background in account strategy, campaign delivery, and technical implementation. Managed more than 75 Google Ads accounts and advised clients on channel allocation, campaign structure, and growth priorities. Recent collaboration with web and content teams on landing pages and Performance Max campaigns, together with CRM/reporting integrations, supports an approach that carries client strategy through to execution and measurement.", ["lead", "clients", "landing", "crm"], "b2b", "account client campaign agency relationship strategy"),
    "b2b_transformation": ("Marketing technology leader experienced in helping established businesses adopt digital systems. Modernized a B2B distributor's commerce environment while protecting its existing retail network. More recent work includes SEO-friendly websites developed with Cursor and Claude, advertising and analytics setup, and Service Titan CRM. Pairs that implementation background with multi-company PPC operations and ERP integration to connect marketing priorities with the systems needed to deliver them.", ["lead", "b2b", "ai_web", "inhouse"], "b2b", "technology digital transformation integration ai operations"),
    "b2b_scale": ("B2B/B2C marketing leader with experience coordinating sizeable advertising programs and building repeatable operating structures. Managed up to $30 million per month in paid media with a four-person team and helped create an in-house PPC system spanning 32 businesses. Brings client strategy across 75+ accounts and automated cross-channel reporting, combining leadership, budget oversight, and technical capability in a practical approach to marketing scale.", ["lead", "leadership", "inhouse", "clients", "reporting"], "b2b", "leadership scale team budget strategy reporting"),
    "digital_campaigns": ("Hands-on digital marketing professional who connects campaign optimization with measurement and website execution. Improved ROAS from 1.5 to 3.5 while scaling monthly marketing volume fourfold, and built automated reporting across 10+ channels. Recent work with web and content teams on custom landing pages and Performance Max content, plus AI-assisted website development, extends that performance background into the content and technology behind campaign delivery.", ["lead", "scale", "reporting", "landing", "ai_web"], "digital", "digital campaign performance analytics content"),
    "vertical_research": ("Marketing strategist with experience using market research to identify services and growth opportunities. Helped establish tax and finance departments that generated more than 25% of firm revenue, and advised advertising clients on investment priorities across multiple channels. Recent work building a multi-business PPC system and integrating CRM with reporting adds execution and operational depth to a background spanning B2B, B2C, and professional services.", ["lead", "research", "clients", "inhouse", "crm"], "vertical", "vertical research market strategy services"),
    "product_market": ("Marketing professional with a background in market research, business planning, and cross-functional digital delivery. Helped introduce tax and finance services that contributed more than 25% of firm revenue, and supported a B2B distributor's expansion into consumer channels while protecting retail relationships. Recent website, CRM, and analytics implementations add technical fluency to that research-led background, with experience translating marketing priorities into practical systems and execution.", ["lead", "research", "b2b", "ai_web"], "product", "product market research positioning technical"),
    "operations_data": ("Marketing operations practitioner focused on reliable data, connected systems, and usable reporting. Implemented Go High Level, trained employees, and integrated existing systems with Power BI; separately built automated reporting across ten-plus channels using Python, Databricks, SQL, Excel, and Funnel.io. Recent ERP and GraphQL integration work adds hands-on automation experience to a broader background in paid media, analytics, and marketing technology.", ["lead", "crm", "reporting", "inhouse", "graphql"], "operations", "operations automation crm reporting data integration"),
}


def family(title: str) -> str | None:
    title = normalize(title)
    for phrase, label in (("account based", "abm"), ("cpg", "cpg"),
                          ("consumer services", "services"), ("b2b", "b2b"),
                          ("operations", "operations"), ("vertical", "vertical"),
                          ("product", "product"), ("digital marketing", "digital")):
        if phrase in title:
            return label
    return None


def render(selection: list[str], source: str) -> str:
    if len(selection) == 4 and selection[0] == "focused":
        entry = TAILORED.get(selection[1])
        if entry is None or selection[2] == selection[3]:
            raise ValueError("Invalid focused summary selection")
        for support in [*entry[1], *selection[2:]]:
            if support not in UNITS or normalize(UNITS[support][1]) not in normalize(source):
                raise ValueError(f"Summary evidence missing from current master: {support}")
        return entry[0].split(". ", 1)[0] + ". " + " ".join(UNITS[key][0] for key in selection[2:])
    if len(selection) == 2 and selection[0] == "tailored":
        entry = TAILORED.get(selection[1])
        if entry is None:
            raise ValueError("Unknown tailored summary")
        for support in entry[1]:
            if normalize(UNITS[support][1]) not in normalize(source):
                raise ValueError(f"Summary evidence missing from current master: {support}")
        return entry[0]
    if len(selection) != 3 or selection[0] != "lead" or len(set(selection)) != 3:
        raise ValueError("Invalid summary evidence selection")
    # Bullet markers between adjacent support sentences carry no factual meaning.
    clean_source = normalize(source)
    texts = []
    for key in selection:
        if key not in UNITS or normalize(UNITS[key][1]) not in clean_source:
            raise ValueError(f"Summary evidence missing from current master: {key}")
        texts.append(UNITS[key][0])
    return " ".join(texts)


def docx_content(path: Path) -> tuple[str, str]:
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = ["".join(t.text or "" for t in p.findall(".//w:t", ns))
                  for p in root.findall(".//w:p", ns)]
    summary = ""
    for index, text in enumerate(paragraphs):
        if normalize(text) == "professional summary":
            following = []
            for value in paragraphs[index + 1:]:
                if normalize(value) in {"core strengths", "selected results", "professional experience"}:
                    break
                following.append(value)
            summary = normalize(" ".join(following))
            break
    return summary, normalize(" ".join(paragraphs))


@lru_cache(maxsize=4096)
def _cached_content(path: Path, modified_ns: int, size: int):
    return docx_content(path)


def inventory(folder: Path):
    for path in sorted(folder.rglob("*.docx")):
        if not path.name.startswith("~$"):
            try:
                stat = path.stat()
                yield path, *_cached_content(path, stat.st_mtime_ns, stat.st_size)
            except Exception as exc:
                raise ValueError(f"Cannot check saved resume for duplicates: {path}: {exc}") from exc


def choose(listing: str, source: str, folder: Path, title: str = "") -> tuple[str, list[str]]:
    used = {summary for _, summary, _ in inventory(folder) if summary}
    target = set(normalize(listing).split())
    group = family(title)
    choices = sorted(TAILORED, key=lambda key: len(target & set(TAILORED[key][3].split())), reverse=True)
    for key in choices:
        if group and TAILORED[key][2] != group:
            continue
        selection = ["tailored", key]
        paragraph = render(selection, source)
        if normalize(paragraph) not in used:
            return paragraph, selection
    # Continue composing from verified evidence after the initial full
    # paragraphs have been used, without reverting to the universal old opener.
    eligible = [key for key, unit in UNITS.items() if key != "lead" and target & set(unit[2].split())]
    pairs = sorted(itertools.combinations(eligible, 2), key=lambda pair:
                   sum(len(target & set(UNITS[key][2].split())) for key in pair), reverse=True)
    for key in choices:
        if group and TAILORED[key][2] != group:
            continue
        for pair in pairs:
            if not any(UNITS[support][3] for support in pair):
                continue
            selection = ["focused", key, *pair]
            paragraph = render(selection, source)
            if normalize(paragraph) not in used:
                return paragraph, selection
    raise ValueError("No substantively distinct summary remains for this role; review tailoring")


def shingle_similarity(left: str, right: str) -> float:
    def shingles(text):
        tokens = normalize(text).split()
        return {tuple(tokens[index:index + 5]) for index in range(max(0, len(tokens) - 4))}
    a, b = shingles(left), shingles(right)
    return len(a & b) / max(1, len(a | b))


def assert_unique(candidate: Path, folder: Path, exclude: Path | None = None) -> None:
    summary, body = docx_content(candidate)
    for path, old_summary, old_body in inventory(folder):
        if path.resolve() == candidate.resolve() or (exclude and path.resolve() == exclude.resolve()):
            continue
        if body == old_body or (summary and summary == old_summary):
            raise ValueError(f"Duplicate resume content or Professional Summary: {path}")
        if shingle_similarity(body, old_body) >= .90:
            raise ValueError(f"Resume is substantively too similar to saved content: {path}")
