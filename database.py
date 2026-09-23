"""
Shared SQLite access layer for the Jobhunt application.

Keeps the schema compatible with the existing Python automation scripts.
All application/API writes go through this module.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

# Ensure the project root is on sys.path so shared_schema can be imported.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared_schema import (  # noqa: E402
    SHARED_INDEXES,
    SHARED_SCHEMA_SQL,
    REVIEW_STATUS,
    READY_STATUS,
    NOT_INTERESTED_STATUS,
    AWAITING_RESPONSE_STATUS,
    DUPLICATE_STATUS,
    ALL_STATUSES,
    CANONICAL_LOCATIONS,
    LOCATION_ALIASES,
    TRACK_KEYS,
    TRACK_LABELS,
    LABEL_TO_TRACK_KEY,
    migrate_job_preferences_check,
    normalize_location,
    normalize_track_value,
    format_salary,
    detect_ats,
    detect_ai_hiring,
)

# The canonical deployed database, shared with the daemon. The old candidate
# list included a stale db_backups copy: if the main DB went missing the app
# silently booted on an old backup (split-brain vs the daemon). Fail loudly
# instead — only the JOBHUNT_DB env override may point elsewhere.
_CANONICAL_DB = Path("/home/gabby/Documents/projects/jobs.sqlite3")


def _resolve_db_path() -> Path:
    override = os.environ.get("JOBHUNT_DB")
    if override:
        return Path(override).expanduser().resolve()

    if not _CANONICAL_DB.exists():
        raise FileNotFoundError(
            f"Main database not found at {_CANONICAL_DB} "
            "(set JOBHUNT_DB to override)"
        )
    return _CANONICAL_DB.resolve()


DB_PATH = _resolve_db_path()
# Schema is now sourced from shared_schema to stay in sync with the daemon.
SCHEMA_SQL = SHARED_SCHEMA_SQL

# Additive migrations only: these columns may already exist in a deployed DB.
# Use explicit SQLite types/defaults so missing columns are added safely to an existing DB.
ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "jobs": [
        ("submitted_resume", "TEXT"),
        ("submitted_cover_letter", "TEXT"),
        ("unsure", "INTEGER NOT NULL DEFAULT 0"),
        ("is_modified", "INTEGER NOT NULL DEFAULT 0"),
        ("preference_added", "INTEGER NOT NULL DEFAULT 0"),
        # Daemon-owned columns (daemon adds these via its own migration;
        # listing them here so the webapp is aware and the init path is self-contained)
        ("source", "TEXT"),
        ("job_id", "TEXT"),
        ("employment_type", "TEXT"),
        ("notes", "TEXT"),
        ("target_tab", "TEXT"),
        ("relevance_score", "INTEGER"),
        ("passed_at", "TEXT"),
        ("archived", "INTEGER NOT NULL DEFAULT 0"),
        # Matched employer email (daemon mail tracker writes these; the
        # Notifications page links out to the email via email_link).
        ("email_link", "TEXT"),
        ("email_subject", "TEXT"),
        ("email_received_at", "TEXT"),
        # New feature columns
        ("application_deadline", "TEXT"),
        ("salary_min", "INTEGER"),
        ("salary_max", "INTEGER"),
        ("salary_currency", "TEXT"),
    ],
    "user_preferences": [
        ("energy_max_reviews", "INTEGER NOT NULL DEFAULT 50"),
        ("theme", "TEXT NOT NULL DEFAULT 'light'"),
    ],
    "user_tracks": [
        ("color", "TEXT"),
    ],
    "user_session_stats": [
        ("points", "INTEGER NOT NULL DEFAULT 0"),
        ("raffle_tickets", "INTEGER NOT NULL DEFAULT 0"),
    ],
    # Daemon-computed skill demand (see jobhunt-daemon/processing/skill_demand.py).
    # The manual market_demand column stays but is no longer read or written by
    # the UI — demand_auto is the live value.
    "skill_assessments": [
        ("demand_auto", "INTEGER"),
        ("demand_job_count", "INTEGER"),
        ("demand_updated_at", "TEXT"),
    ],
}

# --- Multi-user + gamification additive tables ---
USER_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_default INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_session_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,  -- 'like' | 'dislike' | 'unsure' | 'duplicate' | 'apply'
    job_id INTEGER,
    job_score INTEGER,          -- relevance score at time of review
    points INTEGER NOT NULL DEFAULT 0,
    raffle_tickets INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    badge_key TEXT NOT NULL,
    earned_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, badge_key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER PRIMARY KEY,
    default_job_types TEXT,      -- JSON array of track values
    default_locations TEXT,      -- JSON array of source_tab values
    default_tracks TEXT,        -- JSON array of track values (aliases for job_types)
    default_keywords TEXT,      -- JSON array of keyword strings
    blacklist_terms TEXT,       -- JSON array of terms to exclude
    preferred_keywords TEXT,     -- JSON array of bonus keywords
    daily_goal INTEGER NOT NULL DEFAULT 10,
    exclude_already_seen INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_job_state (
    user_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    status TEXT NOT NULL,       -- 'seen' | 'liked' | 'disliked' | 'unsure' | 'duplicate' | 'applied'
    score INTEGER,              -- cached relevance score at time of seen
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, job_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS job_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    score INTEGER NOT NULL,     -- 0-100
    confidence REAL,            -- 0.0-1.0
    reasoning TEXT,
    scored_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, job_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_session_stats_user ON user_session_stats(user_id);
CREATE INDEX IF NOT EXISTS idx_user_session_stats_date ON user_session_stats(created_at);
CREATE INDEX IF NOT EXISTS idx_user_badges_user ON user_badges(user_id);
CREATE INDEX IF NOT EXISTS idx_user_job_state_user ON user_job_state(user_id);
CREATE INDEX IF NOT EXISTS idx_user_job_state_seen ON user_job_state(user_id, status);
CREATE INDEX IF NOT EXISTS idx_job_scores_user ON job_scores(user_id);
"""

# --- New: cover letters, contacts, streak freezes, interview prep, skill gap ---
FEATURE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS cover_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    job_id INTEGER,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    company TEXT,
    role TEXT,
    email TEXT,
    linkedin_url TEXT,
    notes TEXT,
    last_contacted_at TEXT,
    next_follow_up_at TEXT,
    warmth INTEGER NOT NULL DEFAULT 1,  -- 1=cold, 2=warm, 3=hot
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS streak_freezes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    used_on TEXT NOT NULL,  -- ISO date YYYY-MM-DD that was saved
    source TEXT NOT NULL,   -- 'earned' | 'manual' | 'system'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, used_on),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS skill_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    skill TEXT NOT NULL,
    self_rating INTEGER NOT NULL CHECK (self_rating BETWEEN 1 AND 5),
    market_demand INTEGER NOT NULL CHECK (market_demand BETWEEN 1 AND 5),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, skill),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS interview_prep (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    job_id INTEGER,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    interview_date TEXT,
    prep_notes TEXT,
    questions_to_ask TEXT,
    follow_up_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_date TEXT NOT NULL,        -- YYYY-MM-DD
    source TEXT NOT NULL,             -- 'linkedin' | 'indeed' | 'wellfound' | 'remoteok' | 'greenhouse'
    jobs_found INTEGER NOT NULL DEFAULT 0,
    jobs_inserted INTEGER NOT NULL DEFAULT 0,
    jobs_merged INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(metric_date, source)
);

CREATE INDEX IF NOT EXISTS idx_cover_letters_user ON cover_letters(user_id);
CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_id);
CREATE INDEX IF NOT EXISTS idx_contacts_follow_up ON contacts(next_follow_up_at);
CREATE INDEX IF NOT EXISTS idx_interview_prep_user ON interview_prep(user_id);
CREATE INDEX IF NOT EXISTS idx_interview_prep_date ON interview_prep(interview_date);
CREATE INDEX IF NOT EXISTS idx_skill_assessments_user ON skill_assessments(user_id);
CREATE INDEX IF NOT EXISTS idx_daily_metrics_date ON daily_metrics(metric_date);

-- ----------------------------------------------------------------------------
-- User-defined regions: replaces the hardcoded LA/NY/BC/ON canonical set
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    color TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, code),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_location_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    FOREIGN KEY (region_id) REFERENCES user_regions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_regions_user ON user_regions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_regions_code ON user_regions(code);
CREATE INDEX IF NOT EXISTS idx_user_location_aliases_region ON user_location_aliases(region_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_location_aliases_unique
    ON user_location_aliases(region_id, alias);

-- ----------------------------------------------------------------------------
-- User-defined tracks: editable per-track titles + keywords (regions-style).
-- "not a fit" is reserved: never seeded, never listed, never deletable.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    color TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_track_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL,
    term_type TEXT NOT NULL CHECK (term_type IN ('title', 'keyword')),
    value TEXT NOT NULL,
    FOREIGN KEY (track_id) REFERENCES user_tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_tracks_user ON user_tracks(user_id);
CREATE INDEX IF NOT EXISTS idx_user_track_terms_track ON user_track_terms(track_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_track_terms_unique
    ON user_track_terms(track_id, term_type, value);
"""


def get_connection() -> sqlite3.Connection:
    """Open a SQLite connection with Row access and foreign keys enabled.

    busy_timeout/WAL mirror the daemon's core.database.get_connection(): both
    processes share one jobs.sqlite3, and the webapp's old timeout=5 with no
    busy_timeout made every write race lose to the daemon's long transactions
    ("database is locked" on both sides).
    """
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# ── Write-behind: durable side store ─────────────────────────────────────────────
# Pending web-app writes live in web_pending_writes.sqlite3, a tiny separate
# SQLite file next to the main DB. The daemon's scrape transactions never lock
# it, so a pending write is persisted instantly and survives web-app restarts.
# Reads overlay staged values (the side store wins on contradiction), and the
# store is drained by both the web flusher thread and the daemon each cycle.

_log = logging.getLogger(__name__)

_pending_store_ready = False


def _ensure_pending_store() -> None:
    """Open (once) the pending-write side store beside the main DB."""
    global _pending_store_ready
    if _pending_store_ready:
        return
    import pending_writes
    pending_writes.ensure_store(DB_PATH.parent)
    _pending_store_ready = True


def init_pending_store() -> None:
    """Public init hook for app startup."""
    _ensure_pending_store()


def queue_write(sql: str, params: tuple = (), table: str = "jobs",
                row_key: str = "", payload: dict | None = None,
                retry: bool = True) -> bool:
    """Write to the main DB fast (2s); on lock, stage durably in the side store.

    Returns True if the write was staged (deferred), False if it applied
    immediately. Callers that stage should pass ``row_key``/``payload`` so the
    side store can (a) collapse contradictory writes (last write wins) and
    (b) overlay reads until the daemon applies the staged row.

    Generic non-SELECT statements (INSERT/UPDATE/DELETE on any table) are
    staged as raw (sql, params) when they hit a lock — only jobs +
    user_preferences get payload overlay support, other tables simply replay
    verbatim on drain. When ``retry`` is False the lock error propagates
    (callers that must confirm, e.g. raw INSERTs returning rows).
    """
    _ensure_pending_store()
    import pending_writes
    intent = _intent_from_sql(sql, params, table, row_key, payload)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=2)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 2000")
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "locked" not in msg and "busy" not in msg:
            raise
        if not retry:
            raise
        if intent:
            pending_writes.stage_write(
                DB_PATH, intent[0], intent[1], intent[2]
            )
        else:
            pending_writes.stage_raw(DB_PATH, sql, list(params))
        return True  # queued for later
    if intent:
        target_table, row_key = intent[0], intent[1]
        pending_writes.clear_staged(DB_PATH, target_table, row_key)
    return False  # applied immediately


def _intent_from_sql(sql: str, params, table: str, row_key: str,
                     payload: dict | None) -> tuple[str, str, dict] | None:
    """Build (target_table, row_key, payload) for the side store from a known
    service write. Returns None for unrecognized statements (no staging)."""
    if table == "jobs" and row_key:
        return (table, str(row_key), payload if payload is not None else {})
    if table == "user_preferences" and row_key:
        p = payload
        if p is None and len(params) >= 8:
            p = {
                "user_id": int(params[0]),
                "prefs": {
                    "default_tracks": json.loads(params[1] or "[]"),
                    "default_keywords": json.loads(params[2] or "[]"),
                    "blacklist_terms": json.loads(params[3] or "[]"),
                    "daily_goal": int(params[4] or 10),
                    "exclude_already_seen": 1 if params[5] else 0,
                    "energy_max_reviews": int(params[6] or 50),
                    "theme": params[7] or "light",
                },
            }
        if p is not None:
            return (table, str(row_key), p)
    return None


def overlay_job_pending(job: dict) -> dict:
    """Prioritize the side store: overlay ALL staged columns onto a job row.

    Last write wins per (target_table, row_key), so when a staged payload and
    the main-DB row contradict, the staged value is applied. Only whitelisted
    columns are overlaid (mirrors ``apply_pending_write`` in pending_writes).
    """
    _OVERLAYABLE_JOB_COLUMNS = (
        "status", "archived", "notes", "track", "application_deadline",
        "interview_date", "follow_up_sent", "salary_offered", "applied_at",
        "submitted_resume", "submitted_cover_letter", "passed_at", "unsure",
        "is_modified", "preference_added", "not_interested_checked",
    )
    _INT_COLUMNS = frozenset({
        "archived", "unsure", "is_modified",
        "preference_added", "not_interested_checked",
    })
    try:
        _ensure_pending_store()
        import pending_writes
        pw = pending_writes.overlay_cached(DB_PATH, "jobs").get(str(job.get("id")))
        if pw:
            for col in _OVERLAYABLE_JOB_COLUMNS:
                if col in pw:
                    job[col] = int(pw[col]) if col in _INT_COLUMNS else pw[col]
    except Exception:
        pass
    return job


def overlay_job_archived(job: dict) -> dict:
    """Backward-compat wrapper: overlays staged pending columns onto a job."""
    return overlay_job_pending(job)


def pending_prefs_overlay(user_id: int) -> dict | None:
    """Staged preference payload for a user, if any (side store wins)."""
    try:
        _ensure_pending_store()
        import pending_writes
        pw = pending_writes.overlay_cached(DB_PATH, "user_preferences").get(str(user_id))
        if pw and pw.get("prefs"):
            return dict(pw["prefs"])
    except Exception:
        return None
    return None





@contextmanager
def locked_connection(timeout: float = 60.0):
    """Open a main-DB connection that waits behind the daemon's write lock.

    Runs the same BEGIN IMMEDIATE admission as the daemon's write_connection
    (minus the OS flock): instead of failing fast when a scrape holds the DB,
    the web request waits up to ``timeout`` seconds. Use for multi-step writes
    (swipe, apply, merge) that must stay atomic — they can't split across
    queue_write + pending overlay.
    """
    import pending_writes

    conn = sqlite3.connect(DB_PATH, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    deadline = time.monotonic() + timeout
    while True:
        try:
            conn.execute("BEGIN IMMEDIATE")
            break
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "locked" not in msg and "busy" not in msg:
                conn.close()
                raise
            if time.monotonic() >= deadline:
                conn.close()
                raise
            time.sleep(0.2)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    try:
        pending_writes.invalidate_overlay()
    except Exception:
        pass
def drain_write_queue():
    """Apply staged side-store writes to the main DB now; returns count applied.

    Called by the background flusher thread in ``start_write_queue_flusher``
    and by the daemon each cycle. Stops at the first write that still hits a
    busy main DB — remaining rows stay staged (order preserved).
    """
    _ensure_pending_store()
    import pending_writes
    try:
        with closing(get_connection()) as conn:
            return pending_writes.drain_pending(DB_PATH, conn)
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "locked" in msg or "busy" in msg:
            return 0  # main DB still busy; rows stay staged for next tick
        raise


def get_write_queue_size() -> int:
    """Return the number of pending (staged) write operations."""
    try:
        _ensure_pending_store()
        import pending_writes
        return pending_writes.pending_count(DB_PATH)
    except Exception:
        return 0


_flusher_started = False


def start_write_queue_flusher(interval: float = 5.0) -> None:
    """Start a daemon thread that periodically flushes the side store.

    The daemon holds long write locks while scraping, so staged writes may sit
    for a while. Flushing on a background timer guarantees staged writes land
    once the database is free even if the user makes no requests.
    """
    global _flusher_started
    if _flusher_started:
        return
    _flusher_started = True

    def _loop() -> None:
        while True:
            try:
                drained = drain_write_queue()
                if drained:
                    _log.info("Flushed %s staged web write(s)", drained)
            except Exception:
                _log.exception("Write-queue flusher error")
            time.sleep(interval)

    threading.Thread(target=_loop, name="write-queue-flusher", daemon=True).start()


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add missing columns to existing tables without dropping data."""
    for table, columns in ADDITIVE_COLUMNS.items():
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if not exists:
            # Table not created by this init path (e.g. daemon-owned table on a
            # fresh DB). Skip instead of crashing on ALTER TABLE.
            continue
        existing = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for column_name, column_type in columns:
            if column_name not in existing:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}"
                )


def ensure_additive_columns() -> None:
    """Public entry point for additive column migration.

    Wraps ``_ensure_columns`` with its own connection so callers (like
    ``app.py``) don't need to manage a connection. Safe to call at every
    startup — missing columns are added via ``ALTER TABLE ADD COLUMN``;
    already-present columns are skipped.
    """
    with closing(get_connection()) as conn:
        _ensure_columns(conn)
        conn.commit()


# ---------------------------------------------------------------------------
# Note: LOCATION_ALIASES, CANONICAL_LOCATIONS, normalize_location,
# TRACK_ALIASES, and normalize_track_value are imported from shared_schema
# to ensure the daemon and webapp stay in sync.
# ---------------------------------------------------------------------------


def _save_locations_for_job(conn: sqlite3.Connection, job_id: int, locations: list[str]) -> list[str]:
    """Normalize + dedupe raw location strings and persist the canonical set.

    Only canonical region codes (LA/NY/BC/ON) and "Remote" survive; generic
    tokens and unrecognized raw variants are dropped so the job_locations table
    and the jobs.location blob cannot grow unbounded across merges. Also keeps
    jobs.location in sync as a canonical comma-joined list.
    """
    clean: list[str] = []
    seen: set[str] = set()
    for raw in locations:
        loc = normalize_location(str(raw or "").strip())
        if not loc:
            continue
        key = loc.lower()
        if key in seen:
            continue
        seen.add(key)
        if loc == "Remote" or loc.upper() in CANONICAL_LOCATIONS:
            clean.append(loc)
    clean.sort()

    conn.execute("DELETE FROM job_locations WHERE job_id = ?", (job_id,))
    for loc in clean:
        conn.execute(
            "INSERT OR IGNORE INTO job_locations (job_id, location) VALUES (?, ?)",
            (job_id, loc),
        )
    has_location_col = any(
        row["name"] == "location"
        for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    )
    if has_location_col:
        conn.execute(
            "UPDATE jobs SET location = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (", ".join(clean), job_id),
        )
    return clean


def merge_duplicate_jobs(conn: sqlite3.Connection, kept_job_id: int, removed_job_id: int) -> dict:
    """Merge a duplicate record into the preserved record, keeping the richer description and combined locations.

    Schema-tolerant: handles both the daemon schema (jobs.location TEXT) and the
    web-app schema (job_locations side table only).
    """
    if kept_job_id == removed_job_id:
        return {"kept_job_id": kept_job_id, "removed_job_id": removed_job_id, "locations": [], "merged": False}

    # Detect whether jobs has a single `location` column (daemon) or not (web app)
    has_location_col = any(
        row["name"] == "location"
        for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    )

    if has_location_col:
        kept_row = conn.execute(
            "SELECT id, description, location, status FROM jobs WHERE id = ?", (kept_job_id,)
        ).fetchone()
        removed_row = conn.execute(
            "SELECT id, description, location FROM jobs WHERE id = ?", (removed_job_id,)
        ).fetchone()
    else:
        kept_row = conn.execute(
            "SELECT id, description, status FROM jobs WHERE id = ?", (kept_job_id,)
        ).fetchone()
        removed_row = conn.execute(
            "SELECT id, description FROM jobs WHERE id = ?", (removed_job_id,)
        ).fetchone()
        kept_row = dict(kept_row) if kept_row else None
        removed_row = dict(removed_row) if removed_row else None
        if kept_row is not None:
            kept_row["location"] = None
        if removed_row is not None:
            removed_row["location"] = None

    # Convert Row → dict so .get() works uniformly on both rows
    if kept_row is not None and not isinstance(kept_row, dict):
        kept_row = dict(kept_row)
    if removed_row is not None and not isinstance(removed_row, dict):
        removed_row = dict(removed_row)

    if kept_row is None or removed_row is None:
        raise ValueError("Both jobs must exist before merging")

    kept_description = str(kept_row.get("description") or "")
    removed_description = str(removed_row.get("description") or "")
    def description_score(value: str) -> tuple[int, int]:
        cleaned = " ".join(value.split())
        placeholders = {"", "none", "n/a", "na", "not specified", "no description provided"}
        meaningful = 0 if cleaned.lower() in placeholders else 1
        return meaningful, len(cleaned)

    if description_score(removed_description) > description_score(kept_description):
        conn.execute(
            "UPDATE jobs SET description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (removed_description, kept_job_id),
        )

    existing_locations: list[str] = []
    # Parse the comma-joined blob in jobs.location into individual locations
    # so we don't re-include the blob as a single item on every merge.
    if kept_row.get("location"):
        for s in str(kept_row["location"]).split(","):
            s = s.strip()
            if s:
                existing_locations.append(s)
    for loc_row in conn.execute(
        "SELECT location FROM job_locations WHERE job_id = ? ORDER BY location", (kept_job_id,)
    ).fetchall():
        loc = str(loc_row["location"]).strip()
        if loc:
            existing_locations.append(loc)
    for loc_row in conn.execute(
        "SELECT location FROM job_locations WHERE job_id = ? ORDER BY location", (removed_job_id,)
    ).fetchall():
        loc = str(loc_row["location"]).strip()
        if loc:
            existing_locations.append(loc)
    if removed_row.get("location"):
        for s in str(removed_row["location"]).split(","):
            s = s.strip()
            if s:
                existing_locations.append(s)

    merged_locations = _save_locations_for_job(conn, kept_job_id, existing_locations)

    # Preserve all user-owned data that points at the duplicate before deleting
    # it. The two per-user tables can conflict when both jobs have state, so
    # merge those rows explicitly instead of relying on a blind UPDATE.
    for state in conn.execute(
        "SELECT * FROM user_job_state WHERE job_id = ?", (removed_job_id,)
    ).fetchall():
        conn.execute(
            """
            INSERT INTO user_job_state (user_id, job_id, status, score, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, job_id) DO UPDATE SET
                status = excluded.status,
                score = COALESCE(excluded.score, user_job_state.score),
                last_seen_at = MAX(excluded.last_seen_at, user_job_state.last_seen_at)
            """,
            (state["user_id"], kept_job_id, state["status"], state["score"], state["last_seen_at"]),
        )
    conn.execute("DELETE FROM user_job_state WHERE job_id = ?", (removed_job_id,))

    for score in conn.execute(
        "SELECT * FROM job_scores WHERE job_id = ?", (removed_job_id,)
    ).fetchall():
        conn.execute(
            """
            INSERT INTO job_scores (user_id, job_id, score, confidence, reasoning, scored_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, job_id) DO UPDATE SET
                score = excluded.score,
                confidence = excluded.confidence,
                reasoning = excluded.reasoning,
                scored_at = MAX(excluded.scored_at, job_scores.scored_at)
            """,
            (
                score["user_id"], kept_job_id, score["score"], score["confidence"],
                score["reasoning"], score["scored_at"],
            ),
        )
    conn.execute("DELETE FROM job_scores WHERE job_id = ?", (removed_job_id,))

    for table in ("job_preferences", "cover_letters", "interview_prep", "user_session_stats"):
        conn.execute(f"UPDATE {table} SET job_id = ? WHERE job_id = ?", (kept_job_id, removed_job_id))

    conn.execute("DELETE FROM jobs WHERE id = ?", (removed_job_id,))
    conn.commit()
    return {
        "kept_job_id": kept_job_id,
        "removed_job_id": removed_job_id,
        "locations": merged_locations,
        "merged": True,
    }


def find_similar_job(conn: sqlite3.Connection, title: str | None, company: str | None) -> int | None:
    title_text = (title or "").strip(); company_text = (company or "").strip();
    if not title_text or not company_text:
        return None

    norm_company = _normalize_company(company_text)
    norm_title = _normalize_title(title_text)
    if not norm_company or not norm_title:
        return None

    for row in conn.execute("SELECT id, title, company FROM jobs WHERE company IS NOT NULL AND TRIM(company) != '' ORDER BY id DESC").fetchall():
        existing_company = str(row["company"] or "").strip(); existing_title = str(row["title"] or "").strip()
        if not existing_company or not existing_title:
            continue
        if not _normalize_company(existing_company):
            continue
        same_company = (
            _normalize_company(existing_company) == norm_company
            or norm_company in _normalize_company(existing_company)
            or _normalize_company(existing_company) in norm_company
        )
        if not same_company:
            continue
        left = _normalize_title(existing_title); right = _normalize_title(title_text)
        if left == right or left in right or right in left:
            return int(row["id"])
        overlap = set(left.split()) & set(right.split())
        if len(overlap) >= 2:
            return int(row["id"])
    return None


def normalize_legacy_job_tracks() -> int:
    """Rewrite legacy track aliases in the persisted jobs table to canonical values."""
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT id, track FROM jobs WHERE track IS NOT NULL").fetchall()
        updated = 0
        for row in rows:
            raw = str(row["track"] or "").strip()
            normalized = normalize_track_value(raw)
            if not normalized:
                continue
            if raw and raw != normalized:
                conn.execute(
                    "UPDATE jobs SET track = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (normalized, row["id"]),
                )
                updated += 1
        conn.commit()
        return updated


def normalize_legacy_job_locations() -> int:
    """Rewrite raw location strings in job_locations to canonical (LA/NY/BC/ON) values.

    Also collapses duplicate rows that become identical after normalization.
    Table has composite PK (job_id, location).
    """
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT job_id, location FROM job_locations").fetchall()
        updated = 0
        for row in rows:
            raw = str(row["location"] or "").strip()
            if not raw:
                continue
            try:
                canonical = normalize_location(raw)
            except Exception:
                canonical = raw  # skip malformed data
            if canonical != raw:
                try:
                    conn.execute(
                        "UPDATE job_locations SET location = ? WHERE job_id = ? AND location = ?",
                        (canonical, row["job_id"], raw),
                    )
                    updated += 1
                except Exception:
                    pass  # skip on constraint errors

        # Remove duplicates that became identical after normalization.
        dupes_removed = 0
        for row in conn.execute(
            "SELECT job_id, LOWER(TRIM(location)) as lc, COUNT(*) as n "
            "FROM job_locations WHERE location IS NOT NULL AND location != '' "
            "GROUP BY job_id, LOWER(TRIM(location)) HAVING n > 1"
        ).fetchall():
            try:
                dups = conn.execute(
                    "SELECT ROWID FROM job_locations WHERE job_id = ? AND LOWER(TRIM(location)) = ? ORDER BY ROWID",
                    (row["job_id"], row["lc"]),
                ).fetchall()
                for d in dups[1:]:
                    try:
                        conn.execute(
                            "DELETE FROM job_locations WHERE job_id = ? AND ROWID = ?",
                            (row["job_id"], d[0]),
                        )
                        dupes_removed += 1
                    except Exception:
                        pass
            except Exception:
                pass
        conn.commit()
        return updated + dupes_removed


def ensure_skill_demand_columns() -> None:
    """Additive migration for skill_assessments.demand_* columns.

    app.py skips the full init_db() (the daemon owns the deployed schema), but
    GET /api/skills selects *, so the columns must exist before the daemon's
    first skill-demand run. Idempotent; duplicate-column errors are expected.
    """
    with closing(get_connection()) as conn:
        existing = {row["name"] for row in conn.execute(
            "PRAGMA table_info(skill_assessments)").fetchall()}
        if not existing:
            return
        for name, decl in ADDITIVE_COLUMNS["skill_assessments"]:
            if name in existing:
                continue
            try:
                conn.execute(f"ALTER TABLE skill_assessments ADD COLUMN {name} {decl}")
                conn.commit()
            except sqlite3.OperationalError:
                pass


def init_db() -> None:
    """Create missing tables/indexes and apply additive migrations. Safe to run repeatedly."""
    with closing(get_connection()) as conn:
        # Create ALL tables first, then add columns. _ensure_columns() must run
        # after USER_TABLES_SQL: on a fresh database `user_preferences` does not
        # exist until then, and ALTER TABLE on a missing table crashed init_db
        # with "no such table: user_preferences" (only worked historically
        # because the production DB already had every table).
        conn.executescript(SCHEMA_SQL)
        conn.executescript(USER_TABLES_SQL)
        conn.executescript(FEATURE_TABLES_SQL)
        # Rebuild job_preferences if its CHECK constraint predates 'superdisliked'
        migrate_job_preferences_check(conn)
        _ensure_columns(conn)
        conn.commit()
    normalize_legacy_job_tracks()
    normalize_legacy_job_locations()
    _ensure_default_user()


def _ensure_default_user() -> None:
    """Create the default user (Gabby) if no users exist yet."""
    with closing(get_connection()) as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            conn.execute(
                "INSERT INTO users (username, is_default) VALUES ('Gabby', 1)"
            )
            conn.commit()
