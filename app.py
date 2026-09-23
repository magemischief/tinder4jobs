from __future__ import annotations

import os
from pathlib import Path
from functools import wraps
from flask import Flask, redirect, render_template, request, url_for, jsonify

from api.routes import api
from api.auth import auth_bp
from database import get_connection, ensure_skill_demand_columns, ensure_additive_columns, start_write_queue_flusher
from contextlib import closing
from url_utils import safe_next_url

# The database already exists with the full schema (managed by the daemon);
# skip the expensive init_db() and just ensure the sessions table is present.
with closing(get_connection()) as _conn:
    _conn.execute(
        "CREATE TABLE IF NOT EXISTS _sessions "
        "(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, "
        "created_at REAL NOT NULL, expires_at REAL NOT NULL)"
    )
    _conn.commit()

# Migrate additive columns (email_link, email_subject, email_received_at, etc.)
# onto any existing tables the webapp reads from but the daemon may not have
# re-touched. Idempotent — only ADD COLUMN when the column is missing.
ensure_additive_columns()

# Skills API selects * and the UI renders demand_auto/demand_job_count, so
# make sure the columns exist even if the daemon hasn't run its first
# skill-demand pass yet.
ensure_skill_demand_columns()


def login_required(f):
    """Redirect to /login if the request has no valid session cookie."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        from services import user_service
        user = user_service.get_logged_in_user(request)
        if user is None:
            return redirect(url_for("login_page") + "?next=" + request.path)
        return f(user=user, *args, **kwargs)
    return wrapper


def create_app() -> Flask:
    app = Flask(__name__)
    live_reload_enabled = os.environ.get("JOBHUNT_LIVERELOAD", "").lower() in {"1", "true", "yes"}
    # Always serve static files fresh and reload templates on disk, even when
    # FLASK_DEBUG=0. This ensures UI changes (CSS/JS/templates) are reflected
    # immediately without requiring a browser hard-refresh or server restart.
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    
    # Project root for file mtime checks
    _project_root = Path(__file__).resolve().parent
    
    @app.get("/_livereload/check")
    def livereload_check():
        """Return timestamp of most recent static/template change.
        Used by client-side polling to auto-refresh on file changes."""
        if not live_reload_enabled:
            return jsonify({"enabled": False, "mtime": 0})
        max_mtime = 0.0
        watch_dirs = ["static", "templates"]
        for watch_dir in watch_dirs:
            watch_path = _project_root / watch_dir
            if not watch_path.exists():
                continue
            for root, _, files in os.walk(watch_path):
                for f in files:
                    if f.endswith((".js", ".css", ".html", ".htm")):
                        p = Path(root) / f
                        try:
                            m = p.stat().st_mtime
                            if m > max_mtime:
                                max_mtime = m
                        except OSError:
                            pass
        return jsonify({"enabled": True, "mtime": max_mtime})
    
    app.register_blueprint(api)
    app.register_blueprint(auth_bp)

    @app.get("/")
    def index():
        return redirect(url_for("swipe_page"))

    @app.get("/login")
    def login_page():
        from services import user_service
        user = user_service.get_logged_in_user(request)
        if user is not None:
            next_url = safe_next_url(request.args.get("next", ""))
            return redirect(next_url or url_for("swipe_page"))
        return render_template(
            "login.html",
            active_page="login",
            next=safe_next_url(request.args.get("next", "")),
        )

    @app.get("/review")
    @login_required
    def swipe_page(user=None):
        return render_template("swipe.html", active_page="swipe", current_user=user)

    @app.get("/applications")
    @login_required
    def applications_page(user=None):
        return render_template("applications.html", active_page="applications", current_user=user)

    @app.get("/notifications")
    @login_required
    def notifications_page(user=None):
        return render_template("notifications.html", active_page="notifications", current_user=user)

    @app.get("/profile")
    @login_required
    def profile_page(user=None):
        """Combined user profile: preferences + badges."""
        return render_template("profile.html", active_page="profile", current_user=user)

    @app.get("/preferences")
    @login_required
    def preferences_page(user=None):
        return redirect(url_for("profile_page"))

    @app.get("/badges")
    @login_required
    def badges_page(user=None):
        return redirect(url_for("profile_page"))

    @app.get("/contacts")
    @login_required
    def contacts_page(user=None):
        return render_template("contacts.html", active_page="contacts", current_user=user)

    @app.get("/skills")
    @login_required
    def skills_page(user=None):
        return render_template("skills.html", active_page="skills", current_user=user)

    @app.get("/interviews")
    @login_required
    def interviews_page(user=None):
        return render_template("interviews.html", active_page="interviews", current_user=user)

    @app.get("/analytics")
    @login_required
    def analytics_page(user=None):
        return render_template("analytics.html", active_page="analytics", current_user=user)

    @app.get("/cover-letters")
    @login_required
    def cover_letters_page(user=None):
        return render_template("cover-letters.html", active_page="cover-letters", current_user=user)

    # Cached writes (queued when the daemon held the DB lock) are flushed by a
    # background timer thread — no per-request drain needed. See database.py.
    start_write_queue_flusher()

    return app


app = create_app()

if __name__ == '__main__':
    import os
    debug_mode = os.environ.get('FLASK_DEBUG', '1') not in (
        '0', 'false', 'False', ''
    )
    # Bind to all interfaces: the app is used from other devices on the LAN
    # (phone/tablet). Tradeoff: the app has no password auth, so anything on
    # the network can read/write the job DB — acceptable on a trusted home
    # network; add a real login password before ever exposing beyond that.
    # Reloader follows debug mode (prod unit sets FLASK_DEBUG=0 — an
    # always-on reloader forks twice and confuses systemd status).
    app.run(host='0.0.0.0', port=5000, debug=debug_mode, use_reloader=debug_mode)
