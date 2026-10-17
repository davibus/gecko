# Gecko execution and workspace preferences

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
