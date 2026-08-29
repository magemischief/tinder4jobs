"""HTTP API. This is the only interface the frontend talks to."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from services import job_service

api = Blueprint("api", __name__, url_prefix="/api")


@api.get("/review/queue")
def review_queue():
    limit = request.args.get("limit", default=100, type=int)
    jobs = job_service.get_review_queue(limit)
    return jsonify({"jobs": jobs, "count": len(jobs)})


@api.post("/jobs/<int:job_id>/swipe")
def swipe_job(job_id: int):
    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if action not in {"like", "dislike", "unsure"}:
        return jsonify({"error": "Invalid action. Use 'like', 'dislike', or 'unsure'."}), 400

    # Unsure intentionally does not change the database.
    if action == "unsure":
        job = job_service.get_job_by_id(job_id)
        if job is None:
            return jsonify({"error": "Job not found"}), 404
        return jsonify({"ok": True, "status": job["status"]})

    try:
        new_status = job_service.apply_swipe_action(job_id, action)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    return jsonify({"ok": True, "job_id": job_id, "status": new_status})


@api.get("/applications")
def applications():
    q = request.args.get("q", "").strip()
    jobs = job_service.get_ready_to_apply(q or None)
    return jsonify({"jobs": jobs, "count": len(jobs)})


@api.post("/jobs/<int:job_id>/apply")
def mark_applied(job_id: int):
    try:
        status = job_service.mark_applied(job_id)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    return jsonify({"ok": True, "job_id": job_id, "status": status})


@api.get("/notifications")
def notifications():
    jobs = job_service.get_notifications()
    return jsonify({"jobs": jobs, "count": len(jobs)})