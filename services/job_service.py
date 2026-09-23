"""Service functions used by API routes and pipeline scripts."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from database import CANONICAL_LOCATIONS, detect_ai_hiring, detect_ats, get_connection, merge_duplicate_jobs, normalize_location, normalize_track_value, overlay_job_archived, queue_write

REVIEW_STATUS = "Review to Apply"
READY_STATUS = "Ready to Apply"
NOT_INTERESTED_STATUS = "Not Interested"
AWAITING_RESPONSE_STATUS = "Awaiting Response"
DUPLICATE_STATUS = "Duplicate"
PASSED_STATUS = "Passed"

# ── Notification filtering ────────────────────────────────────────────────────────
def _days_ago(iso: str) -> Optional[int]:
    """Return days ago from ISO date; None if missing or invalid."""
    try:
        from datetime import datetime as _dt
        if not iso:
            return None
        parsed = _dt.fromisoformat(iso.replace('Z', '+00:00'))
        now = _dt.now(parsed.tzinfo)
        delta = now - parsed
        return delta.days
    except Exception:
        return None

def get_notifications() -> list[dict[str, Any]]:
    """Return applied jobs with optional employer-email alerts for notifications.

    Filtering:
    - Always include jobs with unsure=0 (i.e., active applications)
    - Applied: jobs with status="Applied" AND email_link IS NULL (no email reply yet)
    - Awaiting Response: jobs marked unsure=0 (daemon handles status updates)
    - Responded: jobs with status="Responded" (from email replies)
    - Rejected: jobs with status="Rejected" (from rejection emails)
    - Applied jobs never have email_link
    - Rejected jobs shown only if <= 30 days old (color-red)
    - All other jobs go to unsure=1 and are not shown
    """
    with closing(get_connection()) as conn:
        # Step 1: Fetch all unsure=0 jobs (active applications) with relevant columns
        query = """
        SELECT
            j.id, j.title, j.company, j.link, j.status, j.interview_date,
            j.follow_up_sent, j.updated_at, j.email_link, j.email_subject,
            j.email_received_at, j.source_tab, j.source_row
        FROM jobs j
        WHERE j.unsure = 0
        """

        rows = conn.execute(query).fetchall()
        active_jobs = [dict(row) for row in rows]

        # Step 2: Apply business logic per status category
        filtered = []
        for job in active_jobs:
            status = job.get("status") or "Applied"

            # Applied: only jobs without email replies
            if status == "Applied":
                if job.get("email_link"):
                    # Has email reply, so move to unsure and daemon will handle status change
                    conn.execute(
                        "UPDATE jobs SET unsure = 1 WHERE id = ?",
                        (job["id"],)
                    )
                    conn.commit()
                    continue
                filtered.append(job)

            # Responded: include directly (from email replies)
            elif status == "Responded":
                filtered.append(job)

            # Rejected: only if <= 30 days old (to keep UI tidy)
            elif status == "Rejected":
                ages = [_days_ago(job.get(field)) for field in ("updated_at", "email_received_at")]
                known_ages = [age for age in ages if age is not None]
                if not known_ages or all(age <= 30 for age in known_ages):
                    filtered.append(job)
                else:
                    # Older rejection moved to unsure (daemon may purge or keep for history)
                    conn.execute("UPDATE jobs SET unsure = 1 WHERE id = ?", (job["id"],))
                    conn.commit()

            # Awaiting Response: keep only as placeholder for daemon handling
            elif status == "Awaiting Response":
                # These are cleared by the previous migration, but if any remain, keep them
                filtered.append(job)

            # All other statuses (Duplicate, Passed, etc.) -> unsure=1
            else:
                conn.execute("UPDATE jobs SET unsure = 1 WHERE id = ?", (job["id"],))
                conn.commit()

        return filtered

def _job_exists(job_id: int) -> bool:
    """True when a jobs row exists — a read-only guard that never mutates."""
    with closing(get_connection()) as conn:
        return conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone() is not None

_JOB_FIELDS = """
    j.id, j.source_tab, j.source_row, j.date_found, j.track, j.title,
    j.company, j.salary, j.link, j.description, j.status, j.interview_date,
    j.follow_up_sent, j.salary_offered, j.created_at, j.updated_at,
    j.relevance_score, j.passed_at, j.archived
""".strip()


def _job_row_to_dict(row: sqlite3.Row, conn: sqlite3.Connection) -> dict[str, Any]:
    job = dict(row)
    job["track"] = normalize_track_value(job.get("track"))
    job = overlay_job_archived(job)
    try:
        ats = detect_ats(job.get("link"), job.get("description"))
    except Exception:
        ats = {"uses_ats": None, "ats_name": None, "apply_type": "Unknown"}
    job["uses_ats"] = ats["uses_ats"]
    job["ats_name"] = ats["ats_name"]
    job["apply_type"] = ats["apply_type"]
    try:
        ai = detect_ai_hiring(job.get("link"), job.get("description"))
    except Exception:
        ai = {"uses_ai": False, "ai_signal": None}
    job["uses_ai"] = ai["uses_ai"]
    job["ai_signal"] = ai["ai_signal"]
    location_rows = conn.execute(
        "SELECT location FROM job_locations WHERE job_id = ? ORDER BY location",
        (row["id"],),
    ).fetchall()
    job["locations"] = [loc["location"] for loc in location_rows]
    return job


def _description_quality_score(description: Any) -> int:
    """Higher score indicates a fuller, non-placeholder description."""
    raw = str(description or "").strip()
    if not raw:
        return 0

    lowered = raw.lower()
    placeholders = {"none", "n/a", "na", "not specified", "no description provided"}
    if lowered in placeholders or lowered.startswith("none"):
        return 0

    cleaned = " ".join(raw.split())
    if len(cleaned) >= 200:
        return 2
    if len(cleaned) >= 50:
        return 1
    return 0


def get_relevance_score(job_id: int) -> Optional[int]:
    """Return the daemon-assigned 1-10 relevance score for a job, or None.

    The score lives in jobs.relevance_score (written by the daemon's LLM
    scorer). It is on a 1-10 scale; the badge engine uses 0-100, so callers
    that feed it into user_session_stats.job_score must multiply by 10
    (see _record_and_badge in api/routes.py).
    """
    if job_id is None:
        return None
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT relevance_score FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
    if row is None or row["relevance_score"] is None:
        return None
    return int(row["relevance_score"])


def _enabled_track_names(conn: sqlite3.Connection, user_id: Optional[int]) -> list[str]:
    """Names of the user's enabled tracks — the tracks editor is the source of
    truth. Returns [] when user_id is None or the DB predates user_tracks,
    which disables track scoping (same fallback pattern as regions).

    Used to keep jobs from removed/disabled tracks out of the review queue and
    its filter dropdowns, while still allowing tracks to be deleted (their
    jobs are kept).
    """
    if user_id is None:
        return []
    try:
        return [
            (row["name"] or "").strip()
            for row in conn.execute(
                """
                SELECT name FROM user_tracks
                WHERE user_id = ? AND enabled = 1
                ORDER BY sort_order, name
                """,
                (user_id,),
            ).fetchall()
            if (row["name"] or "").strip() and (row["name"] or "").strip() != "not a fit"
        ]
    except Exception:
        return []


def get_review_queue(
    limit: int = 100,
    location: Optional[str] = None,
    job_type: Optional[str] = None,
    user_id: Optional[int] = None,
    exclude_seen: bool = False,
) -> list[dict[str, Any]]:
    """Return jobs still waiting in the raw review queue, prioritizing real descriptions."""
    safe_limit = max(1, min(int(limit), 500))
    location = (location or "").strip()
    job_type = (job_type or "").strip()
    canonical_location = normalize_location(location) if location else ""
    canonical_job_type = normalize_track_value(job_type) if job_type else ""

    # Scope to the user's enabled tracks (see _enabled_track_names) so jobs
    # from removed/disabled tracks stop resurfacing in review.
    with closing(get_connection()) as scope_conn:
        enabled_tracks = _enabled_track_names(scope_conn, user_id)

    query = f"""
        SELECT {_JOB_FIELDS},
               COALESCE(j.relevance_score, 0) AS relevance_score,
               CASE
                   WHEN j.description IS NULL OR TRIM(j.description) = '' THEN 0
                   WHEN LOWER(TRIM(j.description)) IN ('none', 'n/a', 'na', 'not specified', 'no description provided') THEN 0
                   WHEN LENGTH(TRIM(j.description)) >= 200 THEN 2
                   WHEN LENGTH(TRIM(j.description)) >= 50 THEN 1
                   ELSE 0
               END AS description_score
        FROM jobs j
        WHERE j.status = ?
    """
    params: list[Any] = [REVIEW_STATUS]

    if canonical_location:
        # Match the canonical region OR "Remote" (Remote is a wildcard that
        # qualifies under every region filter). Rows stored as verbose
        # strings ("Toronto, Ontario, Canada") still match through the
        # user's own region aliases — exact alias or city-prefix — so the
        # editable regions table actually drives filtering.
        if user_id is not None:
            query += """
                AND EXISTS (
                    SELECT 1 FROM job_locations l
                    WHERE l.job_id = j.id
                      AND (
                          LOWER(l.location) IN (?, 'remote')
                          OR EXISTS (
                              SELECT 1
                              FROM user_regions ur
                              JOIN user_location_aliases a ON a.region_id = ur.id
                              WHERE ur.user_id = ?
                                AND LOWER(ur.code) = ?
                                AND (LOWER(l.location) = a.alias
                                     OR LOWER(l.location) LIKE a.alias || ',%')
                          )
                      )
                )
            """
            params.extend([canonical_location.lower(), user_id, canonical_location.lower()])
        else:
            query += """
                AND EXISTS (
                    SELECT 1 FROM job_locations l
                    WHERE l.job_id = j.id AND LOWER(l.location) IN (?, 'remote')
                )
            """
            params.append(canonical_location.lower())

    if canonical_job_type:
        query += " AND j.track = ?"
        params.append(canonical_job_type)

    if enabled_tracks:
        # Removed/disabled-track jobs keep their rows but leave the review
        # queue; unclassified jobs (empty track) always stay swipable.
        placeholders = ", ".join("?" for _ in enabled_tracks)
        query += f" AND (j.track IN ({placeholders}) OR j.track IS NULL OR TRIM(j.track) = '')"
        params.extend(enabled_tracks)

    if exclude_seen and user_id is not None:
        query += """
            AND j.id NOT IN (
                SELECT job_id FROM user_job_state WHERE user_id = ?
            )
        """
        params.append(user_id)

    query += " ORDER BY relevance_score DESC, description_score DESC, j.date_found IS NULL, j.date_found ASC, j.id ASC LIMIT ?"
    params.append(safe_limit)

    with closing(get_connection()) as conn:
        rows = conn.execute(query, params).fetchall()
        return [_job_row_to_dict(row, conn) for row in rows]


def get_review_filter_options(user_id: Optional[int] = None) -> dict[str, Any]:
    """Return filter values for the review-page dropdowns.

    Locations come from the user's enabled regions (user_regions) so the
    dropdown reflects the editable regions table instead of a hardcoded
    set. Falls back to distinct canonical values when the user has no
    regions (e.g. pre-seed accounts).

    Also returns ``track_colors`` ({track name: hex color}) from the user's
    editable tracks so the review page can theme swipe cards with the
    colors chosen in the tracks editor.
    """
    with closing(get_connection()) as conn:
        locations: list[str] = []
        if user_id is not None:
            region_rows = conn.execute(
                """
                SELECT code FROM user_regions
                WHERE user_id = ? AND enabled = 1
                ORDER BY sort_order, code
                """,
                (user_id,),
            ).fetchall()
            locations = [row["code"] for row in region_rows]

        if not locations:
            # Fallback: derive from job_locations (now stores normalized values)
            location_rows = conn.execute(
                """
                SELECT DISTINCT l.location
                FROM job_locations l
                JOIN jobs j ON j.id = l.job_id
                WHERE j.status = ? AND l.location IS NOT NULL AND TRIM(l.location) != ''
                ORDER BY l.location
                """,
                (REVIEW_STATUS,),
            ).fetchall()
            # Dedupe on canonical form AND only keep canonical values
            # (LA / NY / BC / ON). Raw city variants are dropped so the
            # filter dropdown stays small.
            seen_locs: set[str] = set()
            for row in location_rows:
                loc = row["location"]
                canonical = normalize_location(loc)
                if not canonical or canonical not in CANONICAL_LOCATIONS:
                    continue
                if canonical in seen_locs:
                    continue
                seen_locs.add(canonical)
                locations.append(canonical)

        # Tracks are normalized via normalize_track_value
        job_types: list[str] = []
        seen_tracks: set[str] = set()
        enabled_tracks = _enabled_track_names(conn, user_id)
        for row in conn.execute(
            """
            SELECT DISTINCT track
            FROM jobs
            WHERE status = ?
              AND track IS NOT NULL
              AND TRIM(track) != ''
            ORDER BY track
            """,
            (REVIEW_STATUS,),
        ).fetchall():
            norm = normalize_track_value(row["track"])
            if not norm or norm == "not a fit":
                continue
            # A track removed from the editor can't be selected in the scoped
            # review queue, so don't offer it in the dropdown either.
            if enabled_tracks and norm not in enabled_tracks:
                continue
            if norm in seen_tracks:
                continue
            seen_tracks.add(norm)
            job_types.append(norm)

        # Live track colors from the user's editable tracks ({name: color}),
        # so swipe cards use the colors chosen in the tracks editor.
        track_colors: dict[str, str] = {}
        if user_id is not None:
            try:
                for trow in conn.execute(
                    "SELECT name, color FROM user_tracks WHERE user_id = ?",
                    (user_id,),
                ).fetchall():
                    if trow["color"]:
                        track_colors[trow["name"]] = trow["color"]
            except Exception:
                # Pre-migration DB without the color column: fall back to the
                # hardcoded swipe palette instead of 500ing the filter endpoint.
                track_colors = {}

        # The user's enabled editor tracks join the dropdown so a track can
        # always be assigned, even when no queued job currently carries it
        # (e.g. GIS/Spatial once its review-queue jobs move on).
        for name in enabled_tracks:
            if name in seen_tracks:
                continue
            seen_tracks.add(name)
            job_types.append(name)

    return {"locations": locations, "job_types": job_types, "track_colors": track_colors}


def get_job_by_id(job_id: int) -> Optional[dict[str, Any]]:
    """Return a single job record, including locations."""
    with closing(get_connection()) as conn:
        row = conn.execute(
            f"""
            SELECT {_JOB_FIELDS}
            FROM jobs j
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()

        if row is None:
            return None

        return _job_row_to_dict(row, conn)


def _record_job_preference(
    conn: sqlite3.Connection,
    job_id: int,
    preference: str,
    source_status: str,
) -> None:
    """Persist a user preference for a job into the job_preferences table."""
    if preference not in {"liked", "disliked", "superdisliked"}:
        raise ValueError("Preference must be 'liked', 'disliked', or 'superdisliked'")

    job_row = conn.execute(
        """
        SELECT j.title, j.company, j.description, j.source_tab,
               COALESCE(
                   (
                       SELECT GROUP_CONCAT(l.location, ', ')
                       FROM job_locations l
                       WHERE l.job_id = j.id
                   ),
                   ''
               ) AS location
        FROM jobs j
        WHERE j.id = ?
        """,
        (job_id,),
    ).fetchone()

    if job_row is None:
        raise KeyError("Job not found")

    location = str(job_row["location"] or "").strip()
    title = str(job_row["title"] or "").strip()
    company = str(job_row["company"] or "").strip()
    description = str(job_row["description"] or "").strip()

    conn.execute(
        """
        INSERT INTO job_preferences (
            job_id, preference, title, location, description, keywords, source_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, preference, title, location or None, description or None, None, source_status),
    )
    # Mirror into the legacy singular job_preference table: the daemon's
    # preference filtering reads it (title/company matched, values only
    # 'like'/'dislike') and nothing else in the system wrote it, so the
    # daemon never actually saw web-app dislikes. Superdislikes are
    # recorded as 'dislike' — the strongest signal the legacy shape holds.
    legacy_preference = "like" if preference == "liked" else "dislike"
    try:
        conn.execute(
            """
            INSERT INTO job_preference (title, company, preference)
            VALUES (?, ?, ?)
            """,
            (title, company or None, legacy_preference),
        )
    except sqlite3.OperationalError:
        # Legacy table may not exist in local/dev databases; the plural
        # write above is the source of truth for the web app.
        pass
    conn.execute(
        "UPDATE jobs SET preference_added = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (job_id,),
    )


def apply_swipe_action(job_id: int, action: str) -> str:
    """Apply a like/dislike/superdislike/expired/duplicate swipe. Unsure is handled without DB writes.

    'superdislike' means the user dislikes the job AND it is a poor fit for its
    assigned track. It sets the track to 'not a fit', stores preference='superdisliked'
    (a stronger negative signal than 'disliked') with the same job status as a dislike.

    'expired' means the job posting no longer exists or the deadline has passed.
    The status is set to 'Passed' and no preference row is written.

    'duplicate' means this job is a duplicate of another posting. The status is
    set to 'Duplicate' and no preference row is written.
    """
    if action not in ("like", "dislike", "superdislike", "expired", "duplicate"):
        raise ValueError("Action must be 'like', 'dislike', 'superdislike', 'expired', or 'duplicate'")

    if action == "like":
        new_status = READY_STATUS
        preference = "liked"
        new_track = None  # Don't change track on like
    elif action == "superdislike":
        new_status = NOT_INTERESTED_STATUS
        preference = "superdisliked"
        new_track = "not a fit"  # Mark as not a fit for its track
    elif action == "dislike":
        new_status = NOT_INTERESTED_STATUS
        preference = "disliked"
        new_track = None  # Don't change track on regular dislike
    elif action == "expired":
        new_status = PASSED_STATUS
        preference = None
        new_track = None
    else:  # duplicate
        new_status = DUPLICATE_STATUS
        preference = None
        new_track = None

    with closing(get_connection()) as conn:
        # expired also stamps passed_at so it matches mark_expired() semantics.
        passed_clause = ", passed_at = CURRENT_TIMESTAMP" if action == "expired" else ""

        if action == "like":
            cursor = conn.execute(
                f"""
                UPDATE jobs
                SET status = ?, not_interested_checked = 0{passed_clause}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ?
                """,
                (new_status, job_id, REVIEW_STATUS),
            )
        else:
            cursor = conn.execute(
                f"""
                UPDATE jobs
                SET status = ?, not_interested_checked = 1{passed_clause}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ?
                """,
                (new_status, job_id, REVIEW_STATUS),
            )

        if cursor.rowcount == 0:
            current = conn.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()

            if current is None:
                raise KeyError("Job not found")

            raise ValueError(
                f"Job is no longer in the review queue (current status: {current['status']})"
            )

        # Only like/dislike/superdislike persist a preference row; expired and
        # duplicate intentionally write no preference (they keep prior state).
        if preference is not None:
            _record_job_preference(conn, job_id, preference, REVIEW_STATUS)

        # Update track for superdislike
        if new_track is not None:
            conn.execute(
                "UPDATE jobs SET track = ?, is_modified = 1 WHERE id = ?",
                (new_track, job_id),
            )

        conn.commit()

    return new_status


def mark_job_unsure(job_id: int) -> bool:
    """Flag a job as needing more info from the daemon's scraper.

    Sets unsure=1 (status becomes 'Awaiting Response' as a holding state).
    Once the daemon rescrapes the description it clears unsure AND returns
    the job to 'Review to Apply'. Unsure jobs never belong on the
    Notifications page — that page tracks applied jobs only.
    """
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = ?, unsure = 1, not_interested_checked = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = ?
            """,
            (AWAITING_RESPONSE_STATUS, job_id, REVIEW_STATUS),
        )

        if cursor.rowcount == 0:
            current = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if current is None:
                raise KeyError("Job not found")
            raise ValueError(f"Job is no longer in the review queue (current status: {current['status']})")

        conn.commit()

        return True


def set_job_deadline(job_id: int, deadline: Optional[str]) -> None:
    """Set or clear a job's application deadline.

    Routed through the durable pending-write side store so a mid-scrape daemon
    hold can't 500 the request: the write applies immediately when free,
    otherwise it stages (last write wins) and the UI overlays it.
    """
    if not _job_exists(job_id):
        raise KeyError("Job not found")
    if deadline:
        try:
            date.fromisoformat(str(deadline))
        except ValueError as exc:
            raise ValueError("application_deadline must use YYYY-MM-DD format") from exc
    queue_write(
        "UPDATE jobs SET application_deadline = ?, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (deadline or None, job_id),
        table="jobs",
        row_key=str(job_id),
        payload={"application_deadline": deadline or None},
    )


def revert_last_action(job_id: int, action: Optional[str] = None) -> str:
    """Undo the most recent swipe action on a job (Like → Review to Apply).

    Clears the most recent job_preferences row for this job and restores the
    job's status to REVIEW_STATUS so it reappears in the review queue.

    Raises KeyError if the job doesn't exist, ValueError if the most recent
    preference isn't something we can safely revert (expired/duplicate leave no
    preference row — they're terminal-ish, and re-reviewing is the user's call
    via reclassify/restart rather than blind auto-revert).
    """
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT p.id, p.preference, p.source_status, j.title, j.company "
            "FROM job_preferences p JOIN jobs j ON j.id = p.job_id "
            "WHERE p.job_id = ? ORDER BY p.id DESC LIMIT 1",
            (job_id,),
        ).fetchone()

        if row is None:
            current = conn.execute(
                "SELECT status, unsure FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if current is None:
                raise KeyError("Job not found")
            if action == "unsure" and current["status"] == AWAITING_RESPONSE_STATUS and current["unsure"]:
                conn.execute(
                    "UPDATE jobs SET status=?, unsure=0, not_interested_checked=0, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (REVIEW_STATUS, job_id),
                )
                conn.commit()
                return REVIEW_STATUS
            if action == "expired" and current["status"] == PASSED_STATUS:
                conn.execute(
                    "UPDATE jobs SET status=?, unsure=0, passed_at=NULL, not_interested_checked=0, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (REVIEW_STATUS, job_id),
                )
                conn.commit()
                return REVIEW_STATUS
            raise ValueError(
                f"Cannot revert job #{job_id}: no reversible swipe recorded "
                f"(current status: {current['status']})."
            )

        preference = row["preference"]
        if preference not in ("liked", "disliked", "superdisliked"):
            raise ValueError(
                f"Cannot revert: last preference was '{preference}', only liked/disliked/superdisliked are undoable."
            )

        # Remove only the latest canonical signal and its matching legacy
        # daemon signal. Older history must not be erased by a single undo.
        conn.execute("DELETE FROM job_preferences WHERE id = ?", (row["id"],))
        legacy_preference = "like" if preference == "liked" else "dislike"
        try:
            conn.execute(
                """
                DELETE FROM job_preference
                WHERE id = (
                    SELECT id FROM job_preference
                    WHERE title = ? AND COALESCE(company, '') = COALESCE(?, '')
                      AND preference = ?
                    ORDER BY id DESC LIMIT 1
                )
                """,
                (row["title"], row["company"], legacy_preference),
            )
        except sqlite3.OperationalError:
            pass
        has_older = conn.execute(
            "SELECT 1 FROM job_preferences WHERE job_id = ? LIMIT 1", (job_id,)
        ).fetchone() is not None

        # Reset the job to the review queue. Track is NOT restored (the user's
        # reclassification via superdislike is kept — they made a deliberate call).
        conn.execute(
            "UPDATE jobs SET status = ?, unsure = 0, not_interested_checked = 0, "
            "preference_added = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (REVIEW_STATUS, 1 if has_older else 0, job_id),
        )
        conn.commit()

    return REVIEW_STATUS


def mark_job_status(job_id: int, status: str) -> None:
    """Set a job's status directly (does not guard on current status).

    Durable: applies when the main DB is free, otherwise stages in the
    pending-write side store (daemon lock holds can't 500 or lose it).
    """
    if not _job_exists(job_id):
        raise KeyError("Job not found")
    queue_write(
        "UPDATE jobs SET status = ?, not_interested_checked = 1, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, job_id),
        table="jobs",
        row_key=str(job_id),
        payload={"status": status, "not_interested_checked": 1},
    )


def mark_expired(job_id: int) -> str:
    """Mark a job as expired (Passed status). Keeps the like/dislike preference
    but removes it from active views.

    Durable via queue_write. passed_at is stamped from naive UTC (matching
    CURRENT_TIMESTAMP storage) so the staged replay matches the direct path.
    """
    if not _job_exists(job_id):
        raise KeyError("Job not found")
    passed_at = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    queue_write(
        "UPDATE jobs SET status = ?, passed_at = ?, not_interested_checked = 1, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (PASSED_STATUS, passed_at, job_id),
        table="jobs",
        row_key=str(job_id),
        payload={"status": PASSED_STATUS, "passed_at": passed_at, "not_interested_checked": 1},
    )
    return PASSED_STATUS


def reclassify_job_track(job_id: int, new_track: str) -> str:
    """Update the job's track classification to a different value.

    Routed through the durable pending-write side store so a mid-scrape daemon
    hold can't 500 the request: the write applies immediately when free,
    otherwise it stages (last write wins) and the UI overlays it.
    """
    track_value = normalize_track_value(new_track)
    if not track_value:
        raise ValueError("Track cannot be empty")

    if not _job_exists(job_id):
        raise KeyError("Job not found")
    queue_write(
        "UPDATE jobs SET track = ?, is_modified = 1, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (track_value, job_id),
        table="jobs",
        row_key=str(job_id),
        payload={"track": track_value, "is_modified": 1},
    )
    return track_value


def get_ready_to_apply(search: Optional[str] = None) -> list[dict[str, Any]]:
    """Return all jobs eligible for the Application Manager (excludes expired jobs)."""
    search = (search or "").strip()
    params: list[Any] = [READY_STATUS]

    query = f"""
        SELECT {_JOB_FIELDS}
        FROM jobs j
        WHERE j.status = ?
          AND (j.passed_at IS NULL OR j.passed_at = '')
          AND j.archived = 0
    """

    if search:
        like = f"%{search}%"
        query += """
            AND (
                j.title LIKE ?
                OR j.company LIKE ?
                OR EXISTS (
                    SELECT 1 FROM job_locations l
                    WHERE l.job_id = j.id AND l.location LIKE ?
                )
            )
        """
        params.extend([like, like, like])

    query += " ORDER BY j.date_found DESC, j.id DESC"

    with closing(get_connection()) as conn:
        rows = conn.execute(query, params).fetchall()
        return [_job_row_to_dict(row, conn) for row in rows]


def mark_applied(
    job_id: int,
    applied_at: Optional[str] = None,
    submitted_resume: Optional[str] = None,
    submitted_cover_letter: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """Transition a job from Ready to Apply to Awaiting Response.

    Optional fields let the client record what was submitted (resume filename,
    cover letter reference, free-text notes) at the moment of applying.

    Durable: the READY-guarded UPDATE applies when the main DB is free; under
    a daemon lock it stages a fully-resolved payload (the COALESCE logic is
    resolved here in Python so the staged replay matches the direct path).
    """
    with closing(get_connection()) as conn:
        current = conn.execute(
            "SELECT status, applied_at, submitted_resume, submitted_cover_letter, notes "
            "FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

    if current is None:
        raise KeyError("Job not found")
    if current["status"] == AWAITING_RESPONSE_STATUS:
        return AWAITING_RESPONSE_STATUS  # idempotent, same as the old write path
    if current["status"] != READY_STATUS:
        raise ValueError(
            f"Only 'Ready to Apply' jobs can be marked as applied (current status: {current['status']})"
        )

    if applied_at:
        try:
            date.fromisoformat(str(applied_at))
        except ValueError as exc:
            raise ValueError("applied_at must use YYYY-MM-DD format") from exc
    payload = {
        "status": AWAITING_RESPONSE_STATUS,
        "applied_at": applied_at or current["applied_at"] or date.today().isoformat(),
        "submitted_resume": submitted_resume if submitted_resume is not None else current["submitted_resume"],
        "submitted_cover_letter": submitted_cover_letter if submitted_cover_letter is not None else current["submitted_cover_letter"],
        "notes": notes if notes is not None else current["notes"],
    }
    queue_write(
        "UPDATE jobs SET status = ?, applied_at = ?, submitted_resume = ?, "
        "submitted_cover_letter = ?, notes = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND status = ?",
        (
            AWAITING_RESPONSE_STATUS,
            payload["applied_at"],
            payload["submitted_resume"],
            payload["submitted_cover_letter"],
            payload["notes"],
            job_id,
            READY_STATUS,
        ),
        table="jobs",
        row_key=str(job_id),
        payload=payload,
    )
    return AWAITING_RESPONSE_STATUS


def merge_jobs_as_duplicates(job_id: int, other_job_id: int) -> dict[str, Any]:
    """Merge two job records into one, preserving the richer description and locations."""
    if job_id == other_job_id:
        raise ValueError("A job cannot be merged with itself")

    with closing(get_connection()) as conn:
        kept_job = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        other_job = conn.execute("SELECT id FROM jobs WHERE id = ?", (other_job_id,)).fetchone()

        if kept_job is None or other_job is None:
            raise KeyError("One or both jobs were not found")

        result = merge_duplicate_jobs(conn, job_id, other_job_id)
        conn.commit()
        return result


def find_duplicate_candidates(job_id: int, limit: int = 5) -> list[dict[str, Any]]:
    """Find jobs that look like duplicates of the given job by title/company match.

    Returns a list of candidate job dicts (id, title, company, status, relevance_score)
    that share a similar title and company with the given job, excluding the job itself.
    Uses the same title/company normalization as the daemon's find_similar_job.
    """
    from shared_schema import normalize_title_key, normalize_company_name

    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT title, company FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise KeyError("Job not found")

        title_key = normalize_title_key(row["title"] or "")
        company_key = normalize_company_name(row["company"] or "")

        if not title_key and not company_key:
            return []

        candidates = []
        for jrow in conn.execute(
            "SELECT id, title, company, status, relevance_score FROM jobs "
            "WHERE id != ? AND title IS NOT NULL AND company IS NOT NULL",
            (job_id,),
        ).fetchall():
            rk = normalize_title_key(str(jrow["title"]))
            ck = normalize_company_name(str(jrow["company"]))

            t_match = title_key == rk or rk in title_key or title_key in rk
            c_match = company_key == ck or ck in company_key or company_key in ck

            if t_match and c_match:
                candidates.append({
                    "id": int(jrow["id"]),
                    "title": jrow["title"],
                    "company": jrow["company"],
                    "status": jrow["status"],
                    "relevance_score": jrow["relevance_score"],
                })
                if len(candidates) >= limit:
                    break

        return candidates


def create_manual_job(title: str, company: str, link: Optional[str] = None, location: Optional[str] = None) -> dict[str, Any]:
    """Create a manually-entered job and cross-reference existing DB jobs.

    The user often pastes a job they already applied to. We first search for
    a likely duplicate (same company plus a title that shares enough keywords).
    If found the existing job is updated in place (link, date_found, track) so
    nothing is lost; otherwise a fresh row is created and returned.
    """
    title = (title or "").strip()
    company = (company or "").strip()
    if not title or not company:
        raise ValueError("Title and company are required")
    if link:
        parsed = urlparse(link)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Link must be an http(s) URL")

    from shared_schema import normalize_title_key, normalize_company_name

    with closing(get_connection()) as conn:
        norm_title = normalize_title_key(title)
        norm_company = normalize_company_name(company)
        if not norm_title or not norm_company:
            raise ValueError("Title and company are required")

        # Look for a likely duplicate: same company and a title that
        # either matches exactly or shares >= 2 words.
        link_match = conn.execute("SELECT id FROM jobs WHERE link = ?", (link,)).fetchone() if link else None
        existing_id = link_match["id"] if link_match else None
        for row in conn.execute(
            "SELECT id, title, company FROM jobs WHERE title IS NOT NULL AND company IS NOT NULL",
        ).fetchall():
            if existing_id is not None:
                break
            existing_title = str(row["title"] or "").strip()
            existing_company = str(row["company"] or "").strip()
            if not existing_title or not existing_company:
                continue
            if normalize_company_name(existing_company) != norm_company:
                continue
            existing_title_key = normalize_title_key(existing_title)
            word_overlap = len(set(norm_title.split()) & set(existing_title_key.split()))
            if norm_title == existing_title_key or norm_title in existing_title_key or existing_title_key in norm_title or word_overlap >= 2:
                existing_id = row["id"]
                break

        if existing_id is not None:
            # Update the existing row in place — preserve description and
            # any locations already stored for that job.
            conn.execute(
                """
                UPDATE jobs SET link = COALESCE(?, link), date_found = ?,
                                   source = 'manual', is_modified = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (link, date.today().isoformat(), existing_id),
            )
            if location:
                conn.execute(
                    "INSERT OR IGNORE INTO job_locations (job_id, location) VALUES (?, ?)",
                    (existing_id, normalize_location(location)),
                )
            conn.commit()
            return {"job_id": existing_id, "merged": True}

        conn.execute(
            """
            INSERT INTO jobs (
                source_tab, date_found, track, title, company, link, description,
                status, source, is_modified
            ) VALUES (?, ?, NULL, ?, ?, ?, NULL, 'Review to Apply', 'manual', 1)
            """,
            ("manual", date.today().isoformat(), title, company, link),
        )
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        if location:
            conn.execute(
                "INSERT OR IGNORE INTO job_locations (job_id, location) VALUES (?, ?)",
                (new_id, normalize_location(location)),
            )
        conn.commit()
        return {"job_id": new_id, "merged": False}
def get_notification_counts() -> dict[str, int]:
    """Return counts of jobs per notification status for the nav badge and tabs.

    Only counts jobs with status in the tracked notification set and
    unsure=0. Rejected jobs older than 30 days are excluded from the
    Rejected count.
    """
    tracked_statuses = ("Applied", "Awaiting Response", "Responded", "Rejected")
    counts: dict[str, int] = {status: 0 for status in tracked_statuses}

    with closing(get_connection()) as conn:
        placeholders = ", ".join("?" for _ in tracked_statuses)
        rows = conn.execute(
            f"""
            SELECT status, COUNT(*) as cnt
            FROM jobs
            WHERE status IN ({placeholders})
              AND COALESCE(unsure, 0) = 0
              AND (
                  status != 'Rejected'
                  OR ((updated_at IS NULL OR updated_at >= datetime('now', '-30 days'))
                      AND (email_received_at IS NULL OR email_received_at >= datetime('now', '-30 days')))
              )
            GROUP BY status
            """,
            tracked_statuses,
        ).fetchall()

    for row in rows:
        counts[row["status"]] = row["cnt"]

    return counts


def search_jobs(q: str, exclude_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Search jobs by title/company for finding duplicate candidates."""
    with closing(get_connection()) as conn:
        extra = "" if exclude_id is None else " AND id != ?"
        extra_params: list[Any] = [] if exclude_id is None else [exclude_id]
        rows = conn.execute(
            f"""
            SELECT id, title, company, source_tab, status
            FROM jobs
            WHERE (title LIKE ? OR company LIKE ?)
            {extra}
            ORDER BY updated_at DESC
            LIMIT 20
            """,
            [f"%{q}%", f"%{q}%"] + extra_params,
        ).fetchall()

    return [dict(row) for row in rows]


# ── Notes ────────────────────────────────────────────────────────────────────────


def save_job_notes(job_id: int, notes: str) -> None:
    """Save free-text notes. Durable via queue_write (stages under daemon lock)."""
    if not _job_exists(job_id):
        raise KeyError("Job not found")
    queue_write(
        "UPDATE jobs SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (notes, job_id),
        table="jobs",
        row_key=str(job_id),
        payload={"notes": notes},
    )


def get_job_notes(job_id: int) -> str:
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT notes FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise KeyError("Job not found")
        return row["notes"] or ""


# ── Archive ──────────────────────────────────────────────────────────────────────


def set_job_archived(job_id: int, archived: bool = True) -> bool:
    """Toggle a job's archived flag.

    Writes durably: applies to the main DB when it's free, otherwise stages
    the write in the pending-write side store (survives web-app restarts; the
    daemon and the web flusher drain it). Returns True if the write was
    staged (deferred), False if it applied immediately — reads overlay staged
    values either way, so the UI always reflects the latest intent.
    """
    if not _job_exists(job_id):
        raise KeyError("Job not found")
    return queue_write(
        "UPDATE jobs SET archived = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (1 if archived else 0, job_id),
        table="jobs",
        row_key=str(job_id),
        payload={"archived": 1 if archived else 0},
    )


# ── Interview prep ────────────────────────────────────────────────────────────────


def get_upcoming_interviews(user_id: int) -> list[dict[str, Any]]:
    """Return all non-past interview prep entries for the user."""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT ip.*, j.title as job_title, j.company as job_company
            FROM interview_prep ip
            LEFT JOIN jobs j ON j.id = ip.job_id
            WHERE ip.user_id = ?
              AND ip.interview_date IS NOT NULL
              AND date(ip.interview_date) >= date('now')
            ORDER BY ip.interview_date ASC
            """,
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_interview_prep(user_id: int, interview_id: int) -> None:
    """Delete an interview prep entry owned by the user."""
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT id FROM interview_prep WHERE id = ? AND user_id = ?",
            (interview_id, user_id),
        ).fetchone()
        if row is None:
            raise KeyError("Interview not found")
        conn.execute("DELETE FROM interview_prep WHERE id = ?", (interview_id,))
        conn.commit()


def save_interview_prep(
    user_id: int,
    company: str,
    role: str,
    interview_id: Optional[int] = None,
    job_id: Optional[int] = None,
    interview_date: Optional[str] = None,
    prep_notes: Optional[str] = None,
    questions: Optional[str] = None,
    follow_up_at: Optional[str] = None,
) -> dict[str, Any]:
    company = str(company or "").strip()
    role = str(role or "").strip()
    if not company or not role:
        raise ValueError("Company and role are required")
    for field_name, value in (("interview_date", interview_date), ("follow_up_at", follow_up_at)):
        if value:
            try:
                date.fromisoformat(str(value)[:10])
            except ValueError as exc:
                raise ValueError(f"{field_name} must use an ISO date") from exc
    with closing(get_connection()) as conn:
        existing = None
        if interview_id is not None:
            existing = conn.execute(
                "SELECT id FROM interview_prep WHERE id = ? AND user_id = ?",
                (interview_id, user_id),
            ).fetchone()
            if existing is None:
                raise KeyError("Interview not found")
        elif job_id is not None:
            existing = conn.execute(
                "SELECT id FROM interview_prep WHERE user_id = ? AND job_id IS ?",
                (user_id, job_id),
            ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE interview_prep
                SET company=?, role=?, interview_date=?, prep_notes=?, questions_to_ask=?, follow_up_at=?, updated_at=CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (company, role, interview_date, prep_notes, questions, follow_up_at, existing["id"]),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM interview_prep WHERE id = ?", (existing["id"],)
            ).fetchone()
            return dict(row)
        else:
            conn.execute(
                """
                INSERT INTO interview_prep
                    (user_id, job_id, company, role, interview_date, prep_notes, questions_to_ask, follow_up_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, job_id, company, role, interview_date, prep_notes, questions, follow_up_at),
            )
            conn.commit()
            last = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            row = conn.execute("SELECT * FROM interview_prep WHERE id = ?", (last,)).fetchone()
            return dict(row)


# ── Contacts ─────────────────────────────────────────────────────────────────────


def get_contacts(user_id: int) -> list[dict[str, Any]]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_contact(
    user_id: int,
    name: str,
    company: Optional[str] = None,
    role: Optional[str] = None,
    email: Optional[str] = None,
    linkedin: Optional[str] = None,
    notes: Optional[str] = None,
    warmth: int = 1,
) -> dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Contact name is required")
    try:
        warmth = int(warmth)
    except (TypeError, ValueError) as exc:
        raise ValueError("Warmth must be 1, 2, or 3") from exc
    if warmth not in {1, 2, 3}:
        raise ValueError("Warmth must be 1, 2, or 3")
    if linkedin:
        parsed = urlparse(str(linkedin).strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("LinkedIn URL must be an http(s) URL")
    with closing(get_connection()) as conn:
        conn.execute(
            """
            INSERT INTO contacts (user_id, name, company, role, email, linkedin_url, notes, warmth)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, name, company, role, email, linkedin, notes, warmth),
        )
        conn.commit()
        last = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = conn.execute("SELECT * FROM contacts WHERE id = ?", (last,)).fetchone()
        return dict(row)


def update_contact(user_id: int, contact_id: int, data: dict) -> dict[str, Any]:
    if "name" in data and not str(data["name"] or "").strip():
        raise ValueError("Contact name is required")
    if "warmth" in data:
        try:
            data["warmth"] = int(data["warmth"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Warmth must be 1, 2, or 3") from exc
        if data["warmth"] not in {1, 2, 3}:
            raise ValueError("Warmth must be 1, 2, or 3")
    if data.get("linkedin_url"):
        parsed = urlparse(str(data["linkedin_url"]).strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("LinkedIn URL must be an http(s) URL")
    with closing(get_connection()) as conn:
        existing = conn.execute(
            "SELECT id FROM contacts WHERE id = ? AND user_id = ?",
            (contact_id, user_id),
        ).fetchone()
        if not existing:
            raise KeyError("Contact not found")

        fields = []
        vals = []
        for col in ("name", "company", "role", "email", "linkedin_url", "notes", "warmth",
                    "last_contacted_at", "next_follow_up_at"):
            if col in data:
                fields.append(f"{col} = ?")
                vals.append(data[col])
        if not fields:
            raise ValueError("No fields to update")
        fields.append("updated_at = CURRENT_TIMESTAMP")
        vals.append(contact_id)
        conn.execute(f"UPDATE contacts SET {', '.join(fields)} WHERE id = ?", vals)
        conn.commit()
        row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        return dict(row)


def delete_contact(user_id: int, contact_id: int) -> None:
    """Delete a contact owned by the user."""
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT id FROM contacts WHERE id = ? AND user_id = ?",
            (contact_id, user_id),
        ).fetchone()
        if row is None:
            raise KeyError("Contact not found")
        conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        conn.commit()
