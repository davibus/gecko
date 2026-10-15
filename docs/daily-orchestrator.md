# Gecko daily orchestrator

From the Gecko Main directory, run:

```powershell
python scripts/gecko_daily.py --dry-run
python scripts/gecko_daily.py --apply
```

For a full daily run that limits **resume generation** to specified live
Column A IDs, use `python scripts/gecko_daily.py --apply --resume-ids 2218 2219`.
Discovery, tracker sync, Gmail, and Daily Run reporting still run. The ID
limit is verified before those steps begin. Completed IDs remain skipped.

The default without a flag is `--dry-run`. `--apply` first verifies the live
workbook title, the configured `Job List` and `Rejected Jobs` headers, the
canonical resume queue, the source resume files, and the existing `Daily Run`
history layout. If `Daily Run` is missing or unsafe to write, it stops before
discovery or any job, resume, or Gmail changes. It never creates tabs.

After preflight, the command runs the existing `job-scout/scout.py daily`
workflow. That workflow searches configured sources, including automated
Indeed discovery, handles manual Indeed intake, syncs the tracker, runs the
canonical all-source resume queue, and checks Gmail for employer replies.
During the daily run, declined rows are retained and skipped by Indeed intake;
Gecko does not move formula-bearing ledger rows to clean them up.
It consults rejection history, avoids duplicates, and preserves completed
`Resume Created = X` rows and their links. Only approved and geographically
eligible jobs enter resume generation. It does not submit applications.

The orchestrator records the final labeled workflow counts in the existing
`Daily Run` tab, with new jobs, duplicates, resumes created and reused, Gmail
responses, errors, and attention items. Each execution has a unique Run ID.
It also saves a JSON audit and captured command log under
`reports/daily/YYYY-MM-DD/`. A failed workflow is recorded as failed when the
history tab remains available. If the history write itself fails, the local
audit records the failure and the command exits nonzero.

The dry run invokes the existing daily preview, which can perform provider
requests, read the live Sheet, and write local logs or temporary SQLite state;
it does not update Sheet cells or generate resumes. Gmail is skipped in the
preview, so its counts are shown as `Unavailable`.

Run `python scripts/archive_applied_resumes.py --apply` separately after
application decisions. Gecko never submits an application from this command.

## Test only selected resume IDs

To generate resumes only for named live Column A IDs, use the canonical queue
directly. For example:

```powershell
python scripts/generate_apply_queue.py --dry-run --ids 2218 2219
python scripts/generate_apply_queue.py --ids 2218 2219
```

The queue verifies that each requested ID appears exactly once under the live
Column A `ID` header, then classifies and processes only those rows. It skips
unrelated rejection maintenance and does not run discovery, Gmail, or the
Daily Run report. Completed, rejected, excluded, or ineligible target rows
remain skipped under the queue's normal safeguards.
