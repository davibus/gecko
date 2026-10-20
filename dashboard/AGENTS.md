# Dashboard instructions

Follow the root AGENTS.md and docs/sqlite-workspace.md. Read
docs/agent-guides/tracker.md for changes to tracker data or job actions.
Do not load resume/application guides for unrelated dashboard work.

## Dashboard column filters

Always include a working filter button when adding a dashboard table column. Match the existing column filter controls, support blank values, and include active-filter and clear/reset behavior.

## Default job order

Default job tables to Date Found ascending (oldest first). Keep unknown dates last. User-selected sorting may override this during the current session.

## Missing job descriptions

Jobs blocked from automatic resume creation because their exact description is missing or unusable must display **No job description**. Do not label these Ready to apply or attempt generic resume generation. Follow the missing-description rule in docs/agent-guides/resumes.md.
