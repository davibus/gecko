# Gecko Main Codex usage ledger

This folder records every Codex task found in the local session transcripts, across working directories. The original Codex JSONL remains under `%USERPROFILE%\.codex\sessions`; this tool reads it and stores selected metadata and observed token counters in `codex_usage.sqlite3`. `codex_usage.xlsx` is a regenerated view of that database. Its **Tasks** tab has one row per Codex session/chat; **Turns** shows each prompt and follow-up. The working directory identifies the project for each row.

## Automatic collection

The Windows task `Gecko Main Codex Usage Collector` runs `launch_collector.vbs` through `wscript.exe` every five minutes. The launcher runs the existing `run_collector.ps1` hidden and writes stdout, stderr, and the exit code to timestamped files in `usage/logs/`. The task and script both prevent overlapping runs. It scans local Codex session files from the last three Mountain dates, files modified within three days (including resumed older chats and recently archived files), plus any files it previously saw. A Codex task launched through Cursor is covered when that client writes a normal transcript to the same Codex home. Desktop tasks in any working directory are covered too. No Gecko daily report, job discovery, tracker, or resume script is invoked.

Run immediately:

```powershell
Start-ScheduledTask -TaskName 'Gecko Main Codex Usage Collector'
```

Reinstall the scheduled task after moving the project directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File usage/install_scheduled_task.ps1
```

The installer retains a matching existing task and refuses to overwrite an unrelated task with the same name. To inspect the schedule, use `Get-ScheduledTask -TaskName 'Gecko Main Codex Usage Collector'`. The task runs in the signed-in Windows account. A missed run catches up when it next executes, provided the source transcript still exists. The workbook export requires the bundled Codex spreadsheet library and Node.js; the collector itself needs only Python 3.9+ with `tzdata` available on Windows.

## What each field means

- Each turn in SQLite is keyed by **session ID + turn ID**. The workbook groups turns with the same session ID into one task row; repeated scans update it rather than append duplicates. Simultaneous sessions are separate. A turn stays `running` until a completion or interruption event appears; an abrupt process kill can leave that status stale. `completed` means Codex ended the turn, not that its work passed tests. A task's work duration is the sum of its turn durations, excluding idle time between turns.
- Token counts are deltas of Codex's cumulative `token_count.info.total_token_usage` counters within one transcript. They are observed tokens, including cached input; `cached input` is a subset of input and must not be added to `input + output`. A blank counter means the source did not provide one, while zero is an observed zero.
- `duration` is wall time from Codex's start and completion events, so waiting for a tool or user is included. A running task has no final duration.
- `source` in SQLite is the Codex transcript's client source. The workbook displays a `vscode` source as **Cursor/Codex**, matching this installation's IDE integration; the original source value remains in SQLite. Codex does not record a reliable custom Cursor terminal tab name, so **Terminal name is blank**. Likewise, the saved Git branch is the branch at session start and may differ if the branch changed during a long task.
- On **Turns**, column **J (Fast mode)** reads the most recent `thread_settings_applied.thread_settings.service_tier` event before that turn started. `fast` or `priority` displays **Yes**; `default` displays **No**. Missing or other tiers display **Unknown**. A current global setting is never applied retroactively to older turns.
- On **Tasks**, column **I (Usage Used %)** is an Excel formula: G minus H on the same row. Column **O (Fast Mode)** summarizes recorded settings across the turns in that task: **Yes** or **No** when they agree, **Mixed** when they differ, and **Unknown** when none is recorded. A **(partial)** suffix means one or more turns had no recorded setting, so the label describes only the known turns. The session ID remains in SQLite for deduplication but is omitted from the Tasks sheet.
- **Usage left before** is 100 minus the most recent Codex account-wide, seven-day `used_percent` reading within 30 minutes before the task started. **Usage left after** is 100 minus the last such reading observed while the task ran, and appears after completion or interruption. The Turns sheet shows the before sample time and reset time; SQLite retains both sample times. A blank before or after means no qualifying reading was available; it is never filled by guessing from token counts. These readings are account-wide, so concurrent Codex tasks can change the meter during this task. They are not a per-task cost or a precise attribution of the percentage change. Dollar cost remains unavailable.
- On **Turns**, column **S (Usage Used %)** is an Excel formula: Q minus R on the same row. It stays blank until both readings are present. A reset during the turn can make the subtraction negative; consult the reset time in column U before interpreting it. The account-wide reading can also reflect simultaneous tasks.

## Privacy and maintenance

The database and workbook remain in `usage/` under the current Gecko Main root and are ignored by Git. The database stores the first 160 characters of the task prompt as a brief description, with common `token=`, `api_key=`, `secret=`, and `password=` values masked. This is a convenience filter, not a guarantee that all sensitive prompt text is removed. To collect without descriptions, run `python usage/codex_usage.py --no-descriptions`; for existing rows, remove them manually from the private database if required. Raw prompts and tool output are never copied into the database or workbook. The temporary `codex_usage.snapshot.json` contains the same selected metadata and is also ignored by Git; it is rewritten on each refresh.

If Codex uses a different `CODEX_HOME`, run `python usage/codex_usage.py --sessions-root <other-home>\sessions` for that installation. The task scans only the default home. Sessions with another working directory, cloud-only sessions without local JSONL, or clients that do not emit Codex transcripts cannot be counted. The collector makes no claims about their usage. For historical backfill, use `python usage/codex_usage.py --days 30` and then run the wrapper to refresh the workbook.

Tests: `python -m unittest discover -s usage -p 'test_*.py'`.
