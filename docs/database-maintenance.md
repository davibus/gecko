# Database recovery and maintenance

Current policy, October 27, 2026. This supersedes per-run full backups and full
row change-history instructions. The Google Sheet remains the primary tracker;
SQLite is its working cache and the store for discovery and local evidence.

The existing runner's `sync_gecko_local.py` step calls
`database_maintenance.backup_database`. It uses SQLite's backup API, compresses
the snapshot under `C:\gecko-backups`, then restores into a separate temporary
database. SHA-256, integrity checks, every table's count and content hashes must
match. The live database is never a restore-test target. Sync baseline and
resume-delivery configuration/registry accompany live recovery points, with
checksums. These private files stay outside Git.

Make at most one ordinary recovery point per America/Denver day, when substantive
data or saved sync/delivery state has changed since the previous point. Later
same-day edits are captured on the next requested daily backup; this is not
continuous recovery. Log and report timestamp churn alone does not trigger a
new daily point. Keep the newest seven available daily dates and newest four
available ISO weeks, using one compressed file for overlapping selections.
There is no new clock schedule: backups use the existing requested runner.

Before a significant migration or destructive maintenance, run:

```powershell
.tools/dashboard-python/Scripts/python.exe scripts/maintain_database.py pre-maintenance
```

Keep two additional pre-maintenance points. Identical snapshots and state reuse
an existing verified point. A byte-range OS lock prevents overlapping backup
workers. Rotation first restores every retained point and commits its catalog;
failure must preserve the last verified point. Orphan partial files are not
recovery points and are never grounds to delete a verified recovery.

`workspace_events` is a bounded operational log, not a job ledger. Routine sync,
updates, manual edits/intake and column changes retain at most 1,000 metadata
events in the same transaction as the record write. Never store descriptions or
application answers in those events. Manual attachment conflict recovery uses
old-version and field hashes; expired recovery metadata fails closed and keeps
the uploaded file. Completion and durable exceptional evidence are preserved.
Notes/Previous Notes, current/archived job rows, rejection history, identities,
application evidence, resumes, delivery/review receipts, and sync baselines are
not disposable history. Conflict detection, formulas, live header resolution,
frozen headers, transaction rollback and completion protection remain mandatory.

Explicit cleanup commands are `cleanup-history` and `cleanup-backups` on the same
script. History cleanup verifies a gzip JSONL archive before deleting only the
listed disposable event actions. It holds the existing Gecko run lock and a
SQLite exclusive connection through deletion and VACUUM. Only use an idle window
with no other Gecko writer. All non-event tables must match before and after.
An existing archive causes a stop for review, not an overwrite.

Backup cleanup is restricted to timestamp-named SQLite files directly under
`reports/sqlite-backups`. Inventory and hash every file, retain policy-selected
days/weeks as verified compressed points, then delete exact unchanged originals.
External inventory, deletion log and receipts record paths, hashes and bytes.
Never treat discovery data, migration candidates, the live database/sidecars,
credentials, resumes, or application artifacts as disposable backup files.

Runtime databases, backup copies and maintenance temporary files are ignored by
Git. Previously committed copies also require index/history cleanup. Rewrite
only verified unpublished commits, retain a recovery reference, compare all
other tree entries, and preserve worktree/index work. Never force-push or rewrite
published history. Old published blobs and the recovery branch/bundle may retain
large objects; do not delete those automatically merely to shrink `.git`.

## Retained report artifacts and Git storage

The October 27 follow-up audit is under
`C:\gecko-backups\followup-20261027T1520`. Its receipts are separate from the
original maintenance receipts; never overwrite earlier inventories or results.
Historical report databases and employer feed snapshots may be compressed there
only after their consumers and purpose are reviewed. Verify archive SHA-256,
restore into a separate file, compare the exact original byte hash and length,
and check restored SQLite integrity before deleting a redundant original copy.
The original migration `before.sqlite3` / `candidate.sqlite3` pair remains intact
because historical activation consumes those paths directly.

`job-scout/preferences/retained-artifacts.json` is the small source-controlled
manifest. `retained_artifacts.read_json` and `artifact_path` verify and read the
external evidence. `work/extend_gecko_coverage.py` uses this reader for saved
feeds. A registered but missing/corrupt archive fails closed; it must never be
treated as permission to fetch the same feed again or spend credits. Set
`GECKO_ARCHIVE_ROOT` if the verified archive root moves. Explicit recovery:

```powershell
.tools/dashboard-python/Scripts/python.exe scripts/restore_retained_artifact.py reports/discovery/recovery-20261025/source-greenhouse.json --output C:\gecko-backups\restored-greenhouse.json
```

Restoration refuses an existing destination and the CLI refuses targets inside
the checkout. `archive_retained_artifacts.py` accepts an exact, reviewed external
plan, restricts deletion to historical reports, and writes pre-deletion receipts
and the reader manifest. It does not prune live stores, candidate state, credit
ledgers, identity registries, applications, credentials or resumes.

Before Git object reclamation, archive the full Git directory, its references,
and current working edits outside the repository. Verify entry hashes and restore
the Git directory separately; `git fsck --full` and reference comparison must
pass. A stored ZIP avoids expensive delta recompression of enormous database
blobs already compressed inside Git. Retain `backup/pre-database-maintenance-20261027`
until this recovery proof exists. Published refs and unrelated branches remain
unchanged. Rebuild only unpublished commits, compare all other tree entries,
and never force-push.

Object reclamation requires no active Git processes and a verified archived copy
of every unreachable object selected for pruning. Expire archived reflogs only
after that proof; use ordinary non-aggressive repacking and an explicit prune
cutoff. Inspect failed-bundle/temp-object leftovers individually. Never delete
unknown lock files or invoke `reset --hard`, `git clean`, or aggressive GC.

`.githooks/pre-commit` runs `scripts/check_git_artifacts.py` with Gecko's native
Python. This repository uses local `core.hooksPath=.githooks`; preserve any
existing hooks before changing that setting elsewhere. The guard rejects runtime
databases, retained feed snapshots and staged blobs larger than GitHub's 100 MiB
limit. Before a push, inspect every blob in `origin/main..HEAD` and verify that
the current remote branch is an ancestor. No maintenance command pushes.

The large discovery database remains protected: its pending candidates, response
caches, reservations, unknown billing states, aliases and identities prevent
repeat spending and duplicate admission. Large installers, browser profiles,
report dependencies and application/resume artifacts need separate semantic
review; folder size alone never authorizes their deletion.
