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


def get_review_queue(limit: int = 100) -> list[dict[str, Any]]:
    """Return jobs still waiting in the raw review queue."""
    safe_limit = max(1, min(int(limit), 500))

    with closing(get_connection()) as conn:
        rows = conn.execute(
            f"""
            SELECT {_JOB_FIELDS}
            FROM jobs j
            WHERE j.status = ?
            ORDER BY j.date_found IS NULL, j.date_found ASC, j.id ASC
            LIMIT ?
            """,
            (REVIEW_STATUS, safe_limit),
        ).fetchall()

        return [_job_row_to_dict(row, conn) for row in rows]


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