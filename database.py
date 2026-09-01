"""
Shared SQLite access layer for the Jobhunt application.

Keeps the schema compatible with the existing Python automation scripts.
All application/API writes go through this module.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

# Use JOBHUNT_DB if set; otherwise use the SQLite file next to this module.
DB_PATH = Path(os.environ.get("JOBHUNT_DB", Path(__file__).resolve().parent.parent / "jobs.sqlite3"))
print(DB_PATH)
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_tab TEXT NOT NULL,
    source_row INTEGER,
    date_found TEXT,
    track TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    salary TEXT,
    link TEXT UNIQUE,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'Review to Apply',
    interview_date TEXT,
    follow_up_sent TEXT,
    salary_offered TEXT,
    not_interested_checked INTEGER NOT NULL DEFAULT 0,
    unsure INTEGER NOT NULL DEFAULT 0,
    is_modified INTEGER NOT NULL DEFAULT 0,
    preference_added INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    submitted_resume TEXT,
    submitted_cover_letter TEXT
);

CREATE TABLE IF NOT EXISTS job_locations (
    job_id INTEGER NOT NULL,
    location TEXT NOT NULL,
    PRIMARY KEY (job_id, location),
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS job_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    preference TEXT NOT NULL CHECK (preference IN ('liked', 'disliked')),
    title TEXT NOT NULL,
    location TEXT,
    description TEXT,
    keywords TEXT,
    source_status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(title);
CREATE INDEX IF NOT EXISTS idx_preferences_preference ON job_preferences(preference);
"""

# Additive migrations only: these columns may already exist in a deployed DB.
# Use explicit SQLite types/defaults so missing columns are added safely to an existing DB.
ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "jobs": [
        ("submitted_resume", "TEXT"),
        ("submitted_cover_letter", "TEXT"),
        ("unsure", "INTEGER NOT NULL DEFAULT 0"),
        ("is_modified", "INTEGER NOT NULL DEFAULT 0"),
    ],
}


def get_connection() -> sqlite3.Connection:
    """Open a SQLite connection with Row access and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add missing columns to existing tables without dropping data."""
    for table, columns in ADDITIVE_COLUMNS.items():
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for column_name, column_type in columns:
            if column_name not in existing:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}"
                )


def init_db() -> None:
    """Create missing tables/indexes and apply additive migrations. Safe to run repeatedly."""
    with closing(get_connection()) as conn:
        conn.executescript(SCHEMA_SQL)
        _ensure_columns(conn)
        conn.commit()