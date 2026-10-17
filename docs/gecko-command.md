# Gecko command

When the user says **run Gecko**, start the Windows Scheduled Task named
`Gecko` through `scripts/Start-Gecko.ps1`. In a terminal, the command is
`Gecko`. `Gecko --status` shows the task state and pipeline progress.

The on-demand task uses `scripts/run_gecko.py` from this Gecko Main checkout.
It has no clock-based trigger. Do not invent a recurring start time.

The stages are:

1. Run `scripts/daily_report.py --dry-run`, the existing report-writing command
   for Daily Tasks and Daily Run.
2. Run `scripts/gecko_daily.py --apply --sync-local`: discovery and job-list
   updates, local tracker synchronization before the resume queue, tailored
   resumes for approved eligible jobs, response tracking, and run history.
3. Pull the final live tracker again into the local SQLite mirror, full-cell
   JSON, current schema reference, Scratch reference, and Cursor rule.
4. Refresh today's Daily Tasks dashboard with the resulting tracker state.

The latest local references are `docs/live-tracker-schema.md`,
`docs/scratch-column-ideas.md`, and `job-scout/data/tracker-live.json`.
Existing authoritative instructions remain in AGENTS.md and GECKO_SYSTEM.md.
This sync operates inside Gecko Main; it does not change the separate v2 checkout.

Approved `Apply? = Yes` jobs still require the established eligibility checks.
Existing Resume Created = X and existing links prevent regeneration.
No application submissions or resume archiving are part of this command.

The task runs hidden as the logged-in user. Windows ignores duplicate task
starts, and the pipeline also holds a lock. A failed stage stops subsequent
stages and records its exit code. Logs and status are saved in
`reports/gecko-command/`. To add stages later, edit the ordered `STEPS` in
`scripts/run_gecko.py`.

## Run Gecko button — SQLite daily workflow

The dashboard runs scripts/run_gecko.py without a resume-ID limit. The ordered
steps are daily report, full daily discovery and eligible resume queue, local
backup, then final daily report. SQLite remains authoritative. Google Sheets
exports run only when you click **Export to Google Sheets** under **Local workspace**.
Each export creates a new dated tab in the configured workbook,
including custom fields and resume links, without overwriting historical tabs.
The latest manual export link and verification state appear in Activity.

Apply? = Yes resumes use the canonical generator, current master TXT, approved
PDF formatting model, and native Word two-page checks. Existing completion
markers or resume links block regeneration; eligibility, fee, rejection, and
already-applied guards remain active. A failed daily phase still runs the final
backup/report; any failed phase keeps the overall run marked failed.
A failed initial report stops the run before discovery or generation.
