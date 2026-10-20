# Gecko Resume Format Model

The sole default visual authority is:

`input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf`

Follow it as closely as practical for:

- Clean white background
- Professional, compact two-page US Letter design
- Centered three-line header
- EB Garamond typography (11 pt main text)
- Olive (`#556B2F`) uppercase section headings with thin rules
- Compact margins and spacing
- Section hierarchy: Professional Summary; Core Strengths; Selected Results; Professional Experience; Tools & Platforms; Education & Certifications
- CORE STRENGTHS is mandatory: use at least 8 job-relevant, master-supported entries in professional Title Case; use more when useful.
- TOOLS & PLATFORMS is mandatory: use at least 8 job-relevant, master-supported products/platforms with official brand capitalization; generic capabilities belong under Core Strengths, not here.
- Every Professional Experience entry uses one physical line: `Job Title - Company Name - City, ST` at left and verified employment dates flush right. Use a single space around each normal hyphen. Keep the complete heading in one bold paragraph/run without breaks or tabs; use a borderless, zero-padding two-column table with a right-aligned date paragraph. Compact only verified month names, and make minimal heading-only formatting adjustments if needed. Fail validation if the fields wrap or overlap. Accomplishments follow below.
- Bullet styling, alignment, density, and overall appearance
- 1.15 line spacing
- Header contact line ends with `linkedin.com/in/mdavidcall` and does not include Spanish or other language proficiency
- No visible table borders
- Verified job dates appear at the same right text margin on every employment line
- Before final save, auto-correct and validate mandatory section counts/capitalization, complete single-line job headings with source dates, and absence of lowercase placeholder entries. Confirm each rendered heading and its date share one physical line.
- Exactly two pages is necessary but not sufficient when useful, job-relevant evidence remains. Education & Certifications should finish within approximately 0.5 inch (36 points) above the normal bottom text boundary on page two. Use distinct, source-supported accomplishments and relevant project detail, prioritizing the most relevant roles; there is no fixed two- or three-bullet ceiling. Keep standard sections, readable model typography, and normal margins/spacing. Do not fill space with larger fonts, inflated spacing, blank paragraphs, repeated claims, unrelated material, or an education footer/text box. Inspect both rendered pages and measure the final section after native Word/PDF validation. If genuinely relevant evidence is exhausted, document the reviewed evidence and explain the remaining gap; page count alone is not completion.

The model PDF supplies layout only. Its content is not evidence unless independently present in `input/master-resume/master-resume-v4.docx`. Do not substitute another PDF, DOCX, or tailored resume unless the user explicitly requests a one-resume exception.


## Permanent short resume filename rule

Resume filenames must use `Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`, ending in a unique numeric identifier of at most five digits (Gecko uses five zero-padded digits). Never put a full posting ID, Indeed jk, UUID, hash, or long numeric job number in a resume filename. Keep filenames at most 150 characters, sanitizing Windows-invalid characters and shortening an excessively long title at a word boundary. Reserve identifiers through `job-scout/resume_naming.py`; do not truncate a source ID or guess uniqueness. Full posting IDs remain in the identity registry and DOCX metadata for job matching. Use the same rule for explicitly requested renames, verify tracker links after any rename, and preserve the existing Resume Created = X guard. Archived job descriptions and scratch folders continue to use full posting IDs.

Example: `Dave-Call+Array+Digital-Marketing-Manager+00001.docx`.

User-confirmed version 4 exception: if an employment title is omitted in the master, retain the verified company and location without inventing a title. The master archive itself has no one-line or page-limit requirement; apply layout rules only to the finished resume.
