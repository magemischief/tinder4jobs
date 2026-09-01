"""Service functions used by API routes and pipeline scripts."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any, Optional

from database import get_connection

REVIEW_STATUS = "Review to Apply"
READY_STATUS = "Ready to Apply"
APPLIED_STATUS = "Applied"
NOT_INTERESTED_STATUS = "Not Interested"
AWAITING_RESPONSE_STATUS = "Awaiting Response"

_JOB_FIELDS = """
    j.id, j.source_tab, j.source_row, j.date_found, j.track, j.title,
    j.company, j.salary, j.link, j.description, j.status, j.interview_date,
    j.follow_up_sent, j.salary_offered, j.created_at, j.updated_at
""".strip()


def _job_row_to_dict(row: sqlite3.Row, conn: sqlite3.Connection) -> dict[str, Any]:
    job = dict(row)
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


def get_review_queue(
    limit: int = 100,
    location: Optional[str] = None,
    job_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return jobs still waiting in the raw review queue, prioritizing real descriptions."""
    safe_limit = max(1, min(int(limit), 500))
    location = (location or "").strip()
    job_type = (job_type or "").strip()

    query = f"""
        SELECT {_JOB_FIELDS},
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

    if location:
        query += " AND j.source_tab = ?"
        params.append(location)

    if job_type:
        query += " AND j.track = ?"
        params.append(job_type)

    query += " ORDER BY description_score DESC, j.date_found IS NULL, j.date_found ASC, j.id ASC LIMIT ?"
    params.append(safe_limit)

    with closing(get_connection()) as conn:
        rows = conn.execute(query, params).fetchall()
        return [_job_row_to_dict(row, conn) for row in rows]


def get_review_filter_options() -> dict[str, list[str]]:
    """Return distinct values for the review-page filters."""
    with closing(get_connection()) as conn:
        locations = [
            row["source_tab"]
            for row in conn.execute(
                """
                SELECT DISTINCT source_tab
                FROM jobs
                WHERE status = ? AND source_tab IS NOT NULL AND TRIM(source_tab) != ''
                ORDER BY source_tab
                """,
                (REVIEW_STATUS,),
            ).fetchall()
        ]
        job_types = [
            row["track"]
            for row in conn.execute(
                """
                SELECT DISTINCT track
                FROM jobs
                WHERE status = ? AND track IS NOT NULL AND TRIM(track) != ''
                ORDER BY track
                """,
                (REVIEW_STATUS,),
            ).fetchall()
        ]

    return {"locations": locations, "job_types": job_types}


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


def apply_swipe_action(job_id: int, action: str) -> str:
    """Apply a like/dislike swipe. Unsure is handled without DB writes."""
    if action not in ("like", "dislike"):
        raise ValueError("Action must be 'like' or 'dislike'")

    new_status = READY_STATUS if action == "like" else NOT_INTERESTED_STATUS

    with closing(get_connection()) as conn:
        if action == "dislike":
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = ?, not_interested_checked = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = ?
                """,
                (new_status, job_id, REVIEW_STATUS),
            )
        else:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = ?, not_interested_checked = 0, updated_at = CURRENT_TIMESTAMP
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

        conn.commit()

    return new_status


def mark_job_unsure(job_id: int) -> bool:
    """Remove the current item from review by marking it unsure."""
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = ?, unsure = 1, not_interested_checked = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = ?
            """,
            (NOT_INTERESTED_STATUS, job_id, REVIEW_STATUS),
        )

        if cursor.rowcount == 0:
            current = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if current is None:
                raise KeyError("Job not found")
            raise ValueError(f"Job is no longer in the review queue (current status: {current['status']})")

        conn.commit()

    return True


def reclassify_job_track(job_id: int, new_track: str) -> str:
    """Update the job's track classification to a different value."""
    track_value = (new_track or "").strip()
    if not track_value:
        raise ValueError("Track cannot be empty")

    with closing(get_connection()) as conn:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET track = ?, is_modified = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (track_value, job_id),
        )

        if cursor.rowcount == 0:
            raise KeyError("Job not found")

        conn.commit()

    return track_value


def get_ready_to_apply(search: Optional[str] = None) -> list[dict[str, Any]]:
    """Return all jobs eligible for the Application Manager."""
    search = (search or "").strip()
    params: list[Any] = [READY_STATUS]

    query = f"""
        SELECT {_JOB_FIELDS}
        FROM jobs j
        WHERE j.status = ?
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


def mark_applied(job_id: int) -> str:
    """Transition a job from Ready to Apply to Applied."""
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = ?
            """,
            (APPLIED_STATUS, job_id, READY_STATUS),
        )

        if cursor.rowcount == 0:
            current = conn.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()

            if current is None:
                raise KeyError("Job not found")

            if current["status"] == APPLIED_STATUS:
                return APPLIED_STATUS

            raise ValueError(
                f"Only 'Ready to Apply' jobs can be marked Applied (current status: {current['status']})"
            )

        conn.commit()

    return APPLIED_STATUS


def get_notifications() -> list[dict[str, Any]]:
    """Return jobs currently flagged as Awaiting Response."""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT id, source_tab, title, company, link, status,
                   interview_date, follow_up_sent, updated_at
            FROM jobs
            WHERE status = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (AWAITING_RESPONSE_STATUS,),
        ).fetchall()

        return [dict(row) for row in rows]