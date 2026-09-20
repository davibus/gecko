"""SQLite persistence for listings, source links, statuses, and seen history."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from models import JobListing, VALID_STATUSES


DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "jobs.sqlite3"


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

    def _migrate(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY,
                company TEXT NOT NULL, title TEXT NOT NULL, location TEXT,
                work_arrangement TEXT, employment_type TEXT, salary TEXT,
                source TEXT, source_job_id TEXT, url TEXT, canonical_url TEXT,
                date_posted TEXT, date_discovered TEXT NOT NULL, last_seen TEXT NOT NULL,
                description TEXT, category TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]',
                match_score INTEGER NOT NULL, strengths_json TEXT NOT NULL,
                weaknesses_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
                evidence_confidence INTEGER NOT NULL DEFAULT 0,
                provisional INTEGER NOT NULL DEFAULT 0,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                retained INTEGER NOT NULL DEFAULT 1,
                UNIQUE(source, source_job_id)
            );
            CREATE TABLE IF NOT EXISTS source_links (
                job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                source TEXT NOT NULL, source_job_id TEXT, url TEXT NOT NULL,
                UNIQUE(job_id, source, source_job_id, url)
            );
            CREATE INDEX IF NOT EXISTS jobs_score_idx ON jobs(match_score DESC);
            CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status);
            CREATE TABLE IF NOT EXISTS enrichments (
                job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                original_description TEXT NOT NULL,
                original_match_score INTEGER NOT NULL,
                original_evidence_confidence INTEGER NOT NULL,
                original_url TEXT NOT NULL,
                enriched_description TEXT NOT NULL DEFAULT '',
                enriched_source_url TEXT NOT NULL DEFAULT '',
                enriched_at TEXT NOT NULL DEFAULT '',
                enrichment_status TEXT NOT NULL DEFAULT 'not_attempted',
                enrichment_error TEXT NOT NULL DEFAULT '',
                enriched_match_score INTEGER NOT NULL DEFAULT 0,
                enriched_evidence_confidence INTEGER NOT NULL DEFAULT 0
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
        """)
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(jobs)")}
        if "evidence_confidence" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN evidence_confidence INTEGER NOT NULL DEFAULT 0")
        if "provisional" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN provisional INTEGER NOT NULL DEFAULT 0")
        if "evidence_json" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '{}'")
        if "last_seen" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN last_seen TEXT NOT NULL DEFAULT ''")
            self.connection.execute("UPDATE jobs SET last_seen = date_discovered WHERE last_seen = ''")
        if "category" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN category TEXT NOT NULL DEFAULT ''")
        if "tags_json" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")
        self.connection.commit()

    @staticmethod
    def _from_row(row, links=()) -> JobListing:
        return JobListing(
            id=row["id"], company=row["company"], title=row["title"], location=row["location"] or "",
            work_arrangement=row["work_arrangement"] or "unknown", employment_type=row["employment_type"] or "",
            salary=row["salary"] or "", source=row["source"] or "", source_job_id=row["source_job_id"] or "",
            url=row["url"] or "", canonical_url=row["canonical_url"] or "", date_posted=row["date_posted"] or "",
            date_discovered=row["date_discovered"], last_seen=row["last_seen"] or row["date_discovered"],
            description=row["description"] or "", category=row["category"] or "",
            tags=json.loads(row["tags_json"] or "[]"),
            match_score=row["match_score"], match_strengths=json.loads(row["strengths_json"]),
            evidence_confidence=row["evidence_confidence"], provisional=bool(row["provisional"]),
            evidence_levels=json.loads(row["evidence_json"]),
            match_weaknesses=json.loads(row["weaknesses_json"]), status=row["status"], source_links=list(links),
        )

    def all(self, *, retained_only: bool = False) -> list[JobListing]:
        where = " WHERE retained = 1" if retained_only else ""
        rows = self.connection.execute("SELECT * FROM jobs" + where).fetchall()
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
            for name in (
                "original_description", "original_match_score", "original_evidence_confidence",
                "original_url", "enriched_description", "enriched_source_url", "enriched_at",
                "enrichment_status", "enrichment_error", "enriched_match_score",
                "enriched_evidence_confidence",
            ):
                setattr(job, name, enrichment[name])
        resolution = self.connection.execute(
            "SELECT * FROM url_resolutions WHERE job_id = ?", (job_id,)
        ).fetchone()
        if resolution:
            mapping = {
                "verification_status": "url_verification_status",
                "authoritative_url": "authoritative_url",
                "authoritative_url_confidence": "authoritative_url_confidence",
                "destination_type": "url_destination_type",
                "redirect_url": "url_redirect_url",
                "resolved_at": "url_resolved_at",
                "resolution_error": "url_resolution_error",
            }
            for column, attribute in mapping.items():
                setattr(job, attribute, resolution[column])
        return job

    def save(self, job: JobListing, retained: bool = True) -> int:
        cursor = self.connection.execute("""
            INSERT INTO jobs (company,title,location,work_arrangement,employment_type,salary,source,
                source_job_id,url,canonical_url,date_posted,date_discovered,last_seen,description,
                category,tags_json,match_score,strengths_json,weaknesses_json,status,evidence_confidence,provisional,
                evidence_json,retained)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source, source_job_id) DO UPDATE SET
                company=excluded.company,title=excluded.title,location=excluded.location,
                work_arrangement=excluded.work_arrangement,employment_type=excluded.employment_type,
                salary=excluded.salary,url=excluded.url,canonical_url=excluded.canonical_url,
                date_posted=excluded.date_posted,last_seen=excluded.last_seen,description=excluded.description,
                category=excluded.category,tags_json=excluded.tags_json,
                match_score=excluded.match_score,strengths_json=excluded.strengths_json,
                weaknesses_json=excluded.weaknesses_json,
                evidence_confidence=excluded.evidence_confidence,provisional=excluded.provisional,
                evidence_json=excluded.evidence_json,retained=excluded.retained
            RETURNING id
        """, (
            job.company, job.title, job.location, job.work_arrangement, job.employment_type, job.salary,
            job.source, job.source_job_id, job.url, job.canonical_url, job.date_posted,
            job.date_discovered, job.last_seen or job.date_discovered, job.description,
            job.category, json.dumps(job.tags), job.match_score, json.dumps(job.match_strengths),
            json.dumps(job.match_weaknesses), job.status, job.evidence_confidence,
            int(job.provisional), json.dumps(job.evidence_levels), int(retained),
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

    def update_status(self, job_id: int, status: str):
        if status not in VALID_STATUSES:
            raise ValueError(f"Unknown status {status!r}; choose from {', '.join(sorted(VALID_STATUSES))}")
        if not self.get(job_id):
            raise ValueError(f"Job {job_id} does not exist")
        self.connection.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        self.connection.commit()

    def merge(self, canonical_id: int, duplicate: JobListing, retained: bool = False):
        current = self.get(canonical_id)
        self.connection.execute("""
            UPDATE jobs SET last_seen=?, salary=CASE WHEN ? != '' THEN ? ELSE salary END,
                url=CASE WHEN url = '' AND ? != '' THEN ? ELSE url END,
                canonical_url=CASE WHEN canonical_url = '' AND ? != '' THEN ? ELSE canonical_url END
            WHERE id=?
        """, (
            duplicate.last_seen or duplicate.date_discovered,
            duplicate.salary, duplicate.salary,
            duplicate.url, duplicate.url,
            duplicate.canonical_url, duplicate.canonical_url,
            canonical_id,
        ))
        if current and duplicate.match_score > current.match_score:
            self.connection.execute("""
                UPDATE jobs SET title=?, company=?, location=?, work_arrangement=?, employment_type=?,
                    salary=?, date_posted=?, description=?, category=?, tags_json=?, match_score=?, strengths_json=?,
                    weaknesses_json=?, evidence_confidence=?, provisional=?, evidence_json=?,
                    retained=MAX(retained, ?) WHERE id=?
            """, (
                duplicate.title, duplicate.company, duplicate.location, duplicate.work_arrangement,
                duplicate.employment_type, duplicate.salary, duplicate.date_posted, duplicate.description,
                duplicate.category, json.dumps(duplicate.tags), duplicate.match_score,
                json.dumps(duplicate.match_strengths),
                json.dumps(duplicate.match_weaknesses), duplicate.evidence_confidence,
                int(duplicate.provisional), json.dumps(duplicate.evidence_levels), int(retained), canonical_id,
            ))
        for link in duplicate.source_links:
            self.add_source_link(canonical_id, link["source"], link.get("source_job_id", ""), link["url"])
        self.connection.commit()

    def save_url_resolution(self, job: JobListing):
        """Persist URL trust metadata independently from match scoring."""
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
                destination_type=excluded.destination_type,
                redirect_url=excluded.redirect_url,
                resolved_at=excluded.resolved_at,
                resolution_error=excluded.resolution_error
        """, (
            job.id, job.url_verification_status, job.authoritative_url,
            job.authoritative_url_confidence, job.url_destination_type,
            job.url_redirect_url, job.url_resolved_at, job.url_resolution_error,
        ))
        self.connection.commit()

    def update_scoring(self, job: JobListing, retained: bool):
        """Persist a recalculated score without changing lifecycle or source data."""
        if job.id is None:
            raise ValueError("Cannot update scoring for an unsaved job")
        self.connection.execute("""
            UPDATE jobs SET match_score=?, evidence_confidence=?, provisional=?, evidence_json=?,
                strengths_json=?, weaknesses_json=?, retained=? WHERE id=?
        """, (
            job.match_score, job.evidence_confidence, int(job.provisional),
            json.dumps(job.evidence_levels), json.dumps(job.match_strengths),
            json.dumps(job.match_weaknesses), int(retained), job.id,
        ))
        self.connection.commit()

    def save_enrichment(self, job: JobListing):
        """Persist original and enriched evidence independently from the provider listing."""
        if job.id is None:
            raise ValueError("Cannot save enrichment for an unsaved job")
        self.connection.execute("""
            INSERT INTO enrichments (
                job_id,original_description,original_match_score,original_evidence_confidence,
                original_url,enriched_description,enriched_source_url,enriched_at,
                enrichment_status,enrichment_error,enriched_match_score,enriched_evidence_confidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                enriched_description=excluded.enriched_description,
                enriched_source_url=excluded.enriched_source_url,
                enriched_at=excluded.enriched_at,
                enrichment_status=excluded.enrichment_status,
                enrichment_error=excluded.enrichment_error,
                enriched_match_score=excluded.enriched_match_score,
                enriched_evidence_confidence=excluded.enriched_evidence_confidence
        """, (
            job.id, job.original_description, job.original_match_score,
            job.original_evidence_confidence, job.original_url, job.enriched_description,
            job.enriched_source_url, job.enriched_at, job.enrichment_status,
            job.enrichment_error, job.enriched_match_score, job.enriched_evidence_confidence,
        ))
        self.connection.commit()
