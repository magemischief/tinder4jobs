"""Auth API — login, logout, me, profile endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, make_response

from services import user_service

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def require_login():
    """Return the logged-in user, or abort with 401."""
    user = user_service.get_logged_in_user(request)
    if user is None:
        return None, jsonify({"error": "Not logged in"}), 401
    return user, None, None


@auth_bp.get("/me")
def me():
    """Return the current user, or 401 if not logged in."""
    user, error, status = require_login()
    if error:
        return error, status
    prefs = user_service.get_user_preferences(user["id"])
    user_service.seed_default_regions(user["id"])
    user_service.seed_default_tracks(user["id"])
    regions = user_service.get_user_regions(user["id"])
    tracks = user_service.get_user_tracks(user["id"])
    return jsonify({
        "user": user,
        "preferences": prefs,
        "regions": regions,
        "tracks": tracks,
    })


@auth_bp.post("/login")
def login():
    """Log in / register a user. Accepts {username: string}."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify({"error": "username is required"}), 400
    try:
        user = user_service.get_or_create_user(username)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    token = user_service.create_session(user["id"])
    prefs = user_service.get_user_preferences(user["id"])
    resp = make_response(jsonify({"ok": True, "user": user, "preferences": prefs}))
    resp.set_cookie(
        user_service.SESSION_COOKIE_NAME,
        token,
        max_age=user_service.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="Lax",
    )
    return resp


@auth_bp.post("/logout")
def logout():
    """Log out the current user."""
    token = request.cookies.get(user_service.SESSION_COOKIE_NAME, "")
    if token:
        user_service.delete_session(token)
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie(user_service.SESSION_COOKIE_NAME, "", max_age=0)
    return resp


@auth_bp.get("/profile/preferences")
def get_prefs():
    """Return preferences for the current user."""
    user, error, status = require_login()
    if error:
        return error, status
    prefs = user_service.get_user_preferences(user["id"])
    return jsonify(prefs)



# ----------------------------------------------------------------------------
# Regions CRUD (user-defined LA/NY/BC/ON etc.)
# ----------------------------------------------------------------------------

@auth_bp.get("/regions")
def list_regions():
    """Return all regions for the current user, each with its aliases."""
    user, error, status = require_login()
    if error:
        return error, status
    user_service.seed_default_regions(user["id"])
    return jsonify({"regions": user_service.get_user_regions(user["id"])})


@auth_bp.post("/regions")
def save_all_regions():
    """Replace the user's region set. Body: {regions: [...]}."""
    user, error, status = require_login()
    if error:
        return error, status
    data = request.get_json(silent=True) or {}
    regions = data.get("regions", [])
    if not isinstance(regions, list):
        return jsonify({"error": "regions must be a list"}), 400
    saved = user_service.save_regions(user["id"], regions)
    return jsonify({"regions": saved, "ok": True})


@auth_bp.delete("/regions/<int:region_id>")
def remove_region(region_id: int):
    """Delete a single region by id."""
    user, error, status = require_login()
    if error:
        return error, status
    user_service.delete_region(region_id)
    return jsonify({"ok": True, "regions": user_service.get_user_regions(user["id"])})


# ----------------------------------------------------------------------------
# Tracks CRUD (user-defined tracks with editable titles + keywords)
# ----------------------------------------------------------------------------

@auth_bp.get("/tracks")
def list_tracks():
    """Return all tracks for the current user, each with titles + keywords."""
    user, error, status = require_login()
    if error:
        return error, status
    user_service.seed_default_tracks(user["id"])
    return jsonify({"tracks": user_service.get_user_tracks(user["id"])})


@auth_bp.post("/tracks")
def save_all_tracks():
    """Replace the user's track set. Body: {tracks: [...]}. 'not a fit' is ignored."""
    user, error, status = require_login()
    if error:
        return error, status
    data = request.get_json(silent=True) or {}
    tracks = data.get("tracks", [])
    if not isinstance(tracks, list):
        return jsonify({"error": "tracks must be a list"}), 400
    saved = user_service.save_user_tracks(user["id"], tracks)
    return jsonify({"tracks": saved, "ok": True})


@auth_bp.delete("/tracks/<int:track_id>")
def remove_track(track_id: int):
    """Delete a track definition only — its jobs are kept."""
    user, error, status = require_login()
    if error:
        return error, status
    deleted = user_service.delete_track(track_id)
    if not deleted:
        return jsonify({"error": "Track not found or is protected"}), 409
    return jsonify({
        "ok": True,
        "tracks": user_service.get_user_tracks(user["id"]),
    })


@auth_bp.post("/profile/preferences")
def save_prefs():
    """Save preferences for the current user."""
    user, error, status = require_login()
    if error:
        return error, status
    data = request.get_json(silent=True) or {}
    prefs = user_service.save_user_preferences(user["id"], data)
    return jsonify(prefs)


@auth_bp.get("/profile/stats")
def get_stats():
    """Return all stats for the current user (today, total, streak)."""
    user, error, status = require_login()
    if error:
        return error, status
    stats = user_service.get_profile_stats(user["id"])
    return jsonify(stats)


@auth_bp.get("/profile/badges")
def get_badges():
    """Return all badges (earned + locked) for the current user."""
    user, error, status = require_login()
    if error:
        return error, status
    badges = user_service.get_all_badges_for_user(user["id"])
    return jsonify(badges)
