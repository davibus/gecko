# Gecko Job Scout Prompt

Run Gecko Job Scout and show me the strong new matches.

Instructions:
- Read `GECKO_SYSTEM.md`, `AGENTS.md`, and `job-scout/README.md` first.
- Use Adzuna only; do not require or query Brave and do not scrape job boards.
- Run `python job-scout/scout.py search --source adzuna` from the project root.
- Then run `python job-scout/scout.py list --status new`.
- Summarize only jobs scoring 80 or higher, including score, company, title, location/work arrangement, salary when present, strongest alignment, material gaps, and URL.
- Do not select a job, create a resume, or add a tracker row until I explicitly choose one.
- After I choose, run `python job-scout/scout.py select <ID>` and pass the archived description into the existing Gecko workflow.
