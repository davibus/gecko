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
