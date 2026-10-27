# Gecko from Job URL

Use Gecko for this job: "put job URL here"

Execute this workflow live by default. Generate the real resume, make the necessary Gecko-managed tracker updates, and verify the saved file and affected cells by reading them back. Do not substitute a dry run or ask for redundant confirmation.

Read the listing, identify the job number, archive it, and create the V2 tailoring plan with `scripts/gecko_v2.py plan` before modifying the resume. Review its evidence and gaps, then generate the DOCX and run Word-native QA with `scripts/gecko_v2.py generate`. Generate:
Before generation, read the matching live Job Scout row by stable identity. A normalized `Resume Created = X` stops generation and preserves its marker and link, even when the link is blank; report a blank link for manual review.
1. The exactly two-page DOCX resume under `output/resumes/Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx` using `scripts/`.
2. The archived listing under `input/job-descriptions/<Company-Name>+<job-number>.md`.
3. After items 1-2 are successfully created and `v2-qa.json` reports a native Word QA pass, upsert the job in the canonical Google Sheet with `scripts/manage_job_tracker.py add` and validate the tracker. Do not create or update a local Excel tracker.

Ensure a dedicated scratch subfolder `scratch/{Company-Name}+{JobNumber}/` is created for all temporary files (preview PNGs, PDFs, layout verification images, intermediate files). Sanitize company names for Windows filenames. Reusable tools and scripts reside in `scripts/`.

Follow all rules in `GECKO_SYSTEM.md` and `AGENTS.md`.
This includes the permanent minimum of 8 professionally capitalized Core Strengths, 8 officially capitalized Tools & Platforms, and a complete one-physical-line `Job Title - Company Name - City, ST` heading for every Professional Experience entry. Verified employment dates must align flush right on that same physical line; Gecko V2 Word QA rejects wrapped or overlapping fields.


## Permanent short resume filename rule

Resume filenames must use `Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`, ending in a unique numeric identifier of at most five digits (Gecko uses five zero-padded digits). Never put a full posting ID, Indeed jk, UUID, hash, or long numeric job number in a resume filename. Keep filenames at most 150 characters, sanitizing Windows-invalid characters and shortening an excessively long title at a word boundary. Reserve identifiers through `job-scout/resume_naming.py`; do not truncate a source ID or guess uniqueness. Full posting IDs remain in the identity registry and DOCX metadata for job matching. Use the same rule for explicitly requested renames, verify tracker links after any rename, and preserve the existing Resume Created = X guard. Archived job descriptions and scratch folders continue to use full posting IDs.

Example: `Dave-Call+Array+Digital-Marketing-Manager+00001.docx`.

## Resume content density

Exactly two pages is necessary but not sufficient when useful, job-relevant evidence remains. Education & Certifications should finish within approximately 0.5 inch (36 points) above the normal bottom text boundary on page two. Use distinct, source-supported accomplishments and relevant project detail, prioritizing the most relevant roles; there is no fixed two- or three-bullet ceiling. Keep standard sections, readable model typography, and normal margins/spacing. Do not fill space with larger fonts, inflated spacing, blank paragraphs, repeated claims, unrelated material, or an education footer/text box. Inspect both rendered pages and measure the final section after native Word/PDF validation. If genuinely relevant evidence is exhausted, document the reviewed evidence and explain the remaining gap; page count alone is not completion.

## Job-specific resume headline - user instruction October 26, 2026

For EVERY resume, customize the specialization/main title directly below Dave's
name to the exact job's responsibilities, priorities, and required skills. Read
`Variations of Specialization/Main Titles` in the current
`input/master-resume/master-resume-v4.docx`. These are examples, not a closed list:
select, combine, or create the best concise, natural headline supported by Dave's
actual master-resume experience. Lead with the most relevant specialization; omit
unrelated areas and unsupported expertise, seniority, credentials, or claims.
Never automatically reuse `Marketing Technology/AI | Paid Media | E-Commerce |
Analytics | Digital Marketing` across jobs. It is acceptable only when its full
emphasis is genuinely the best fit after reviewing that specific posting.

Review the headline together with the summary and supporting accomplishments,
then inspect its rendered fit in the established header and two-page layout.
The generator ranks master examples as an initial suggestion; the agent must
review suitability and may create better wording. For a custom headline, call
`scripts/gecko_v2.py`'s `set_reviewed_headline(plan, headline, rationale)` before
generation, recording why its claims are supported and relevant. Never bypass
headline validation or copy the master default into every plan. This headline is
professional positioning; preserve verified employment titles and filename/job
identity rules. Existing completed resumes are not regenerated without a request.

## Usable Google Sheets resume links - October 26, 2026

Dave explicitly selected PRIVATE GOOGLE DRIVE LINKS, usable across devices.
Every new resume's Resume Link must be a clickable HTTPS link to the exact
completed DOCX in his private Drive. Keep the validated local DOCX for job
applications. A raw local path or `file:///` URI is not usable in Google Sheets;
HYPERLINK cannot fix that unsupported protocol. This instruction supersedes all
earlier no-upload and raw-file-URI requirements for resume delivery only. Never
make resumes public, convert the validated DOCX, or share them with others.

After native Word and visual QA, upload the exact final DOCX with the connected
Google Drive `upload_file` tool, preserving its filename and DOCX MIME type. Use
the private folder configured in `job-scout/preferences/resume-delivery.json`:
`https://drive.google.com/drive/folders/1Noy8XUqlL5ufqA4aU9jZWdwpMYeCVmol`.
Reuse a verified unchanged upload instead of creating duplicates. Read back the
Drive metadata (ID, observed URL, filename, MIME type, size, parents and private
owner-only permissions), download its raw bytes and compare SHA-256 with the
local DOCX. Save a receipt JSON containing `path`, `metadata` from that readback,
and `download: {"sha256": "<actual downloaded SHA-256>"}`. Register it using
`scripts/register_resume_drive_link.py --receipt <receipt.json>`.

The canonical publisher resolves that verified receipt to its observed HTTPS
URL. Write Resume Link as a clickable Google Sheets hyperlink, verify the cell's
actual hyperlink target, and preserve completion dates, job identity, formulas,
formatting and unrelated fields. Resume Created still requires all existing QA
and completion safeguards. If the connector is unavailable, retain the finished
local file and report Private Drive publication pending; do not silently fall
back to file:/// or claim a working tracker link. Unattended queue runs without
a registered delivery receipt stop at this publication gate and need a connected
agent to perform the upload. Dashboard and applications resolve registered Drive
URLs back to the unchanged local file through `job-scout/resume_delivery.py`.

## Canadian remote jobs allowed - user instruction October 26, 2026

Dave explicitly instructed: If it is Canada, allow it. Treat Canadian remote
jobs, including Canada-only postings and country codes CA/CAN, as geographically
eligible for Gecko discovery, qualification, resume queues and tracker review.
Do not set Qualifies to Apply? to No solely because the country is Canada or the
ATS applicant country is Canadian. This supersedes earlier U.S./Utah-only remote
country restrictions for Canada. Marketbridge ID 2983 is the confirmed example.

Keep other safeguards: fees, permanent rejections, completed-resume protection,
match thresholds, usable job descriptions, and genuine additional location or
residency restrictions. Required Eastern working hours alone are not an Eastern
residency restriction. This does not authorize inventing Canadian citizenship,
work authorization, residency or willingness to relocate; answer application
questions truthfully and surface any unsupported mandatory requirement. The
exception permits remote Canada jobs; it does not make Canadian onsite/hybrid
jobs local Utah jobs or permit every other foreign-country requisition.
