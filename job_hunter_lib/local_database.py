"""SQLite persistence for jobs displayed by the local website."""

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from job_hunter_lib.utils import generate_job_id


DATABASE_PATH = Path(__file__).resolve().parent.parent / "jobs.db"
VALID_STATUSES = {"new", "old", "saved", "applied"}


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            job_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            appearance_count INTEGER NOT NULL DEFAULT 1,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            ai_analyzed INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
    if "ai_analyzed" not in columns:
        connection.execute("ALTER TABLE jobs ADD COLUMN ai_analyzed INTEGER NOT NULL DEFAULT 0")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_deliveries (
            job_id TEXT NOT NULL,
            recipient TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            PRIMARY KEY (job_id, recipient)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_job_matches (
            cv_hash TEXT NOT NULL,
            job_hash TEXT NOT NULL,
            model TEXT NOT NULL,
            analysis_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (cv_hash, job_hash, model)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_companies (
            company_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            ats_type TEXT NOT NULL,
            config_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cleanup_database_hygiene(connection)
    return connection


def get_custom_companies() -> list[dict]:
    """Return all user-added custom companies."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT company_id, name, ats_type, config_json, created_at FROM custom_companies ORDER BY name ASC"
        ).fetchall()
    companies = []
    for row in rows:
        try:
            config = json.loads(row["config_json"])
        except Exception:
            config = {}
        companies.append({
            "company_id": row["company_id"],
            "name": row["name"],
            "ats_type": row["ats_type"],
            "config": config,
            "created_at": row["created_at"],
        })
    return companies


def add_custom_company(name: str, ats_type: str, config: dict) -> dict:
    """Save a new custom company to SQLite and return the saved object."""
    clean_name = str(name).strip()
    clean_ats = str(ats_type).strip().lower()
    company_id = re.sub(r"[^a-z0-9_]+", "_", clean_name.lower()).strip("_") or f"custom_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    now = datetime.now(timezone.utc).isoformat()
    
    with _connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO custom_companies
            (company_id, name, ats_type, config_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (company_id, clean_name, clean_ats, json.dumps(config), now),
        )
    return {
        "company_id": company_id,
        "name": clean_name,
        "ats_type": clean_ats,
        "config": config,
        "created_at": now,
    }


def delete_custom_company(company_id: str) -> bool:
    """Delete a custom company by its ID."""
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM custom_companies WHERE company_id = ?",
            (company_id,),
        )
        return cursor.rowcount > 0



def cleanup_database_hygiene(connection: sqlite3.Connection) -> None:
    """Purge junk jobs, deduplicate multiple records for the same URL, and age stale postings."""
    try:
        connection.execute(
            """
            DELETE FROM jobs 
            WHERE json_extract(job_json, '$.title') IS NULL 
               OR json_extract(job_json, '$.title') = '' 
               OR json_extract(job_json, '$.title') = 'Untitled role' 
               OR json_extract(job_json, '$.title') LIKE 'Image %' 
               OR json_extract(job_json, '$.url') LIKE '%.svg'
               OR json_extract(job_json, '$.url') IN (
                   'https://kla.wd1.myworkdayjobs.com/Search',
                   'https://paloaltonetworks.wd5.myworkdayjobs.com/',
                   'https://amat.wd1.myworkdayjobs.com/External',
                   'https://nvidia.wd5.myworkdayjobs.com'
               )
            """
        )
        rows = connection.execute(
            """
            SELECT json_extract(job_json, '$.url') as url, count(*) as c
            FROM jobs
            WHERE url IS NOT NULL AND url != '' AND url != '#'
            GROUP BY url
            HAVING c > 1
            """
        ).fetchall()
        for row in rows:
            url = row["url"]
            dup_rows = connection.execute(
                "SELECT job_id, appearance_count, status, first_seen, last_seen FROM jobs WHERE json_extract(job_json, '$.url') = ?",
                (url,)
            ).fetchall()
            if len(dup_rows) <= 1:
                continue
            max_count = max(r["appearance_count"] for r in dup_rows)
            statuses = [r["status"] for r in dup_rows]
            final_status = "applied" if "applied" in statuses else ("saved" if "saved" in statuses else ("old" if max_count > 1 else "new"))
            earliest_first = min(r["first_seen"] for r in dup_rows)
            latest_last = max(r["last_seen"] for r in dup_rows)
            best_row = max(dup_rows, key=lambda r: (r["appearance_count"], r["last_seen"]))
            best_id = best_row["job_id"]
            for r in dup_rows:
                if r["job_id"] != best_id:
                    connection.execute("DELETE FROM jobs WHERE job_id = ?", (r["job_id"],))
            connection.execute(
                "UPDATE jobs SET appearance_count = ?, status = ?, first_seen = ?, last_seen = ? WHERE job_id = ?",
                (max_count, final_status, earliest_first, latest_last, best_id)
            )
        connection.execute("UPDATE jobs SET status = 'old' WHERE appearance_count > 3 AND status = 'new'")
        connection.execute("UPDATE jobs SET status = 'old' WHERE status = 'new' AND last_seen < datetime('now', '-2 days')")
    except Exception:
        pass


def get_ai_job_match(cv_hash: str, job_hash: str, model: str) -> dict | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT analysis_json FROM ai_job_matches WHERE cv_hash = ? AND job_hash = ? AND model = ?",
            (cv_hash, job_hash, model),
        ).fetchone()
    return json.loads(row["analysis_json"]) if row else None


def save_ai_job_match(cv_hash: str, job_hash: str, model: str, analysis: dict) -> None:
    with _connect() as connection:
        connection.execute(
            """INSERT OR REPLACE INTO ai_job_matches
               (cv_hash, job_hash, model, analysis_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (cv_hash, job_hash, model, json.dumps(analysis), datetime.now(timezone.utc).isoformat()),
        )


def save_search_results(jobs: list[dict], run_seen_ids: set | None = None) -> list[dict]:
    """Save one search run (or incremental batch), incrementing each unique job exactly once per run."""
    now = datetime.now(timezone.utc).isoformat()
    saved = []
    with _connect() as connection:
        for source_job in jobs:
            job = dict(source_job)
            job_id = str(job.get("job_id") or generate_job_id(job))
            job["job_id"] = job_id
            existing = connection.execute(
                "SELECT job_json, status, appearance_count, first_seen, ai_analyzed FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()

            if existing:
                previously_analyzed = bool(existing["ai_analyzed"])
                ai_analyzed = previously_analyzed or bool(job.get("ai_analyzed") or job.get("ai_analysis"))
                if previously_analyzed:
                    previous_job = json.loads(existing["job_json"])
                    for field in ("match_score", "match_reason", "ai_analysis", "score_source"):
                        if field in previous_job:
                            job[field] = previous_job[field]
                already_counted_this_run = run_seen_ids is not None and job_id in run_seen_ids
                count = existing["appearance_count"] if already_counted_this_run else (existing["appearance_count"] + 1)
                # Explicit user choices always win over automatic aging. More than 3x seen is old.
                status = existing["status"] if existing["status"] in {"saved", "applied"} else ("old" if count > 3 else "new")
                first_seen = existing["first_seen"]
                connection.execute(
                    """UPDATE jobs
                       SET job_json = ?, status = ?, appearance_count = ?, last_seen = ?, ai_analyzed = ?
                       WHERE job_id = ?""",
                    (json.dumps(job), status, count, now, int(ai_analyzed), job_id),
                )
            else:
                ai_analyzed = bool(job.get("ai_analyzed") or job.get("ai_analysis"))
                count = 1
                status = "new"
                first_seen = now
                connection.execute(
                    """INSERT INTO jobs
                       (job_id, job_json, status, appearance_count, first_seen, last_seen, ai_analyzed)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (job_id, json.dumps(job), status, count, now, now, int(ai_analyzed)),
                )

            if run_seen_ids is not None:
                run_seen_ids.add(job_id)

            job.update(status=status, appearance_count=count, first_seen=first_seen, last_seen=now, ai_analyzed=ai_analyzed)
            saved.append(job)
    return saved


def get_all_jobs() -> list[dict]:
    """Return all saved jobs, most recently seen first."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT job_json, status, appearance_count, first_seen, last_seen, ai_analyzed FROM jobs ORDER BY last_seen DESC"
        ).fetchall()
    jobs = []
    for row in rows:
        job = json.loads(row["job_json"])
        job.update(
            status=row["status"],
            appearance_count=row["appearance_count"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            ai_analyzed=bool(row["ai_analyzed"]),
        )
        jobs.append(job)
    return jobs


def get_unsent_new_jobs(recipient: str) -> list[dict]:
    """Return new jobs that have never been sent to this Telegram recipient."""
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT j.job_json, j.status, j.appearance_count, j.first_seen, j.last_seen, j.ai_analyzed
            FROM jobs AS j
            LEFT JOIN telegram_deliveries AS delivery
              ON delivery.job_id = j.job_id AND delivery.recipient = ?
            WHERE j.status = 'new' AND delivery.job_id IS NULL
            ORDER BY j.first_seen DESC
            """,
            (recipient,),
        ).fetchall()
    jobs = []
    for row in rows:
        job = json.loads(row["job_json"])
        job.update(
            status=row["status"],
            appearance_count=row["appearance_count"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            ai_analyzed=bool(row["ai_analyzed"]),
        )
        jobs.append(job)
    return jobs


def mark_jobs_sent_to_telegram(job_ids: list[str], recipient: str):
    """Record a successful Telegram delivery for each job and recipient."""
    sent_at = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.executemany(
            "INSERT OR IGNORE INTO telegram_deliveries (job_id, recipient, sent_at) VALUES (?, ?, ?)",
            [(job_id, recipient, sent_at) for job_id in job_ids],
        )


def save_job_ai_analysis(job_id: str, analysis: dict, match_reason: str, score_source: str) -> dict | None:
    """Persist a completed AI result and permanently flag the job as analyzed."""
    with _connect() as connection:
        row = connection.execute("SELECT job_json FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        job = json.loads(row["job_json"])
        job.update(
            match_score=analysis["score"],
            match_reason=match_reason,
            ai_analysis=analysis,
            score_source=score_source,
            ai_analyzed=True,
        )
        connection.execute(
            "UPDATE jobs SET job_json = ?, ai_analyzed = 1 WHERE job_id = ?",
            (json.dumps(job), job_id),
        )
    return job


def update_job_status(job_id: str, status: str) -> dict | None:
    """Set a saved job's status and return its updated representation."""
    if status not in VALID_STATUSES:
        raise ValueError("Status must be new, old, saved, or applied")
    with _connect() as connection:
        result = connection.execute(
            "UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id)
        )
        if result.rowcount == 0:
            return None
        row = connection.execute(
            "SELECT job_json, status, appearance_count, first_seen, last_seen, ai_analyzed FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    job = json.loads(row["job_json"])
    job.update(status=row["status"], appearance_count=row["appearance_count"], first_seen=row["first_seen"], last_seen=row["last_seen"], ai_analyzed=bool(row["ai_analyzed"]))
    return job
