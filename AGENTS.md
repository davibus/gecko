# Gecko Main — essential instructions

- Canonical project: `C:\gecko_main` (`gecko_main`, not the retired `gecko_website`).
  Preserve unrelated changes, credentials, resumes, job data, and manual fields.
  Opening the workspace must not launch tasks or scripts. Use native Windows.
- **SQLite is authoritative:** `job-scout/preferences/tracker-backend.json` selects
  the backend; `job-scout/data/jobs.sqlite3` owns current tracker state. This rule
  supersedes older Sheets wording in other files. Never import/sync Sheets over
  SQLite or revert the backend. Sheets exports are manual via the dashboard only;
  daily runs retain local backups. See `docs/sqlite-workspace.md` when needed.
- Execute requested work through the canonical live path and verify actual results
  by readback. Preserve protected/manual fields, stable job identity, eligibility,
  fee and rejection exclusions. Do not infer permission for unrelated actions,
  schedules, messages, purchases, or applications from setup or a normal daily run.
- **Existing resume guard:** trimmed/case-insensitive `Resume Created = X` always
  blocks regeneration, even with a blank link. Preserve it and report missing links
  for review; do not backfill. A link with a blank marker also requires review.
- **Resume authorities:** facts only from `input/master-resume/master-resume-v4.docx`;
  layout only from `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf`.
  Re-read sources for generation, invent no claims, and stop if either is missing.
  Final DOCX must pass native Word validation as exactly two pages before completion.
- “Run Gecko” uses the existing `Gecko` task via `scripts/Start-Gecko.ps1`;
  `Gecko --status` checks progress. Read the operations guide first, do not duplicate
  an active run, and do not invent a schedule. It does not submit applications.

## Load only the guide needed for the task

These guides are mandatory for their matching work, not a startup reading list.
Follow their additional references only when the relevant workflow requires them.

| Work | Required guide |
| --- | --- |
| Daily run, runner, workspace or terminals | `docs/agent-guides/operations.md` |
| Resume generation, tailoring, naming or Word QA | `docs/agent-guides/resumes.md` and `GECKO_SYSTEM.md` |
| Tracker, discovery, approvals, reports or resume queue | `docs/agent-guides/tracker.md` |
| Requested applications or application automation | `docs/agent-guides/applications.md`; custom answers remain in `openclaw/application-answers.md` |
| Dashboard table changes | `dashboard/AGENTS.md` |
| Explicit work on the preserved Google Sheet | `docs/agent-guides/legacy-sheets.md` |

Keep workflow details in these guides rather than expanding this root file.
Dave's detailed resume rules and custom answers remain binding in their task scope.

For each job description, select only relevant, source-supported facts from the version 4 master. The master is a career archive, not content to include in full; keep the established two-page resume format.

User-confirmed version 4 exception: if an employment title is omitted in the master, retain the verified company and location without inventing a title. The master archive itself has no one-line or page-limit requirement; apply layout rules only to the finished resume.

Read the version 4 Word master directly for every resume, including paragraphs, tables, and list items. No text export, older master, or cover letter is an alternate factual source. Fill as much of both pages as practical with relevant, distinct, master-supported evidence; never add filler or inflate spacing to fill pages. The master cover letter is reserved for a later explicit request.

## Resume content density

Exactly two pages is necessary but not sufficient when useful, job-relevant evidence remains. Education & Certifications should finish within approximately 0.5 inch (36 points) above the normal bottom text boundary on page two. Use distinct, source-supported accomplishments and relevant project detail, prioritizing the most relevant roles; there is no fixed two- or three-bullet ceiling. Keep standard sections, readable model typography, and normal margins/spacing. Do not fill space with larger fonts, inflated spacing, blank paragraphs, repeated claims, unrelated material, or an education footer/text box. Inspect both rendered pages and measure the final section after native Word/PDF validation. If genuinely relevant evidence is exhausted, document the reviewed evidence and explain the remaining gap; page count alone is not completion.
