# Gecko execution and workspace preferences

## Columns follow names, not positions

Users may move whole columns freely without asking for code or instruction updates.
Read live headers on every sync; use unique header names for fields and stable IDs
for jobs. Never restore a saved order or treat column letters/counts in documentation
as requirements. Automatic idle sync adopts the current order and preserves custom
columns, resume links and Sheet formulas. Moving columns is different from renaming
or deleting a field: missing or ambiguous names must be resolved without guessing.
Keep row 1 frozen. Historical layout tables are reference snapshots only.


## Current tracker columns

Use `docs/current-tracker-columns.md` for the current 36-column Sheet layout and field behavior. Its current-layout rules supersede historical column letters and tracker-authority text in this document. Resolve fields by unique name and jobs by ID, preserve formulas and all jobs/resumes, and always keep row 1 frozen. The qualification field is Qualifies to Apply?; Applied Date is primary and Previous Applied Date is history. Create Resume follows the saved Enough Data value and does not itself trigger generation.


Read for running Gecko, changing its runner, or managing the workspace/terminals.
The root AGENTS.md and docs/sqlite-workspace.md control storage: any preserved
Google Sheet wording below refers to the retired workflow, not permission to
import, export, or synchronize it during current SQLite runs. For the current
daily sequence, use the SQLite daily workflow section of docs/gecko-command.md.

## Canonical project name
## Run Gecko command

When the user says **run Gecko**, start the on-demand Windows task named
`Gecko` with `scripts/Start-Gecko.ps1` (terminal command: `Gecko`).
Use `Gecko --status` for progress. Follow `docs/gecko-command.md` for the
ordered daily report, discovery, local tracker/Cursor sync, tailored approved
resume workflow, and final refresh. Do not start a second run while it is
active. No clock-based schedule has been requested.
## Canonical project identity

The canonical project name is **Gecko Main** and its canonical directory is `gecko_main`. The former directory/name `gecko_website` is deprecated. All new scripts, documentation, commands, paths, and configuration must use Gecko Main and `gecko_main`. Do not rename the current project root or any external resource as part of this naming rule.
## Cursor terminals

See `docs/cursor-terminals.md` for the global persistence settings and workspace-specific terminal behavior. Preserve restored sessions and their existing names and working directories. Opening the workspace must not launch terminal tasks or project scripts.
## Execution default

Execute the live write path by default for requested work. Implement the requested change and run the affected canonical workflow so the real files and configured Google Sheet results are visible. Do not substitute a dry run, preview, simulation, mock execution, or instructions for an authorized live execution, and do not stop after editing code when execution is necessary to complete the request. Explicit dry-run and other read-only commands remain available only when the user requests them or when the command is inherently diagnostic.

Authorization covers the requested work and its necessary writes, including generated resumes and managed tracker cells. It does not authorize unrelated actions, job applications, messages, purchases, destructive operations, or bypassing access restrictions. Preserve eligibility rules, Cost `x` exclusion, duplicate prevention, protected/manual fields, and unrelated data. After every live tracker write, read the affected cells back and verify the expected values and resume link target. If execution is blocked, report the exact blocker and what actually changed; never claim a live write succeeded without verification. Do not ask the user to reconfirm actions already authorized by the request.

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
