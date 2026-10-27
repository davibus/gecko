# Master-resume match filter

New discovery candidates must pass an evidence-backed fit review before storage,
and new tracker rows are checked again by the shared Google/SQLite writer. Existing
tracker rows, manual decisions, resumes and application history are preserved.

`job-scout/preferences/resume-match.json` controls admission. All three thresholds
must pass: overall at least 60/100 (`minimum_score`), responsibilities at least 50%
(`minimum_responsibilities_match`), and required skills at least 50%
(`minimum_required_skills_match`).
The factual source is the current `input/master-resume/master-resume-v4.docx`, read
directly with paragraphs and tables. The saved candidate summary is not a factual
substitute. The existing signed-in Codex JSON runner performs semantic comparison;
Python validates quotes and calculates the score, rather than trusting a model's
invented total. No API key or new service is required.

Weights: responsibilities 40, required qualifications 30, seniority/scope 15,
industry 10, explicitly preferred qualifications 5. Every extracted requirement
gets 1 for direct support, 0.5 for transferable/partial support, or 0 for no evidence.
Requirements are averaged within each category. Categories the posting does not
state are omitted and remaining weights normalized to 100. Both responsibilities
and required qualifications must be present and each score at least 50%. The
unrounded total must be at least 60. Comparisons use unrounded values; a displayed
rounded score cannot admit a job below a threshold. Display scores have two decimals.

Missing/unusable descriptions, unverified mandatory credentials, clearly different
occupations, invalid evidence, inference errors and unavailable master files do
not admit new jobs. Missing evidence is not a claim the candidate lacks a skill.
Pending reviews are retryable and are not cached as final decisions. An unchanged
successful review is reused; master bytes, job title/company/URL/description, model,
reasoning setting and scoring-policy version all participate in its cache identity.
Threshold changes reuse the same cached requirement/evidence assessment, then
recalculate acceptance and failed-rule explanations using the current three
thresholds. They do not require new inference or alter saved tracker rows.

Salary, location, role, fee, rejection, duplicate and availability guards remain
independent requirements. A high fit score does not override them and is not an
estimate of hiring probability. New tracker Notes include the score and explanation;
full requirement-to-master evidence stays in `job-scout/data/resume-match/`.

Manual unified search, daily discovery, Firecrawl and pending-publication retries
use the filter. Sync does not retroactively remove existing rows. Live pilot
inputs/results are retained in `reports/resume-match-pilot/`; pilot scoring does
not write jobs to the tracker or generate resumes.

When optional daily/dashboard AI evaluation is enabled, it reuses this same
validated review rather than generating an independent score or apply decision.

Offline focused regression checks: `python scripts/test_resume_match_filter.py`.
The harness isolates synthetic legacy discovery fixtures from live inference;
match-specific tests explicitly exercise enabled gates, evidence validation,
cache invalidation, publication retries and threshold boundaries.

Focused new-job rounds use `focused_discovery.run_round`: stable identities and
known postings are excluded before retrieval or reviews. Each independent worker
handles one complete employer posting and uses the canonical description and
evidence caches. At most three reviews run concurrently, further limited to the
remaining target slots. Tracker writes and independent readbacks run serially on
the calling thread. Only confirmed additions advance the target; pending work is
checkpointed, and a cooperative stop preserves completed evidence. Existing-job
maintenance is a separate, explicitly requested operation.
# Spreadsheet scores

The Job List has six named numeric columns: Match Score, Responsibilities Match,
Required Skills Match, Seniority Match, Industry Match, and Preferred Skills Match.
All use a 0–100 scale, with two decimal places. Match Score is the weighted overall
score; category scores use weights 40/30/15/10/5 respectively. Unstated categories
stay blank and the remaining weights are normalized. Unreviewed jobs stay blank.
New admitted jobs populate these fields automatically by live header name.
Existing rows are preserved; the initial backfill uses exact posting URLs from
validated pilot reviews. A score alone does not override core-category floors,
blocking requirements, location restrictions, or existing application decisions.

