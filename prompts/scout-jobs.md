# Gecko Job Scout Prompt

Run Gecko Job Scout and show me the relevant new jobs.

Instructions:
- Read `GECKO_SYSTEM.md`, `AGENTS.md`, and `job-scout/README.md` first.
- Run the requested discovery live and verify its actual tracker writes; do not substitute a dry run unless I explicitly request read-only behavior.
- Search all configured core sources using the current source policy.
- Run `python job-scout/scout.py search --source core` from the project root.
- Then run `python job-scout/scout.py list --status new`.
- Summarize the newly discovered role-relevant jobs, including company, title, location/work arrangement, salary when present, strongest alignment, material gaps, and URL.
- Search synchronizes new jobs to the tracker. Do not select a job or create a resume until I explicitly choose one.
- After I choose, run `python job-scout/scout.py select <ID>` and pass the archived description into the existing Gecko workflow.
