"""SQLite persistence for Job Scout listings and lifecycle history."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from models import JobListing, VALID_STATUSES


DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "jobs.sqlite3"

JOB_COLUMNS = (
    "id", "company", "title", "location", "work_arrangement", "employment_type",
    "salary", "source", "source_job_id", "url", "canonical_url", "date_posted",
    "date_discovered", "last_seen", "description", "category", "tags_json", "status",
)
ENRICHMENT_COLUMNS = (
    "job_id", "original_description", "original_url", "enriched_description",
    "enriched_source_url", "enriched_at", "enrichment_status", "enrichment_error",
)
SOURCE_PRIORITY = {
    "greenhouse": 0, "lever": 0, "ashby": 0, "workable": 0, "web-careers": 0,
    "usajobs": 1, "jobicy": 1, "remotive": 1, "remoteok": 1,
    "weworkremotely": 1, "themuse": 1,
    "adzuna": 2,
    "indeed": 3, "linkedin": 3, "glassdoor": 3, "ziprecruiter": 3,
}


class JobStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._migrate()

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _create_schema(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY,
                company TEXT NOT NULL, title TEXT NOT NULL, location TEXT,
                work_arrangement TEXT, employment_type TEXT, salary TEXT,
                source TEXT, source_job_id TEXT, url TEXT, canonical_url TEXT,
                date_posted TEXT, date_discovered TEXT NOT NULL, last_seen TEXT NOT NULL,
                description TEXT, category TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'new',
                UNIQUE(source, source_job_id)
            );
            CREATE TABLE IF NOT EXISTS source_links (
                job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                source TEXT NOT NULL, source_job_id TEXT, url TEXT NOT NULL,
                UNIQUE(job_id, source, source_job_id, url)
            );
            CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status);
            CREATE TABLE IF NOT EXISTS enrichments (
                job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                original_description TEXT NOT NULL,
                original_url TEXT NOT NULL,
                enriched_description TEXT NOT NULL DEFAULT '',
                enriched_source_url TEXT NOT NULL DEFAULT '',
                enriched_at TEXT NOT NULL DEFAULT '',
                enrichment_status TEXT NOT NULL DEFAULT 'not_attempted',
                enrichment_error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS url_resolutions (
                job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                verification_status TEXT NOT NULL DEFAULT 'not_attempted',
                authoritative_url TEXT NOT NULL DEFAULT '',
                authoritative_url_confidence INTEGER NOT NULL DEFAULT 0,
                destination_type TEXT NOT NULL DEFAULT 'unknown',
                redirect_url TEXT NOT NULL DEFAULT '',
                resolved_at TEXT NOT NULL DEFAULT '',
                resolution_error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS scout_state (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_evaluation_cache (
                description_hash TEXT NOT NULL,
                profile_hash TEXT NOT NULL,
                triage_model TEXT NOT NULL,
                scoring_model TEXT NOT NULL,
                relevance TEXT NOT NULL,
                triage_reason TEXT NOT NULL DEFAULT '',
                match_score INTEGER,
                apply_decision TEXT NOT NULL DEFAULT 'No',
                score_reason TEXT NOT NULL DEFAULT '',
                evaluated_at TEXT NOT NULL,
                PRIMARY KEY (description_hash, profile_hash, triage_model, scoring_model)
            );
            CREATE TABLE IF NOT EXISTS job_evaluations (
                job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                description_hash TEXT NOT NULL,
                profile_hash TEXT NOT NULL,
                triage_model TEXT NOT NULL,
                scoring_model TEXT NOT NULL,
                relevance TEXT NOT NULL,
                triage_reason TEXT NOT NULL DEFAULT '',
                match_score INTEGER,
                apply_decision TEXT NOT NULL DEFAULT 'No',
                score_reason TEXT NOT NULL DEFAULT '',
                evaluated_at TEXT NOT NULL
            );
        """)

    def _columns(self, table: str) -> set[str]:
        return {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}

    def _rebuild_canonical_table(self, table: str, columns: tuple[str, ...]) -> None:
        existing = self._columns(table)
        if existing <= set(columns):
            return
        temporary = f"{table}_canonical"
        self.connection.execute(f"DROP TABLE IF EXISTS {temporary}")
        if table == "jobs":
            self.connection.execute("""
                CREATE TABLE jobs_canonical (
                    id INTEGER PRIMARY KEY,
                    company TEXT NOT NULL, title TEXT NOT NULL, location TEXT,
                    work_arrangement TEXT, employment_type TEXT, salary TEXT,
                    source TEXT, source_job_id TEXT, url TEXT, canonical_url TEXT,
                    date_posted TEXT, date_discovered TEXT NOT NULL, last_seen TEXT NOT NULL,
                    description TEXT, category TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'new',
                    UNIQUE(source, source_job_id)
                )
            """)
        else:
            self.connection.execute("""
                CREATE TABLE enrichments_canonical (
                    job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                    original_description TEXT NOT NULL,
                    original_url TEXT NOT NULL,
                    enriched_description TEXT NOT NULL DEFAULT '',
                    enriched_source_url TEXT NOT NULL DEFAULT '',
                    enriched_at TEXT NOT NULL DEFAULT '',
                    enrichment_status TEXT NOT NULL DEFAULT 'not_attempted',
                    enrichment_error TEXT NOT NULL DEFAULT ''
                )
            """)
        shared = [name for name in columns if name in existing]
        names = ",".join(shared)
        self.connection.execute(
            f"INSERT INTO {temporary} ({names}) SELECT {names} FROM {table}"
        )
        self.connection.execute(f"DROP TABLE {table}")
        self.connection.execute(f"ALTER TABLE {temporary} RENAME TO {table}")

    def _migrate(self):
        self.connection.execute("PRAGMA foreign_keys=OFF")
        self._create_schema()
        columns = self._columns("jobs")
        if "last_seen" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN last_seen TEXT NOT NULL DEFAULT ''")
            self.connection.execute("UPDATE jobs SET last_seen = date_discovered WHERE last_seen = ''")
        if "category" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN category TEXT NOT NULL DEFAULT ''")
        if "tags_json" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")
        self._rebuild_canonical_table("jobs", JOB_COLUMNS)
        self._rebuild_canonical_table("enrichments", ENRICHMENT_COLUMNS)
        self._create_schema()
        highest = self.connection.execute("SELECT COALESCE(MAX(id), 0) FROM jobs").fetchone()[0]
        self.connection.execute("""
            INSERT INTO scout_state (key, value) VALUES ('id_high_water', ?)
            ON CONFLICT(key) DO UPDATE SET value=MAX(value, excluded.value)
        """, (int(highest),))
        self.connection.commit()
        self.connection.execute("PRAGMA foreign_keys=ON")

    @staticmethod
    def _from_row(row, links=()) -> JobListing:
        return JobListing(
            id=row["id"], company=row["company"], title=row["title"],
            location=row["location"] or "", work_arrangement=row["work_arrangement"] or "unknown",
            employment_type=row["employment_type"] or "", salary=row["salary"] or "",
            source=row["source"] or "", source_job_id=row["source_job_id"] or "",
            url=row["url"] or "", canonical_url=row["canonical_url"] or "",
            date_posted=row["date_posted"] or "", date_discovered=row["date_discovered"],
            last_seen=row["last_seen"] or row["date_discovered"],
            description=row["description"] or "", category=row["category"] or "",
            tags=json.loads(row["tags_json"] or "[]"), status=row["status"],
            source_links=list(links),
        )

    def all(self, *, retained_only: bool = False) -> list[JobListing]:
        # retained_only is accepted for old callers; discovery no longer gates records.
        rows = self.connection.execute("SELECT id FROM jobs").fetchall()
        return [self.get(row["id"]) for row in rows]

    def get(self, job_id: int) -> JobListing | None:
        row = self.connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        links = [dict(link) for link in self.connection.execute(
            "SELECT source, source_job_id, url FROM source_links WHERE job_id = ?", (job_id,)
        ).fetchall()]
        job = self._from_row(row, links)
        enrichment = self.connection.execute(
            "SELECT * FROM enrichments WHERE job_id = ?", (job_id,)
        ).fetchone()
        if enrichment:
            for name in ENRICHMENT_COLUMNS[1:]:
                setattr(job, name, enrichment[name])
        resolution = self.connection.execute(
            "SELECT * FROM url_resolutions WHERE job_id = ?", (job_id,)
        ).fetchone()
        if resolution:
            mapping = {
                "verification_status": "url_verification_status",
                "authoritative_url": "authoritative_url",
                "authoritative_url_confidence": "authoritative_url_confidence",
                "destination_type": "url_destination_type", "redirect_url": "url_redirect_url",
                "resolved_at": "url_resolved_at", "resolution_error": "url_resolution_error",
            }
            for column, attribute in mapping.items():
                setattr(job, attribute, resolution[column])
        return job

    def highest_scout_id(self) -> int:
        row = self.connection.execute(
            "SELECT value FROM scout_state WHERE key = 'id_high_water'"
        ).fetchone()
        return int(row[0]) if row else 0

    def observe_scout_id(self, scout_id: int) -> None:
        """Advance the persistent ID high-water mark without creating a record."""
        if scout_id < 0:
            raise ValueError("Scout ID high-water mark cannot be negative")
        self.connection.execute("""
            INSERT INTO scout_state (key, value) VALUES ('id_high_water', ?)
            ON CONFLICT(key) DO UPDATE SET value=MAX(value, excluded.value)
        """, (scout_id,))
        self.connection.commit()

    def save(self, job: JobListing, retained: bool = True, *, job_id: int | None = None) -> int:
        existing = self.connection.execute(
            "SELECT id FROM jobs WHERE source = ? AND source_job_id = ?",
            (job.source, job.source_job_id),
        ).fetchone()
        if job_id is None and existing is None:
            job_id = self.highest_scout_id() + 1
        if job_id is not None:
            if job_id < 1:
                raise ValueError("Scout ID must be a positive integer")
            if self.get(job_id):
                raise ValueError(f"Scout ID {job_id} already exists")
            cursor = self.connection.execute("""
                INSERT INTO jobs (id,company,title,location,work_arrangement,employment_type,salary,
                    source,source_job_id,url,canonical_url,date_posted,date_discovered,last_seen,
                    description,category,tags_json,status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                RETURNING id
            """, (
                job_id, job.company, job.title, job.location, job.work_arrangement,
                job.employment_type, job.salary, job.source, job.source_job_id, job.url,
                job.canonical_url, job.date_posted, job.date_discovered,
                job.last_seen or job.date_discovered, job.description, job.category,
                json.dumps(job.tags), job.status,
            ))
            saved_id = int(cursor.fetchone()[0])
            for link in job.source_links:
                self.add_source_link(saved_id, link["source"], link.get("source_job_id", ""), link["url"])
            self.connection.execute(
                "UPDATE scout_state SET value=MAX(value, ?) WHERE key='id_high_water'",
                (saved_id,),
            )
            self.connection.commit()
            return saved_id
        cursor = self.connection.execute("""
            INSERT INTO jobs (company,title,location,work_arrangement,employment_type,salary,source,
                source_job_id,url,canonical_url,date_posted,date_discovered,last_seen,description,
                category,tags_json,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source, source_job_id) DO UPDATE SET
                company=excluded.company,title=excluded.title,location=excluded.location,
                work_arrangement=excluded.work_arrangement,employment_type=excluded.employment_type,
                salary=excluded.salary,url=excluded.url,canonical_url=excluded.canonical_url,
                date_posted=excluded.date_posted,last_seen=excluded.last_seen,
                description=CASE WHEN length(excluded.description) > length(description)
                    THEN excluded.description ELSE description END,
                category=excluded.category,tags_json=excluded.tags_json
            RETURNING id
        """, (
            job.company, job.title, job.location, job.work_arrangement, job.employment_type,
            job.salary, job.source, job.source_job_id, job.url, job.canonical_url,
            job.date_posted, job.date_discovered, job.last_seen or job.date_discovered,
            job.description, job.category, json.dumps(job.tags), job.status,
        ))
        job_id = int(cursor.fetchone()[0])
        for link in job.source_links:
            self.add_source_link(job_id, link["source"], link.get("source_job_id", ""), link["url"])
        self.connection.commit()
        return job_id

    def add_source_link(self, job_id: int, source: str, source_job_id: str, url: str):
        self.connection.execute(
            "INSERT OR IGNORE INTO source_links (job_id,source,source_job_id,url) VALUES (?,?,?,?)",
            (job_id, source, source_job_id, url),
        )

    def update_description(self, job_id: int, description: str, last_seen: str) -> None:
        """Persist a changed posting body without disturbing lifecycle/manual state."""
        self.connection.execute(
            "UPDATE jobs SET description=?, last_seen=? WHERE id=?",
            (description, last_seen, job_id),
        )
        self.connection.commit()

    def update_status(self, job_id: int, status: str):
        if status not in VALID_STATUSES:
            raise ValueError(f"Unknown status {status!r}; choose from {', '.join(sorted(VALID_STATUSES))}")
        if not self.get(job_id):
            raise ValueError(f"Job {job_id} does not exist")
        self.connection.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        self.connection.commit()

    def delete_dead_unprotected(self, job_id: int) -> None:
        job = self.get(job_id)
        if not job:
            return
        if job.status not in {"new", "reviewing"}:
            raise ValueError(f"Cannot delete historical job {job_id} with status {job.status}")
        with self.connection:
            for table in ("source_links", "enrichments", "url_resolutions", "job_evaluations"):
                self.connection.execute(f"DELETE FROM {table} WHERE job_id = ?", (job_id,))
            self.connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    @staticmethod
    def _evaluation_dict(row) -> dict | None:
        if not row:
            return None
        return {key: row[key] for key in (
            "description_hash", "profile_hash", "triage_model", "scoring_model",
            "relevance", "triage_reason", "match_score", "apply_decision",
            "score_reason", "evaluated_at",
        )}

    def find_cached_evaluation(self, description_hash: str, profile_hash: str,
                               triage_model: str, scoring_model: str) -> dict | None:
        row = self.connection.execute("""
            SELECT * FROM ai_evaluation_cache
            WHERE description_hash=? AND profile_hash=? AND triage_model=? AND scoring_model=?
        """, (description_hash, profile_hash, triage_model, scoring_model)).fetchone()
        return self._evaluation_dict(row)

    def cache_evaluation(self, evaluation: dict) -> None:
        columns = (
            "description_hash", "profile_hash", "triage_model", "scoring_model",
            "relevance", "triage_reason", "match_score", "apply_decision",
            "score_reason", "evaluated_at",
        )
        values = tuple(evaluation.get(column) for column in columns)
        self.connection.execute(f"""
            INSERT INTO ai_evaluation_cache ({','.join(columns)})
            VALUES ({','.join('?' for _ in columns)})
            ON CONFLICT(description_hash,profile_hash,triage_model,scoring_model) DO UPDATE SET
                relevance=excluded.relevance,triage_reason=excluded.triage_reason,
                match_score=excluded.match_score,apply_decision=excluded.apply_decision,
                score_reason=excluded.score_reason,evaluated_at=excluded.evaluated_at
        """, values)
        self.connection.commit()

    def save_job_evaluation(self, job_id: int, evaluation: dict) -> None:
        columns = (
            "description_hash", "profile_hash", "triage_model", "scoring_model",
            "relevance", "triage_reason", "match_score", "apply_decision",
            "score_reason", "evaluated_at",
        )
        values = (job_id, *(evaluation.get(column) for column in columns))
        self.connection.execute(f"""
            INSERT INTO job_evaluations (job_id,{','.join(columns)})
            VALUES ({','.join('?' for _ in range(len(columns) + 1))})
            ON CONFLICT(job_id) DO UPDATE SET
                description_hash=excluded.description_hash,profile_hash=excluded.profile_hash,
                triage_model=excluded.triage_model,scoring_model=excluded.scoring_model,
                relevance=excluded.relevance,triage_reason=excluded.triage_reason,
                match_score=excluded.match_score,apply_decision=excluded.apply_decision,
                score_reason=excluded.score_reason,evaluated_at=excluded.evaluated_at
        """, values)
        self.connection.commit()

    def get_job_evaluation(self, job_id: int) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM job_evaluations WHERE job_id=?", (job_id,)
        ).fetchone()
        return self._evaluation_dict(row)

    def merge(self, canonical_id: int, duplicate: JobListing, retained: bool = True):
        current = self.get(canonical_id)
        merged_tags = list(dict.fromkeys([
            *((current.tags if current else []) or []), *(duplicate.tags or []),
        ]))
        self.connection.execute("""
            UPDATE jobs SET last_seen=?, salary=CASE WHEN ? != '' THEN ? ELSE salary END,
                url=CASE WHEN url = '' AND ? != '' THEN ? ELSE url END,
                canonical_url=CASE WHEN canonical_url = '' AND ? != '' THEN ? ELSE canonical_url END,
                description=CASE WHEN length(?) > length(description) THEN ? ELSE description END,
                category=CASE WHEN ? != '' THEN ? ELSE category END, tags_json=?
            WHERE id=?
        """, (
            duplicate.last_seen or duplicate.date_discovered, duplicate.salary, duplicate.salary,
            duplicate.url, duplicate.url, duplicate.canonical_url, duplicate.canonical_url,
            duplicate.description, duplicate.description, duplicate.category, duplicate.category,
            json.dumps(merged_tags), canonical_id,
        ))
        current_priority = SOURCE_PRIORITY.get((current.source if current else "").casefold(), 2)
        incoming_priority = SOURCE_PRIORITY.get(duplicate.source.casefold(), 2)
        if current and incoming_priority < current_priority:
            self.connection.execute("""
                UPDATE jobs SET source=?, source_job_id=?, url=?, canonical_url=?,
                    company=?, title=?, location=?, work_arrangement=?, employment_type=?,
                    date_posted=CASE WHEN ? != '' THEN ? ELSE date_posted END
                WHERE id=?
            """, (
                duplicate.source, duplicate.source_job_id, duplicate.url,
                duplicate.canonical_url, duplicate.company, duplicate.title,
                duplicate.location, duplicate.work_arrangement, duplicate.employment_type,
                duplicate.date_posted, duplicate.date_posted, canonical_id,
            ))
        for link in duplicate.source_links:
            self.add_source_link(canonical_id, link["source"], link.get("source_job_id", ""), link["url"])
        self.connection.commit()

    def save_url_resolution(self, job: JobListing):
        if job.id is None:
            raise ValueError("Cannot save URL resolution for an unsaved job")
        self.connection.execute("""
            INSERT INTO url_resolutions (
                job_id,verification_status,authoritative_url,authoritative_url_confidence,
                destination_type,redirect_url,resolved_at,resolution_error
            ) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                verification_status=excluded.verification_status,
                authoritative_url=excluded.authoritative_url,
                authoritative_url_confidence=excluded.authoritative_url_confidence,
                destination_type=excluded.destination_type,redirect_url=excluded.redirect_url,
                resolved_at=excluded.resolved_at,resolution_error=excluded.resolution_error
        """, (
            job.id, job.url_verification_status, job.authoritative_url,
            job.authoritative_url_confidence, job.url_destination_type,
            job.url_redirect_url, job.url_resolved_at, job.url_resolution_error,
        ))
        self.connection.commit()

    def save_enrichment(self, job: JobListing):
        if job.id is None:
            raise ValueError("Cannot save enrichment for an unsaved job")
        self.connection.execute("""
            INSERT INTO enrichments (
                job_id,original_description,original_url,enriched_description,
                enriched_source_url,enriched_at,enrichment_status,enrichment_error
            ) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                enriched_source_url=CASE
                    WHEN length(excluded.enriched_description) > length(enriched_description)
                    THEN excluded.enriched_source_url ELSE enriched_source_url END,
                enriched_description=CASE
                    WHEN length(excluded.enriched_description) > length(enriched_description)
                    THEN excluded.enriched_description ELSE enriched_description END,
                enriched_at=excluded.enriched_at,
                enrichment_status=excluded.enrichment_status,
                enrichment_error=excluded.enrichment_error
        """, (
            job.id, job.original_description, job.original_url, job.enriched_description,
            job.enriched_source_url, job.enriched_at, job.enrichment_status,
            job.enrichment_error,
        ))
        self.connection.commit()
