"""HTTP API. This is the only interface the frontend talks to."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from services import job_service

api = Blueprint("api", __name__, url_prefix="/api")


@api.get("/review/queue")
def review_queue():
    limit = request.args.get("limit", default=9999, type=int)
    location = request.args.get("location") or request.args.get("source_tab") or ""
    job_type = request.args.get("job_type") or request.args.get("track") or ""
    jobs = job_service.get_review_queue(limit, location=location, job_type=job_type)
    return jsonify({"jobs": jobs, "count": len(jobs)})


@api.get("/review/filter-options")
def review_filter_options():
    return jsonify(job_service.get_review_filter_options())


@api.post("/jobs/<int:job_id>/swipe")
def swipe_job(job_id: int):
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    print(data)

    if action not in {"like", "dislike", "unsure"}:
        return jsonify({"error": "Invalid action. Use 'like', 'dislike', or 'unsure'."}), 400

    if action == "unsure":
        try:
            job_service.mark_job_unsure(job_id)
        except KeyError:
            return jsonify({"error": "Job not found"}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"ok": True, "job_id": job_id, "status": job_service.REVIEW_STATUS})

    try:
        new_status = job_service.apply_swipe_action(job_id, action)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409

    return jsonify({"ok": True, "job_id": job_id, "status": new_status})


@api.post("/jobs/<int:job_id>/reclassify")
def reclassify_job(job_id: int):
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
    q = request.args.get("q", "").strip()
    jobs = job_service.get_ready_to_apply(q or None)
    print("hi" , jobs)
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