# Cursor instruction and Google Sheets sync

`scripts/sync_cursor_instructions.py` copies the complete text of one Gecko Main
instruction file to or from one explicitly chosen Google Sheets cell. It does
not interpret the job tracker schema or edit job rows. The two commands are
`sheets-to-cursor` and `cursor-to-sheets`.

## Setup

1. From `gecko_main`, install `python -m pip install -r job-scout/requirements.txt`.
2. Keep the existing `GOOGLE_SHEETS_SPREADSHEET_ID` and
   `GOOGLE_SHEETS_CREDENTIALS_FILE` in `.env.local` or
   `.env.google-sheets.local`. The utility uses Gecko's existing service account
   loader; no credential is stored in the script.
3. Run `python scripts/sync_cursor_instructions.py list-tabs` to verify the
   tab's current title and numeric ID. On 2026-10-11, the user-authorized
   `Cursor Instructions` tab was created with ID `2074656464`; its A1 cell is
   mapped to `AGENTS.md`. The utility does not create tabs or write to the
   unowned `Scratch` tab. If the tab is removed or replaced, stop and verify a
   new mapping instead of reusing the old ID.

## Preview and apply

These are the verified Gecko Main commands for `AGENTS.md` and the dedicated
instruction cell:

```powershell
python scripts/sync_cursor_instructions.py cursor-to-sheets --file AGENTS.md --tab "Cursor Instructions" --sheet-id 2074656464 --cell A1
python scripts/sync_cursor_instructions.py sheets-to-cursor --file AGENTS.md --tab "Cursor Instructions" --sheet-id 2074656464 --cell A1
```

## Automatic sync

The Windows sign-in task `Gecko Cursor Instructions Sync` starts a hidden
watcher while you are signed in. It checks `AGENTS.md` and the dedicated Sheet
cell about once a minute. Cursor and the spreadsheet do not need to be open;
the computer must be running and connected to the network. A change to only
one side syncs automatically to the other with a backup and readback check.
If both sides have changed since the last successful sync, the watcher keeps
both versions and records a conflict for manual review.

Check its most recent result in
`scratch/cursor-sheet-sync/watch-status.json`; changes, conflicts, and errors
are also appended to `scratch/cursor-sheet-sync/watch-events.log`. A result of
`equal` means both sides match; `cursor-to-sheets` or `sheets-to-cursor` means
that direction was written and verified. After reviewing a conflict, use the
manual command for the chosen direction and the destination hash from its
preview. The watcher will resume normal operation from the new baseline.

To install or remove the sign-in task from Gecko Main:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_cursor_instructions_sync.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_cursor_instructions_sync.ps1 -Uninstall
```

The task runs independently of Cursor workspace opening, so it does not start
a Cursor terminal or project command when you open the workspace.

The default is a read-only preview. If the endpoints differ on the first run,
the preview prints the destination's SHA-256 value. After reviewing the
destination and direction, apply with the exact hash shown:

```powershell
python scripts/sync_cursor_instructions.py cursor-to-sheets --file AGENTS.md --tab "Cursor Instructions" --sheet-id 2074656464 --cell A1 --apply --expect-destination-sha256 HASH_FROM_PREVIEW
```

For later runs, `--apply` is sufficient when the destination still matches
the last synced baseline. If the destination has changed, the command stops
and requires its current hash. Run the desired direction's preview, review the
conflict, and use that hash only when you intend to replace that destination.
This makes concurrent or independently edited instructions visible before a
write. An empty source never clears the other side.

```powershell
python scripts/sync_cursor_instructions.py cursor-to-sheets --file AGENTS.md --tab "Cursor Instructions" --sheet-id 2074656464 --cell A1 --apply
python scripts/sync_cursor_instructions.py sheets-to-cursor --file AGENTS.md --tab "Cursor Instructions" --sheet-id 2074656464 --cell A1 --apply
```

The utility verifies the tab's title and ID, checks the target cell for a
formula or protected range, re-reads both endpoints before writing, and reads
back the result. It updates one cell with `RAW` values or atomically replaces
one local file. The Sheet keeps its formatting. Before a write, it saves both
original texts under ignored `scratch/cursor-sheet-sync/backups/`; the sync
baseline is also stored under the ignored `scratch/cursor-sheet-sync/`. Keep
that directory if you want future runs to detect changes since the last sync.
If a readback fails, inspect the backup and both endpoints before retrying.

The Google Sheets cell limit is 50,000 characters. Do not map tracker cells or
report output cells to this utility. If multiple instruction files need sync,
give each a separate, explicitly verified cell and run the command once per
file.
