"""HTTP API. This is the only interface the frontend talks to."""

from __future__ import annotations

import logging
import os
import queue
import time
import json
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

from services import job_service
from services import user_service
from badge_events import BadgeEventBroker

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")
_badge_broker = BadgeEventBroker()


def _get_user():
    """Return the logged-in user or None."""
    return user_service.get_logged_in_user(request)


def _require_user():
    user = _get_user()
    if user is None:
        return None, (jsonify({"error": "Not logged in"}), 401)
    return user, None


def _record_and_badge(user_id, action_type, job_id=None, *, mark_state=True):
    """Record an action stat, run badge checks, and award lottery tickets.
    Returns (newly_awarded, points_earned, tickets_earned)."""
    # The badge engine (user_session_stats.job_score) scores on a 0-100 scale,
    # but jobs.relevance_score is the daemon's 1-10 rating (shown as "X/10" in
    # the UI). Convert so thresholds like job_score >= 90 can actually fire;
    # unscored jobs stay NULL and simply don't count toward score badges.
    job_score = job_service.get_relevance_score(job_id) if job_id else None
    if job_score is not None:
        job_score = job_score * 10
    points_earned = user_service.record_action(user_id, action_type, job_id=job_id, job_score=job_score)
    if job_id and mark_state:
        user_service.mark_job_seen(user_id, job_id, action_type, score=job_score)
    newly_awarded = user_service.check_and_award_badges(user_id)
    tickets_earned = user_service.LotterySystem.award_on_action(user_id, action_type, job_id)
    # Broadcast newly-awarded badges to every open tab for this user.
    for badge in newly_awarded:
        _badge_broker.publish(user_id, badge)
    return newly_awarded, points_earned, tickets_earned


@api.get("/review/queue")
def review_queue():
    user, error = _require_user()
    if error:
        return error

    limit = request.args.get("limit", default=9999, type=int)
    location = request.args.get("location") or request.args.get("source_tab") or ""
    job_type = request.args.get("job_type") or request.args.get("track") or ""
    prefs = user_service.get_user_preferences(user["id"])
    jobs = job_service.get_review_queue(
        limit,
        location=location,
        job_type=job_type,
        user_id=user["id"],
        exclude_seen=bool(prefs.get("exclude_already_seen")),
    )
    return jsonify({"jobs": jobs, "count": len(jobs)})


@api.get("/review/filter-options")
def review_filter_options():
    user, error = _require_user()
    if error:
        return error
    return jsonify(job_service.get_review_filter_options(user["id"]))


@api.post("/jobs/<int:job_id>/swipe")
def swipe_job(job_id: int):
    user, error = _require_user()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if action not in {"like", "dislike", "superdislike", "unsure", "expired"}:
        return jsonify({"error": "Invalid action. Use 'like', 'dislike', 'superdislike', 'unsure', or 'expired'."}), 400

    if action == "unsure":
        try:
            job_service.mark_job_unsure(job_id)
        except KeyError:
            return jsonify({"error": "Job not found"}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409
        newly_awarded, points_earned, tickets_earned = _record_and_badge(user["id"], "unsure", job_id)
        return jsonify({
            "ok": True,
            "job_id": job_id,
            "status": job_service.AWAITING_RESPONSE_STATUS,
            "new_badges": newly_awarded,
            "tickets_earned": tickets_earned,
        })

    try:
        new_status = job_service.apply_swipe_action(job_id, action)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    # Superdislike counts as a dislike for session stats/badges — the badge
    # engine's action set has no 'superdislike'.
    newly_awarded, points_earned, tickets_earned = _record_and_badge(
        user["id"], "dislike" if action == "superdislike" else action, job_id
    )
    return jsonify({
        "ok": True,
        "job_id": job_id,
        "status": new_status,
        "new_badges": newly_awarded,
        "tickets_earned": tickets_earned,
    })


@api.post("/jobs/<int:job_id>/reclassify")
def reclassify_job(job_id: int):
    user, error = _require_user()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    track = (data.get("track") or "").strip()

    if not track:
        return jsonify({"error": "Track is required"}), 400

    try:
        new_track = job_service.reclassify_job_track(job_id, track)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    return jsonify({"ok": True, "job_id": job_id, "track": new_track})


@api.get("/applications")
def applications():
    user, error = _require_user()
    if error:
        return error

    q = request.args.get("q", "").strip()
    jobs = job_service.get_ready_to_apply(q or None)
    return jsonify({"jobs": jobs, "count": len(jobs)})


@api.post("/jobs/<int:job_id>/apply")
def mark_applied(job_id: int):
    user, error = _require_user()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    try:
        status = job_service.mark_applied(
            job_id,
            applied_at=data.get("applied_at"),
            submitted_resume=data.get("submitted_resume"),
            submitted_cover_letter=data.get("submitted_cover_letter"),
            notes=data.get("notes"),
        )
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    newly_awarded, points_earned, tickets_earned = _record_and_badge(user["id"], "apply", job_id)
    return jsonify(
        {"ok": True, "job_id": job_id, "status": status, "new_badges": newly_awarded, "points_earned": points_earned, "tickets_earned": tickets_earned}
    )


@api.post("/jobs/<int:job_id>/revert")
def revert_job(job_id: int):
    """Undo the most recent swipe action on a job (Like -> Review to Apply).
    Returns the restored status so the UI can pop the card back.

    Why: a misclick in the swipe flow (accidental dislike/like/expired) used
    to permanently move a job with no recovery. This lets the client undo.
    """
    user, error = _require_user()
    if error:
        return error

    try:
        action = (request.get_json(silent=True) or {}).get("action")
        if action == "superdislike":
            action = "dislike"
        if action not in {None, "like", "dislike", "unsure", "expired"}:
            return jsonify({"error": "Invalid action to undo"}), 400
        restored_status = job_service.revert_last_action(job_id, action)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    user_service.undo_recorded_action(user["id"], job_id, action)
    return jsonify({"ok": True, "job_id": job_id, "status": restored_status})


@api.post("/jobs/<int:job_id>/expired")
def mark_expired(job_id: int):
    """Mark a job as expired. Keeps the like/dislike preference but sets passed_at
    and removes it from active views (applications list, review queue)."""
    user, error = _require_user()
    if error:
        return error

    try:
        status = job_service.mark_expired(job_id)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    newly_awarded, points_earned, tickets_earned = _record_and_badge(
        user["id"], "expired", job_id
    )
    return jsonify({
        "ok": True,
        "job_id": job_id,
        "status": status,
        "new_badges": newly_awarded,
        "points_earned": points_earned,
        "tickets_earned": tickets_earned,
    })


@api.post("/jobs/<int:job_id>/merge")
def merge_jobs(job_id: int):
    user, error = _require_user()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    other_job_id = data.get("other_job_id")
    if other_job_id is None:
        return jsonify({"error": "other_job_id is required"}), 400

    try:
        result = job_service.merge_jobs_as_duplicates(job_id, int(other_job_id))
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    return jsonify({"ok": True, "result": result})


@api.post("/jobs/<int:job_id>/duplicate")
def mark_duplicate(job_id: int):
    """Mark a job as a duplicate. With `other_job_id`, also merge into that job.
    Without, just sets status='Duplicate' so it leaves the review queue immediately."""
    user, error = _require_user()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    other_job_id = data.get("other_job_id")

    try:
        if other_job_id is not None:
            # Proper merge: keep other_job_id, discard job_id
            result = job_service.merge_jobs_as_duplicates(int(other_job_id), job_id)
        else:
            # Simple path: just mark as duplicate, daemon reconciles later
            job_service.mark_job_status(job_id, job_service.DUPLICATE_STATUS)
            result = {"kept_job_id": job_id, "merged": False}
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    stats_job_id = result["kept_job_id"] if result.get("merged") else job_id
    newly_awarded, points_earned, tickets_earned = _record_and_badge(
        user["id"], "duplicate", stats_job_id, mark_state=not result.get("merged")
    )
    return jsonify({
        "ok": True,
        "result": result,
        "new_badges": newly_awarded,
        "points_earned": points_earned,
        "tickets_earned": tickets_earned,
    })


@api.get("/jobs/<int:job_id>/duplicate-candidates")
def duplicate_candidates(job_id: int):
    """Return jobs that look like duplicates of the given job (title+company match)."""
    user, error = _require_user()
    if error:
        return error
    try:
        candidates = job_service.find_duplicate_candidates(job_id, limit=5)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"candidates": candidates, "count": len(candidates)})


@api.get("/notifications")
def notifications():
    user, error = _require_user()
    if error:
        return error
    jobs = job_service.get_notifications()
    counts = job_service.get_notification_counts()
    return jsonify({"jobs": jobs, "count": counts.get("Awaiting Response", 0), "counts": counts})


@api.post("/jobs/manual")
def create_manual_job():
    """Create a manually-entered job. Cross-references existing jobs by
    company + title keywords; if a likely duplicate is found the existing
    job is updated in place (link, date_found) rather than creating a dupe.
    """
    user, error = _require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    company = (data.get("company") or "").strip()
    link = (data.get("link") or "").strip() or None
    location = (data.get("location") or "").strip() or None
    try:
        result = job_service.create_manual_job(title, company, link, location)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("Failed to create manual job")
        return jsonify({"error": "Could not create job"}), 500
    return jsonify({"ok": True, "job_id": result["job_id"], "merged": result["merged"]})


@api.get("/jobs/search")
def search_jobs():
    """Return jobs matching a search query — used to find duplicate candidates."""
    user, error = _require_user()
    if error:
        return error
    q = (request.args.get("q") or "").strip()
    exclude_id = request.args.get("exclude_id", type=int)
    if not q:
        return jsonify({"jobs": [], "count": 0})

    jobs = job_service.search_jobs(q=q, exclude_id=exclude_id)
    return jsonify({"jobs": jobs, "count": len(jobs)})


# ── Job notes ────────────────────────────────────────────────────────────────────

@api.get("/jobs/<int:job_id>/notes")
def get_job_notes(job_id: int):
    user, error = _require_user()
    if error:
        return error
    try:
        notes = job_service.get_job_notes(job_id)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"notes": notes})


@api.post("/jobs/<int:job_id>/notes")
def save_job_notes(job_id: int):
    user, error = _require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        result = job_service.save_job_notes(job_id, data.get("notes", ""))
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"ok": True, "notes": result})


# ── Archive ───────────────────────────────────────────────────────────────────────

@api.post("/jobs/<int:job_id>/archive")
def archive_job(job_id: int):
    user, error = _require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    archived = data.get("archived", True)
    try:
        staged = job_service.set_job_archived(job_id, archived)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    except Exception:
        logger.exception("Failed to archive job %s", job_id)
        return jsonify({"error": "Could not archive job"}), 500
    return jsonify({"ok": True, "archived": archived, "queued": bool(staged)})


@api.post("/jobs/<int:job_id>/deadline")
def set_job_deadline(job_id: int):
    user, error = _require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        job_service.set_job_deadline(job_id, data.get("application_deadline"))
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


# ── Interviews ───────────────────────────────────────────────────────────────────

@api.get("/interviews")
def list_interviews():
    user, error = _require_user()
    if error:
        return error
    interviews = job_service.get_upcoming_interviews(user["id"])
    return jsonify({"interviews": interviews})


@api.post("/interviews")
def save_interview():
    user, error = _require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        result = job_service.save_interview_prep(
            user_id=user["id"],
            company=data.get("company", ""),
            role=data.get("role", ""),
            interview_id=data.get("interview_id"),
            job_id=data.get("job_id"),
            interview_date=data.get("interview_date"),
            prep_notes=data.get("prep_notes"),
            questions=data.get("questions_to_ask", data.get("questions")),
            follow_up_at=data.get("follow_up_at"),
        )
    except KeyError:
        return jsonify({"error": "Interview not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "interview": result})


@api.delete("/interviews/<int:interview_id>")
def delete_interview(interview_id: int):
    user, error = _require_user()
    if error:
        return error
    try:
        job_service.delete_interview_prep(user["id"], interview_id)
    except KeyError:
        return jsonify({"error": "Interview not found"}), 404
    return jsonify({"ok": True})


# ── Contacts ─────────────────────────────────────────────────────────────────────

@api.get("/contacts")
def list_contacts():
    user, error = _require_user()
    if error:
        return error
    contacts = job_service.get_contacts(user["id"])
    return jsonify({"contacts": contacts})


@api.post("/contacts")
def create_contact():
    user, error = _require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        contact = job_service.create_contact(
            user_id=user["id"],
            name=data.get("name", ""),
            company=data.get("company"),
            role=data.get("role"),
            email=data.get("email"),
            linkedin=data.get("linkedin"),
            notes=data.get("notes"),
            warmth=data.get("warmth", 1),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "contact": contact}), 201


@api.put("/contacts/<int:contact_id>")
def update_contact(contact_id: int):
    user, error = _require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    if "linkedin" in data and "linkedin_url" not in data:
        data["linkedin_url"] = data.pop("linkedin")
    try:
        contact = job_service.update_contact(user["id"], contact_id, data)
    except KeyError:
        return jsonify({"error": "Contact not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "contact": contact})


@api.delete("/contacts/<int:contact_id>")
def delete_contact(contact_id: int):
    user, error = _require_user()
    if error:
        return error
    try:
        job_service.delete_contact(user["id"], contact_id)
    except KeyError:
        return jsonify({"error": "Contact not found"}), 404
    return jsonify({"ok": True})


# ── Streak ───────────────────────────────────────────────────────────────────────

@api.get("/streak")
def get_streak_info():
    user, error = _require_user()
    if error:
        return error
    streak = user_service.get_streak(user["id"])
    freezes = user_service.get_streak_freezes(user["id"])
    return jsonify({"streak": streak, "freezes": freezes})


@api.post("/streak/freeze")
def use_streak_freeze():
    user, error = _require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    date_str = data.get("date")
    if not date_str:
        return jsonify({"error": "date is required (YYYY-MM-DD)"}), 400
    try:
        ok, msg = user_service.use_streak_freeze(user["id"], date_str)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": ok, "message": msg})


# ── Skills ───────────────────────────────────────────────────────────────────────

@api.get("/skills")
def list_skills():
    user, error = _require_user()
    if error:
        return error
    skills = user_service.get_user_skills(user["id"])
    return jsonify({"skills": skills})


@api.post("/skills")
def upsert_skill():
    user, error = _require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    skill = data.get("skill", "").strip()
    if not skill:
        return jsonify({"error": "skill name is required"}), 400
    try:
        result = user_service.upsert_skill_assessment(
            user_id=user["id"],
            skill=skill,
            self_rating=data.get("self_rating", 3),
            notes=data.get("notes"),
            original_skill=data.get("original_skill"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "skill": result})


@api.delete("/skills/<path:skill_name>")
def delete_skill(skill_name: str):
    user, error = _require_user()
    if error:
        return error
    try:
        user_service.delete_skill_assessment(user["id"], skill_name)
    except KeyError:
        return jsonify({"error": "Skill not found"}), 404
    return jsonify({"ok": True})


# ── Cover letters ───────────────────────────────────────────────────────────────

@api.get("/cover-letters")
def list_cover_letters():
    user, error = _require_user()
    if error:
        return error
    letters = user_service.get_cover_letters(user["id"])
    return jsonify({"cover_letters": letters})


@api.delete("/cover-letters/<int:letter_id>")
def delete_cover_letter(letter_id: int):
    user, error = _require_user()
    if error:
        return error
    try:
        user_service.delete_cover_letter(user["id"], letter_id)
    except KeyError:
        return jsonify({"error": "Cover letter not found"}), 404
    return jsonify({"ok": True})


@api.post("/cover-letters")
def create_cover_letter():
    user, error = _require_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    body = data.get("body", "").strip()
    if not title or not body:
        return jsonify({"error": "title and body are required"}), 400
    try:
        letter = user_service.create_cover_letter(
            user_id=user["id"],
            title=title,
            body=body,
            job_id=data.get("job_id"),
        )
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"ok": True, "cover_letter": letter}), 201


# ── Analytics ─────────────────────────────────────────────────────────────────────

@api.get("/analytics")
def get_analytics():
    user, error = _require_user()
    if error:
        return error
    summary = user_service.get_analytics_summary(user["id"])
    return jsonify(summary)


# ── Profile (used by nav.js) ────────────────────────────────────────────────────

@api.get("/auth/profile")
def auth_profile():
    user, error = _require_user()
    if error:
        return error
    profile = user_service.get_profile_stats(user["id"])
    badges = user_service.get_user_badges(user["id"])
    return jsonify({"profile": profile, "badges": badges})


@api.get("/auth/profile/badges")
def auth_profile_badges():
    user, error = _require_user()
    if error:
        return error
    badges = user_service.get_all_badges_for_user(user["id"])
    # Return badge data directly (not wrapped) so callers can access
    # data.earned / data.locked / data.total. The previous wrapper caused
    # "data.earned is undefined" errors in badges.js.
    return jsonify(badges)

# ── SSE live badge feed (real-time badge notifications) ────────────────────────────

@api.get("/badges/live")
def badges_live():
    """SSE endpoint: streams badge-earned events to the connected client.

    Uses a generator that yields events only for the authenticated user.
    Flask keeps the connection open; generator blocks on queue.get() until
    an event arrives or the client disconnects (GeneratorExit).
    """
    user, error = _require_user()
    if error:
        return error
    user_id = user["id"]

    def event_stream():
        subscriber = _badge_broker.subscribe(user_id)
        try:
            while True:
                try:
                    badge = subscriber.get(timeout=30)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                payload = json.dumps(badge, ensure_ascii=False)
                yield f"event: badge-earned\ndata: {payload}\n\n"
        except GeneratorExit:
            pass
        finally:
            _badge_broker.unsubscribe(user_id, subscriber)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )
