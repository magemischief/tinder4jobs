"""Multi-user accounts, preferences, session stats, streak, and badges."""
from __future__ import annotations
import json
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from database import get_connection, normalize_location, normalize_track_value, pending_prefs_overlay, queue_write
from shared_schema import count_skill_job_matches, demand_score_for_count

DEFAULT_USER_ID = 1
SESSION_COOKIE_NAME = "jh_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
REVIEW_STATUS = "Review to Apply"
READY_STATUS = "Ready to Apply"

def _make_token():
    return secrets.token_hex(24)

def _ensure_sessions_table():
    with closing(get_connection()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS _sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL)")
        conn.commit()

def create_session(user_id):
    _ensure_sessions_table()
    token = _make_token()
    now = time.time()
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM _sessions WHERE expires_at <= ?", (now,))
        conn.execute("INSERT OR REPLACE INTO _sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)", (token, user_id, now, now + SESSION_TTL_SECONDS))
        conn.commit()
    return token

def _get_user_from_token(token):
    if not token:
        return None
    now = time.time()
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT user_id, expires_at FROM _sessions WHERE token = ? AND expires_at > ?", (token, now)).fetchone()
        if row is None:
            return None
        user_row = conn.execute("SELECT id, username, created_at, is_default FROM users WHERE id = ?", (row["user_id"],)).fetchone()
        if user_row is None:
            return None
        return dict(user_row)

def delete_session(token):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM _sessions WHERE token = ?", (token,))
        conn.commit()

def get_or_create_default_user():
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT id, username, created_at, is_default FROM users WHERE is_default = 1 LIMIT 1").fetchone()
        if row:
            return dict(row)
        conn.execute("INSERT INTO users (username, is_default) VALUES ('Gabby', 1)")
        conn.commit()
        row = conn.execute("SELECT id, username, created_at, is_default FROM users WHERE is_default = 1 LIMIT 1").fetchone()
        return dict(row)

def get_user_by_id(user_id):
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT id, username, created_at, is_default FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

def get_user_by_username(username):
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT id, username, created_at, is_default FROM users WHERE username = ? COLLATE NOCASE", (username.strip(),)).fetchone()
        return dict(row) if row else None

def create_user(username):
    username = username.strip()
    if not username:
        raise ValueError("Username cannot be empty")
    if len(username) > 50:
        raise ValueError("Username must be 50 characters or fewer")
    with closing(get_connection()) as conn:
        existing = conn.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        if existing:
            raise ValueError(f"Username '{username}' is already taken")
        conn.execute("INSERT INTO users (username, is_default) VALUES (?, 0)", (username,))
        conn.commit()
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"id": user_id, "username": username, "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(), "is_default": 0}

def get_or_create_user(username):
    existing = get_user_by_username(username)
    if existing:
        return existing
    return create_user(username)

def _default_preferences():
    return {
        "default_tracks": [],
        "default_keywords": [],
        "blacklist_terms": [],
        "daily_goal": 10,
        "exclude_already_seen": False,
        "energy_max_reviews": 50,
        "theme": "light",
    }

def get_user_preferences(user_id):
    defaults = _default_preferences()
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)).fetchone()
    prefs = defaults
    if row is not None:
        d = dict(row)
        prefs = {
            "default_tracks": json.loads(d.get("default_tracks", "[]")),
            "default_keywords": json.loads(d.get("default_keywords", "[]")),
            "blacklist_terms": json.loads(d.get("blacklist_terms", "[]")),
            "daily_goal": d.get("daily_goal", 10),
            "exclude_already_seen": bool(d.get("exclude_already_seen", 0)),
            "energy_max_reviews": d.get("energy_max_reviews", 50),
            "theme": d.get("theme", "light") or "light",
        }
    # Side store wins on contradiction: staged (not-yet-applied) prefs overlay.
    staged = pending_prefs_overlay(user_id)
    if staged:
        prefs.update(staged)
    return prefs

def save_user_preferences(user_id, prefs):
    if not isinstance(prefs, dict):
        raise ValueError("preferences must be an object")
    for key in ("default_tracks", "default_keywords", "blacklist_terms"):
        if key in prefs and (
            not isinstance(prefs[key], list)
            or any(not isinstance(value, str) for value in prefs[key])
        ):
            raise ValueError(f"{key} must be a list of strings")
    for key, minimum, maximum in (("daily_goal", 1, 1000), ("energy_max_reviews", 0, 1000)):
        if key in prefs:
            try:
                prefs[key] = int(prefs[key])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be an integer") from exc
            if not minimum <= prefs[key] <= maximum:
                raise ValueError(f"{key} must be between {minimum} and {maximum}")
    if "theme" in prefs and prefs["theme"] not in {"light", "dark"}:
        raise ValueError("theme must be 'light' or 'dark'")
    if "exclude_already_seen" in prefs and not isinstance(prefs["exclude_already_seen"], bool):
        raise ValueError("exclude_already_seen must be a boolean")
    defaults = _default_preferences()
    # Settings updates are PATCH-like: forms and API clients may submit only
    # one field. Preserve all persisted (and staged) values not in this update.
    merged = {**defaults, **get_user_preferences(user_id), **prefs}

    # Normalize tracks to canonical forms (Software Engineer, Data Analyst, etc.).
    # Legacy keys (default_job_types, default_locations, preferred_keywords) are
    # accepted-but-ignored: their columns stay dormant to avoid data loss.
    norm_tracks = list({
        nt for nt in (normalize_track_value(t) for t in merged["default_tracks"] if t)
        if nt and nt != "not a fit"
    })
    merged["default_tracks"] = norm_tracks

    queued = queue_write(
        """INSERT INTO user_preferences
           (user_id, default_tracks, default_keywords, blacklist_terms,
            daily_goal, exclude_already_seen, energy_max_reviews, theme, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(user_id) DO UPDATE SET
               default_tracks = excluded.default_tracks,
               default_keywords = excluded.default_keywords,
               blacklist_terms = excluded.blacklist_terms,
               daily_goal = excluded.daily_goal,
               exclude_already_seen = excluded.exclude_already_seen,
               energy_max_reviews = excluded.energy_max_reviews,
               theme = excluded.theme,
               updated_at = CURRENT_TIMESTAMP""",
        (
            user_id,
            json.dumps(merged["default_tracks"]),
            json.dumps(merged["default_keywords"]),
            json.dumps(merged["blacklist_terms"]),
            merged["daily_goal"],
            1 if merged["exclude_already_seen"] else 0,
            merged["energy_max_reviews"],
            merged["theme"],
        ),
        table="user_preferences",
        row_key=str(user_id),
        payload={"user_id": user_id, "prefs": merged},
    )
    # If the write was queued (DB was locked), return the merged prefs from
    # memory so the caller gets the correct values immediately — reading the DB
    # now would return the stale pre-edit row.
    if queued:
        return {
            "default_tracks": merged["default_tracks"],
            "default_keywords": merged["default_keywords"],
            "blacklist_terms": merged["blacklist_terms"],
            "daily_goal": merged["daily_goal"],
            "exclude_already_seen": merged["exclude_already_seen"],
            "energy_max_reviews": merged["energy_max_reviews"],
            "theme": merged["theme"],
        }
    return get_user_preferences(user_id)


# -----------------------------------------------------------------------
# Regions (user-defined LA/NY/BC/ON etc.)
# -----------------------------------------------------------------------

def get_user_regions(user_id):
    """Return all regions for a user, each with its aliases."""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT id, code, name, color, sort_order, enabled FROM user_regions WHERE user_id = ? ORDER BY sort_order, code",
            (user_id,),
        ).fetchall()
        regions = []
        for row in rows:
            r = dict(row)
            alias_rows = conn.execute(
                "SELECT alias FROM user_location_aliases WHERE region_id = ? ORDER BY alias",
                (r["id"],),
            ).fetchall()
            r["aliases"] = [a["alias"] for a in alias_rows]
            regions.append(r)
        return regions


def save_regions(user_id, regions):
    """Upsert a list of regions. Each region dict: {code, name, color, sort_order, enabled, aliases: [str]}."""
    if not isinstance(regions, list) or any(not isinstance(region, dict) for region in regions):
        raise ValueError("regions must be a list of objects")
    with closing(get_connection()) as conn:
        for r in regions:
            code = (r.get("code") or "").strip().upper()
            if not code:
                continue
            name = (r.get("name") or code).strip()
            color = (r.get("color") or "").strip() or None
            try:
                sort_order = int(r.get("sort_order", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError("region sort_order must be an integer") from exc
            enabled = 1 if r.get("enabled", True) else 0

            conn.execute("""
                INSERT INTO user_regions (user_id, code, name, color, sort_order, enabled)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, code) DO UPDATE SET
                    name = excluded.name,
                    color = excluded.color,
                    sort_order = excluded.sort_order,
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, code, name, color, sort_order, enabled))

            region_row = conn.execute(
                "SELECT id FROM user_regions WHERE user_id = ? AND code = ?",
                (user_id, code),
            ).fetchone()
            if region_row:
                region_id = region_row["id"]
                conn.execute("DELETE FROM user_location_aliases WHERE region_id = ?", (region_id,))
                aliases = r.get("aliases") or []
                if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
                    raise ValueError("region aliases must be a list of strings")
                for alias in aliases:
                    alias_key = alias.strip().lower()
                    if alias_key:
                        conn.execute(
                            "INSERT OR IGNORE INTO user_location_aliases (region_id, alias) VALUES (?, ?)",
                            (region_id, alias_key),
                        )

        conn.commit()
    return get_user_regions(user_id)


def delete_region(user_id, region_id):
    """Delete one of the user's regions and all its aliases."""
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            "DELETE FROM user_regions WHERE id = ? AND user_id = ?",
            (region_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def seed_default_regions(user_id):
    """Seed ON/BC/LA/NY if the user has no regions yet."""
    with closing(get_connection()) as conn:
        existing = conn.execute(
            "SELECT COUNT(*) FROM user_regions WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        if existing > 0:
            return

    defaults = [
        {"code": "ON",  "name": "Ontario",           "color": "#f59e0b", "sort_order": 0,
         "aliases": ["ontario", "kitchener", "toronto", "ottawa", "london", "waterloo"]},
        {"code": "BC",  "name": "British Columbia",  "color": "#10b981", "sort_order": 1,
         "aliases": ["british columbia", "vancouver", "victoria", "kelowna", "burnaby", "richmond"]},
        {"code": "LA",  "name": "Los Angeles",       "color": "#ec4899", "sort_order": 2,
         "aliases": ["los angeles", "santa monica", "hollywood", "california", "san francisco", "socal"]},
        {"code": "NY",  "name": "New York",          "color": "#6366f1", "sort_order": 3,
         "aliases": ["new york", "nyc", "manhattan", "brooklyn", "jersey city", "new jersey"]},
    ]
    save_regions(user_id, defaults)


# -------------------------------------------------------------------------------
# Tracks (user-defined Game Developer / Software Engineer / ... with titles +
# keywords, regions-style). "not a fit" is reserved: never seeded, never listed,
# never deletable.
# -------------------------------------------------------------------------------

RESERVED_TRACK = "not a fit"

_DEFAULT_TRACKS = [
    {"name": "Game Developer", "sort_order": 0, "color": "#9333ea",
     "titles": ["game developer", "gameplay programmer", "unity developer",
                "unreal developer", "game programmer"],
     "keywords": ["unity", "unreal", "godot", "gameplay", "c++", "c#", "3d", "shader"]},
    {"name": "Software Engineer", "sort_order": 1, "color": "#2563eb",
     "titles": ["software engineer", "software developer", "full stack developer",
                "backend engineer", "frontend engineer", "web developer"],
     "keywords": ["python", "react", "node", "typescript", "javascript", "go", "java", "api", "aws"]},
    {"name": "Data Analyst", "sort_order": 2, "color": "#0f766e",
     "titles": ["data analyst", "business intelligence analyst", "bi analyst",
                "data scientist", "analytics engineer"],
     "keywords": ["sql", "tableau", "power bi", "pandas", "excel", "analytics", "etl", "python"]},
    {"name": "GIS/Spatial", "sort_order": 3, "color": "#0284c7",
     "titles": ["gis analyst", "gis developer", "geospatial analyst",
                "spatial analyst", "remote sensing specialist", "cartographer"],
     "keywords": ["gis", "arcgis", "qgis", "arcpy", "remote sensing", "spatial", "cartography", "geojson"]},
    {"name": "ML/AI", "sort_order": 4, "color": "#db2777",
     "titles": ["machine learning engineer", "ai engineer", "ml engineer",
                "nlp engineer", "computer vision engineer"],
     "keywords": ["machine learning", "deep learning", "tensorflow", "pytorch",
                  "llm", "nlp", "computer vision", "rag"]},
]


def _is_valid_hex_color(value):
    """True for '#rrggbb' strings. Guards the badge/CSS against garbage."""
    if not isinstance(value, str):
        return False
    v = value.strip()
    if len(v) != 7 or not v.startswith("#"):
        return False
    try:
        int(v[1:], 16)
    except ValueError:
        return False
    return True


def _track_term_map(track_id):
    """Return {'title': [...], 'keyword': [...]} for one track."""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT term_type, value FROM user_track_terms WHERE track_id = ? ORDER BY value",
            (track_id,),
        ).fetchall()
    titles, keywords = [], []
    for row in rows:
        (titles if row["term_type"] == "title" else keywords).append(row["value"])
    return {"title": titles, "keyword": keywords}


def get_user_tracks(user_id):
    """All tracks for a user with their titles+keywords. 'not a fit' is never returned."""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT id, name, color, sort_order, enabled FROM user_tracks "
            "WHERE user_id = ? AND LOWER(name) != ? ORDER BY sort_order, name",
            (user_id, RESERVED_TRACK),
        ).fetchall()
        # jobs.track holds the same label values; count per track (case-insensitive)
        # so the editor can show what deleting a track would remove.
        counts = {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT LOWER(track) AS tk, COUNT(*) AS n FROM jobs "
                "WHERE track IS NOT NULL AND TRIM(track) != '' GROUP BY LOWER(track)"
            ).fetchall()
        }
    tracks = []
    for row in rows:
        t = dict(row)
        terms = _track_term_map(t["id"])
        t["titles"] = terms["title"]
        t["keywords"] = terms["keyword"]
        t["job_count"] = counts.get(str(t["name"]).lower(), 0)
        tracks.append(t)
    return tracks


def save_user_tracks(user_id, tracks):
    """Upsert a list of tracks. Each dict: {name, color, sort_order, enabled, titles, keywords}.

    Terms replace the track's existing term set. 'not a fit' is reserved and
    ignored — it is never created, renamed, or listed.
    """
    if not isinstance(tracks, list) or any(not isinstance(track, dict) for track in tracks):
        raise ValueError("tracks must be a list of objects")
    with closing(get_connection()) as conn:
        for t in tracks:
            name = (t.get("name") or "").strip()
            if not name or name.lower() == RESERVED_TRACK:
                continue
            try:
                sort_order = int(t.get("sort_order", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError("track sort_order must be an integer") from exc
            enabled = 1 if t.get("enabled", True) else 0
            # Validate: only '#rrggbb' is stored; anything else (garbage,
            # 3-digit shorthand, named colors) falls back to NULL (= default).
            # Invalid input is a caller bug — log it instead of silently
            # swallowing so bad palettes surface in logs, not blank badges.
            raw_color = (t.get("color") or "").strip()
            color = raw_color if _is_valid_hex_color(raw_color) else None
            if t.get("color") and color is None:
                print(f"WARNING: save_user_tracks: invalid color {t.get('color')!r} for track {name!r}, using NULL")

            conn.execute("""
                INSERT INTO user_tracks (user_id, name, color, sort_order, enabled)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, name) DO UPDATE SET
                    color = excluded.color,
                    sort_order = excluded.sort_order,
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, name, color, sort_order, enabled))

            row = conn.execute(
                "SELECT id FROM user_tracks WHERE user_id = ? AND name = ?",
                (user_id, name),
            ).fetchone()
            if not row:
                continue
            track_id = row["id"]
            conn.execute("DELETE FROM user_track_terms WHERE track_id = ?", (track_id,))
            for term_type, values in (("title", t.get("titles") or []),
                                      ("keyword", t.get("keywords") or [])):
                if not isinstance(values, list):
                    raise ValueError(f"track {term_type} terms must be a list")
                for value in values:
                    key = str(value).strip().lower()
                    if key:
                        conn.execute(
                            "INSERT OR IGNORE INTO user_track_terms (track_id, term_type, value) "
                            "VALUES (?, ?, ?)",
                            (track_id, term_type, key),
                        )
        conn.commit()
    return get_user_tracks(user_id)

def delete_track(user_id, track_id):
    """Delete a track definition only — its jobs are kept.

    Returns True when a non-reserved track was deleted. Refuses the
    reserved 'not a fit'. Jobs keep their ``jobs.track`` label so no
    postings are lost; only the editor's titles/keywords entry is removed.
    """
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT name FROM user_tracks WHERE id = ? AND user_id = ?",
            (track_id, user_id),
        ).fetchone()
        if row is None:
            return False
        name = str(row["name"]).strip()
        if name.lower() == RESERVED_TRACK:
            return False
        conn.execute(
            "DELETE FROM user_tracks WHERE id = ? AND user_id = ?",
            (track_id, user_id),
        )
        conn.commit()
        return True


def seed_default_tracks(user_id):
    """Seed the editable track set if the user has none. Never includes 'not a fit'."""
    with closing(get_connection()) as conn:
        existing = conn.execute(
            "SELECT COUNT(*) FROM user_tracks WHERE user_id = ? AND LOWER(name) != ?",
            (user_id, RESERVED_TRACK),
        ).fetchone()[0]
        if existing > 0:
            return

    save_user_tracks(user_id, _DEFAULT_TRACKS)

    # Keep the legacy default_tracks preference in sync so the review filter and
    # daemon still see the same track set the editor manages.
    with closing(get_connection()) as conn:
        names = [t["name"] for t in _DEFAULT_TRACKS]
        conn.execute(
            """
            INSERT INTO user_preferences (user_id, default_tracks)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                default_tracks = CASE
                    WHEN TRIM(COALESCE(user_preferences.default_tracks, '')) = ''
                    THEN excluded.default_tracks
                    ELSE user_preferences.default_tracks
                END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, json.dumps(names)),
        )
        conn.commit()


REVERSIBLE_REVIEW_ACTIONS = {"like", "dislike", "unsure", "expired"}
COUNTED_ACTIONS = REVERSIBLE_REVIEW_ACTIONS | {"duplicate", "apply"}
COUNTED_ACTIONS_SQL = ", ".join(f"'{action}'" for action in sorted(COUNTED_ACTIONS))


def record_action(user_id, action_type, job_id=None, job_score=None):
    if action_type not in COUNTED_ACTIONS:
        return
    points = 0
    if action_type == "apply":
        # Base XP for applying
        points = 10
        # Bonus based on job relevance (0-100 scale, so //10 gives 0-10)
        if job_score is not None:
            points += job_score // 10
        # Daily first-apply bonus
        with closing(get_connection()) as conn:
            today = date.today().isoformat()
            apply_today = conn.execute(
                "SELECT COUNT(*) FROM user_session_stats WHERE user_id = ? AND action_type = 'apply' AND date(created_at) = ?",
                (user_id, today)
            ).fetchone()[0]
            if apply_today == 0:
                points += 5
            # Apply streak bonus (max +5)
            streak = _get_apply_streak(conn, user_id)
            points += min(streak, 5)
    with closing(get_connection()) as conn:
        conn.execute(
            "INSERT INTO user_session_stats (user_id, action_type, job_id, job_score, points) VALUES (?, ?, ?, ?, ?)",
            (user_id, action_type, job_id, job_score, points)
        )
        conn.commit()
    return points


def _get_apply_streak(conn, user_id):
    """Return current consecutive days with at least one apply (0 if none today/yesterday)."""
    rows = conn.execute(
        "SELECT DISTINCT date(created_at) as action_date FROM user_session_stats "
        "WHERE user_id = ? AND action_type = 'apply' ORDER BY action_date DESC",
        (user_id,)
    ).fetchall()
    if not rows:
        return 0
    dates = [datetime.strptime(r["action_date"], "%Y-%m-%d").date() for r in rows]
    today = date.today()
    date_set = set(dates)
    # Streak counts today if applied today, else yesterday
    cursor = today if today in date_set else today - timedelta(days=1)
    streak = 0
    while cursor in date_set:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def get_total_points(user_id):
    """Return total XP earned from all actions."""
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(points), 0) FROM user_session_stats WHERE user_id = ?",
            (user_id,)
        ).fetchone()
    return row[0] if row else 0


class LotterySystem:
    """Gamified lottery reward system using existing infrastructure.

    Applications and likes earn lottery tickets in addition to XP.
    5 tickets = 1 entry in the daily draw for a $5 coffee credit.
    """

    TICKETS_FOR_LIKE = 1
    TICKETS_FOR_APPLY = 3
    TICKETS_FOR_DAILY_DRAW = 5

    @staticmethod
    def award_on_action(user_id, action_type, job_id=None):
        """Award lottery tickets for an action. Returns tickets earned."""
        if action_type == "apply":
            tickets = LotterySystem.TICKETS_FOR_APPLY
        elif action_type == "like":
            tickets = LotterySystem.TICKETS_FOR_LIKE
        else:
            tickets = 0
        LotterySystem._record_tickets(user_id, action_type, tickets, job_id)
        return tickets

    @staticmethod
    def _record_tickets(user_id, action_type, tickets, job_id=None):
        """Attach tickets to the action row that earned them."""
        if tickets <= 0:
            return
        today = date.today().isoformat()
        with closing(get_connection()) as conn:
            cursor = conn.execute(
                """UPDATE user_session_stats
                   SET raffle_tickets = raffle_tickets + ?
                   WHERE id = (
                       SELECT id FROM user_session_stats
                       WHERE user_id = ? AND action_type = ?
                         AND date(created_at) = ?
                         AND (job_id = ? OR (? IS NULL AND job_id IS NULL))
                       ORDER BY id DESC LIMIT 1
                   )""",
                (tickets, user_id, action_type, today, job_id, job_id),
            )
            # Keep direct callers correct even if no action row was recorded first.
            if cursor.rowcount == 0:
                conn.execute(
                    """INSERT INTO user_session_stats
                       (user_id, action_type, job_id, points, raffle_tickets, created_at)
                       VALUES (?, ?, ?, 0, ?, ?)""",
                    (user_id, action_type, job_id, tickets, today),
                )
            conn.commit()

    @staticmethod
    def get_user_tickets(user_id):
        """Get current raffle ticket balance (today + any pending)."""
        with closing(get_connection()) as conn:
            today = date.today().isoformat()
            row = conn.execute(
                """SELECT COALESCE(SUM(raffle_tickets), 0) as tickets
                   FROM user_session_stats WHERE user_id = ? AND date(created_at) = ?""",
                (user_id, today)
            ).fetchone()
        return row[0] if row else 0

    @staticmethod
    def draw_daily_winners():
        """Draw lottery winners for the day. Returns list of (user_id, prize) tuples."""
        with closing(get_connection()) as conn:
            today = date.today().isoformat()
            users = conn.execute(
                """SELECT user_id, COALESCE(SUM(raffle_tickets), 0) as tickets
                   FROM user_session_stats WHERE date(created_at) = ? GROUP BY user_id""",
                (today,)
            ).fetchall()

            winners = []
            for user in users:
                user_id = user["user_id"]
                tickets = user["tickets"]
                # Every 5 tickets = 1 coffee credit ($5)
                while tickets >= LotterySystem.TICKETS_FOR_DAILY_DRAW:
                    winners.append((user_id, "$5 Coffee Credit"))
                    tickets -= LotterySystem.TICKETS_FOR_DAILY_DRAW

            # Reset all tickets for tomorrow
            conn.execute(
                "UPDATE user_session_stats SET raffle_tickets = 0 WHERE date(created_at) = ?",
                (today,)
            )
            conn.commit()
            return winners


def get_apply_streak(user_id):
    """Return current and longest apply streak."""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT DISTINCT date(created_at) as action_date FROM user_session_stats "
            "WHERE user_id = ? AND action_type = 'apply' ORDER BY action_date DESC",
            (user_id,)
        ).fetchall()
    if not rows:
        return {"current": 0, "longest": 0}
    dates = [datetime.strptime(r["action_date"], "%Y-%m-%d").date() for r in rows]
    today = date.today()
    date_set = set(dates)
    current = 0
    cursor = today if today in date_set else today - timedelta(days=1)
    while cursor in date_set:
        current += 1
        cursor -= timedelta(days=1)
    longest = 0
    streak = 0
    prev = None
    for d in sorted(dates):
        streak = streak + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, streak)
        prev = d
    return {"current": current, "longest": longest}

def _action_counts_query(user_id, today_only):
    with closing(get_connection()) as conn:
        if today_only:
            today = date.today().isoformat()
            return conn.execute("SELECT action_type, COUNT(*) as count FROM user_session_stats WHERE user_id = ? AND date(created_at) = ? GROUP BY action_type", (user_id, today)).fetchall()
        return conn.execute("SELECT action_type, COUNT(*) as count FROM user_session_stats WHERE user_id = ? GROUP BY action_type", (user_id,)).fetchall()

def get_today_stats(user_id):
    rows = _action_counts_query(user_id, today_only=True)
    counts = {a: 0 for a in COUNTED_ACTIONS}
    for row in rows:
        if row["action_type"] in counts:
            counts[row["action_type"]] = row["count"]
    total = sum(counts.values())
    prefs = get_user_preferences(user_id)
    goal = prefs["daily_goal"]
    return {**counts, "total": total, "daily_goal": goal, "goal_progress": min(total / goal, 1.0) if goal > 0 else 1.0, "goal_met": total >= goal}

def get_total_stats(user_id):
    rows = _action_counts_query(user_id, today_only=False)
    counts = {a: 0 for a in COUNTED_ACTIONS}
    for row in rows:
        if row["action_type"] in counts:
            counts[row["action_type"]] = row["count"]
    total = sum(counts.values())
    with closing(get_connection()) as conn:
        badges = conn.execute("SELECT COUNT(*) FROM user_badges WHERE user_id = ?", (user_id,)).fetchone()[0]
    return {**counts, "total": total, "badges_earned": badges, "total_points": get_total_points(user_id)}

def get_streak(user_id):
    with closing(get_connection()) as conn:
        placeholders = ", ".join("?" for _ in COUNTED_ACTIONS)
        rows = conn.execute(
            f"SELECT DISTINCT date(created_at) AS action_date FROM user_session_stats "
            f"WHERE user_id = ? AND action_type IN ({placeholders}) ORDER BY action_date DESC",
            (user_id, *sorted(COUNTED_ACTIONS)),
        ).fetchall()
        freeze_rows = conn.execute(
            "SELECT used_on AS action_date FROM streak_freezes WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    if not rows and not freeze_rows:
        return {"current": 0, "longest": 0}
    dates = [
        datetime.strptime(r["action_date"], "%Y-%m-%d").date()
        for r in [*rows, *freeze_rows]
        if r["action_date"]
    ]
    today = date.today()
    date_set = set(dates)
    current = 0
    cursor = today if today in date_set else today - timedelta(days=1)
    while cursor in date_set:
        current += 1
        cursor -= timedelta(days=1)
    longest = 0
    streak = 0
    prev = None
    for d in sorted(dates):
        streak = streak + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, streak)
        prev = d
    return {"current": current, "longest": longest}

def get_profile_stats(user_id):
    today_stats = get_today_stats(user_id)
    total_stats = get_total_stats(user_id)
    streak = get_streak(user_id)
    prefs = get_user_preferences(user_id)
    user = get_user_by_id(user_id)
    return {
        "user": user,
        "today": today_stats,
        "total": total_stats,
        "streak": streak,
        "daily_goal": prefs["daily_goal"],
        "apply_streak": get_apply_streak(user_id),
    }


def get_logged_in_user(request):
    """Return the user from a valid session cookie, or None if not logged in.
    Unlike get_current_user, this does NOT fall back to the default user."""
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not token:
        return None
    user = _get_user_from_token(token)
    if user is None:
        return None
    return user



BADGE_CATALOG = {
    "first_review": ("First Swipe", "Reviewed your first job", "🎯", "milestone"),
    "first_like": ("Liked First", "Liked your first job", "❤️", "milestone"),
    "first_dislike": ("First Pass", "Disliked your first job", "👎", "milestone"),
    "first_unsure": ("Unsure Starter", "Marked your first job as unsure", "🤔", "milestone"),
    "first_dup": ("Duplicate Hunter", "Marked your first job as duplicate", "🔁", "milestone"),
    "first_apply": ("Ready to Apply", "Applied to your first job", "📤", "milestone"),
    "reviews_10": ("Getting Started", "Reviewed 10 jobs", "10️⃣", "volume"),
    "reviews_25": ("Reviewer", "Reviewed 25 jobs", "2️⃣5️⃣", "volume"),
    "reviews_50": ("Job Scout", "Reviewed 50 jobs", "5️⃣0️⃣", "volume"),
    "reviews_100": ("Dedicated Reviewer", "Reviewed 100 jobs", "💯", "volume"),
    "reviews_250": ("Job Explorer", "Reviewed 250 jobs", "🌿", "volume"),
    "reviews_500": ("Career Navigator", "Reviewed 500 jobs", "🚀", "volume"),
    "reviews_1000": ("Job Veteran", "Reviewed 1000 jobs", "⚔️", "volume"),
    "likes_10": ("Liker", "Liked 10 jobs", "👍10", "likes"),
    "likes_50": ("Selective", "Liked 50 jobs", "👍50", "likes"),
    "likes_100": ("Quality Selector", "Liked 100 jobs", "👍💯", "likes"),
    "likes_250": ("Curator", "Liked 250 jobs", "🏆", "likes"),
    "applied_1": ("First Steps", "Applied to 1 job", "📋1", "applied"),
    "applied_5": ("Active Applicant", "Applied to 5 jobs", "📋5", "applied"),
    "applied_10": ("Job Seeker", "Applied to 10 jobs", "📋🔟", "applied"),
    "applied_25": ("Serial Applicant", "Applied to 25 jobs", "📋2️⃣5️⃣", "applied"),
    "applied_50": ("Career Chaser", "Applied to 50 jobs", "📋5️⃣0️⃣", "applied"),
    "applied_100": ("Application Machine", "Applied to 100 jobs", "🏭", "applied"),
    "apply_streak_3": ("3-Day Apply Streak", "Applied 3 days in a row", "🔥3", "streak"),
    "apply_streak_7": ("7-Day Apply Streak", "Applied 7 days in a row", "🔥7", "streak"),
    "apply_streak_14": ("14-Day Apply Streak", "Applied 14 days in a row", "🔥14", "streak"),
    "apply_streak_30": ("30-Day Apply Streak", "Applied 30 days in a row", "🔥🔥🔥", "streak"),
    "points_100": ("Century XP", "Earned 100 total XP", "⭐100", "volume"),
    "points_500": ("Half-K XP", "Earned 500 total XP", "⭐500", "volume"),
    "points_1000": ("K XP Club", "Earned 1,000 total XP", "⭐1K", "volume"),
    "points_5000": ("5K XP Club", "Earned 5,000 total XP", "⭐5K", "volume"),
    "streak_2": ("2-Day Streak", "Reviewed jobs 2 days in a row", "🔥2", "streak"),
    "streak_3": ("3-Day Streak", "Reviewed jobs 3 days in a row", "🔥3", "streak"),
    "streak_5": ("5-Day Streak", "Reviewed jobs 5 days in a row", "🔥5", "streak"),
    "streak_7": ("Week Warrior", "Reviewed jobs 7 days in a row", "🔥7", "streak"),
    "streak_14": ("Fortnight Focus", "Reviewed jobs 14 days in a row", "🔥14", "streak"),
    "streak_30": ("Monthly Master", "Reviewed jobs 30 days in a row", "🔥🔥🔥", "streak"),
    "streak_60": ("Bi-Monthly Beast", "Reviewed jobs 60 days in a row", "💪", "streak"),
    "streak_100": ("Century Club", "Reviewed jobs 100 days in a row", "💯", "streak"),
    "goal_hit_1": ("Goal Getter", "Hit your daily goal once", "🎯1", "goals"),
    "goal_hit_7": ("Goal Setter", "Hit your daily goal 7 times", "🎯7", "goals"),
    "goal_hit_30": ("Goal Crusher", "Hit your daily goal 30 times", "🎯🔥", "goals"),
    "goal_hit_100": ("Goal Destroyer", "Hit your daily goal 100 times", "🎯💯", "goals"),
    "all_likes_day": ("Perfectionist", "A day where all reviews were likes (5+)", "✨", "quality"),
    "all_dislikes_day": ("Tough Crowd", "A day where all reviews were dislikes (5+)", "😤", "quality"),
    "mixed_day": ("Balanced Reviewer", "Used all 4 action types in one day", "⚖️", "quality"),
    "speed_reviewer": ("Speed Demon", "10 reviews in under 60 seconds", "⚡", "speed"),
    "decisive": ("Decisive", "50 reviews in one session", "🏅", "speed"),
    "early_bird": ("Early Bird", "Reviewed a job before 8am", "🌅", "time"),
    "night_owl": ("Night Owl", "Reviewed a job after 11pm", "🦉", "time"),
    "comeback": ("Comeback Kid", "Reviewed after a 7+ day gap", "🔙", "comeback"),
    "multi_track": ("Well-Rounded", "Reviewed across 3 different tracks", "🌈", "diversity"),
    "curator_5": ("Curator", "Applied to 5 jobs in one day", "📚", "applied"),
    "perfect_match": ("Perfect Match", "Encountered a job with 90%+ relevance", "💯", "score"),
    "high_relevance_10": ("Relevance Hunter", "10 jobs with 80%+ relevance", "🎯", "score"),
    "curated_50": ("Curated Collection", "50 jobs with 70%+ relevance", "📖", "score"),
    "veteran_30": ("30-Day Veteran", "Account is 30 days old", "📅30", "veteran"),
    "veteran_60": ("60-Day Veteran", "Account is 60 days old", "📅60", "veteran"),
    "veteran_180": ("6-Month Veteran", "Account is 6 months old", "📅180", "veteran"),
    "veteran_365": ("Year-Long Journey", "Account is 1 year old", "📅365", "veteran"),
    "scholar": ("Scholar", "100 reviews, 50 likes, 7-day streak", "🎓", "special"),
    "nothing_left": ("Clean Queue", "Cleared the entire review queue", "🏆", "special"),
    "duplicate_master": ("Duplicate Master", "Marked 100 jobs as duplicates", "🔁", "special"),
}

def get_badge_info(key):
    name, desc, emoji, category = BADGE_CATALOG.get(key, (key, "", "🏅", "special"))
    return {"key": key, "name": name, "description": desc, "emoji": emoji, "category": category}

def get_user_badges(user_id):
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT badge_key, earned_at FROM user_badges WHERE user_id = ? ORDER BY earned_at DESC", (user_id,)).fetchall()
    return [{**get_badge_info(r["badge_key"]), "earned_at": r["earned_at"]} for r in rows]

def get_all_badges_for_user(user_id):
    earned = get_user_badges(user_id)
    earned_keys = {b["key"] for b in earned}
    locked = [get_badge_info(k) for k in BADGE_CATALOG if k not in earned_keys]
    return {"earned": earned, "locked": locked, "total": len(BADGE_CATALOG)}

def award_badge(user_id, badge_key):
    if badge_key not in BADGE_CATALOG:
        return False
    with closing(get_connection()) as conn:
        try:
            conn.execute("INSERT INTO user_badges (user_id, badge_key) VALUES (?, ?)", (user_id, badge_key))
            conn.commit()
            return True
        except Exception:
            return False

def get_earned_badge_keys(user_id):
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT badge_key FROM user_badges WHERE user_id = ?", (user_id,)).fetchall()
    return {r["badge_key"] for r in rows}



def mark_job_seen(user_id, job_id, status, score=None):
    with closing(get_connection()) as conn:
        conn.execute("INSERT INTO user_job_state (user_id, job_id, status, score, last_seen_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(user_id, job_id) DO UPDATE SET status = excluded.status, score = COALESCE(excluded.score, score), last_seen_at = CURRENT_TIMESTAMP", (user_id, job_id, status, score))
        conn.commit()


def undo_recorded_action(user_id, job_id, action_type=None):
    """Remove the user's latest reversible stat and review marker for a job."""
    with closing(get_connection()) as conn:
        conn.execute(
            """
            DELETE FROM user_session_stats
            WHERE id = (
                SELECT id FROM user_session_stats
                WHERE user_id = ? AND job_id = ?
                  AND action_type IN ('like', 'dislike', 'unsure', 'expired')
                  AND (? IS NULL OR action_type = ?)
                ORDER BY id DESC LIMIT 1
            )
            """,
            (user_id, job_id, action_type, action_type),
        )
        conn.execute(
            "DELETE FROM user_job_state WHERE user_id = ? AND job_id = ?",
            (user_id, job_id),
        )
        conn.commit()

def get_seen_job_ids(user_id, status=None):
    with closing(get_connection()) as conn:
        if status:
            rows = conn.execute("SELECT job_id FROM user_job_state WHERE user_id = ? AND status = ?", (user_id, status)).fetchall()
        else:
            rows = conn.execute("SELECT job_id FROM user_job_state WHERE user_id = ?", (user_id,)).fetchall()
    return {r["job_id"] for r in rows}

def has_user_reviewed_job(user_id, job_id):
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT 1 FROM user_job_state WHERE user_id = ? AND job_id = ? LIMIT 1", (user_id, job_id)).fetchone()
    return row is not None

def get_job_score(user_id, job_id):
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT score FROM job_scores WHERE user_id = ? AND job_id = ?", (user_id, job_id)).fetchone()
    return row["score"] if row else None

def check_and_award_badges(user_id):
    today = get_today_stats(user_id)
    total = get_total_stats(user_id)
    streak = get_streak(user_id)
    prefs = get_user_preferences(user_id)
    user = get_user_by_id(user_id)
    earned = get_earned_badge_keys(user_id)
    newly_awarded = []
    def try_award(key):
        if key not in earned:
            if award_badge(user_id, key):
                newly_awarded.append(get_badge_info(key))
    total_reviews = total["total"]
    total_likes = total["like"]
    total_apply = total["apply"]
    total_dups = total["duplicate"]
    streak_current = streak["current"]
    if total_reviews >= 1: try_award("first_review")
    if total_likes >= 1: try_award("first_like")
    if total["dislike"] >= 1: try_award("first_dislike")
    if total["unsure"] >= 1: try_award("first_unsure")  # use lifetime total like other first_* badges
    if total_dups >= 1: try_award("first_dup")
    if total_apply >= 1: try_award("first_apply")
    for threshold, badge_key in [(10, "reviews_10"), (25, "reviews_25"), (50, "reviews_50"), (100, "reviews_100"), (250, "reviews_250"), (500, "reviews_500"), (1000, "reviews_1000")]:
        if total_reviews >= threshold: try_award(badge_key)
    for threshold, badge_key in [(10, "likes_10"), (50, "likes_50"), (100, "likes_100"), (250, "likes_250")]:
        if total_likes >= threshold: try_award(badge_key)
    for threshold, badge_key in [(1, "applied_1"), (5, "applied_5"), (10, "applied_10"), (25, "applied_25"), (50, "applied_50"), (100, "applied_100")]:
        if total_apply >= threshold: try_award(badge_key)
    apply_streak = get_apply_streak(user_id)
    for threshold, badge_key in [(3, "apply_streak_3"), (7, "apply_streak_7"), (14, "apply_streak_14"), (30, "apply_streak_30")]:
        if apply_streak["current"] >= threshold: try_award(badge_key)
    total_points = total["total_points"]
    for threshold, badge_key in [(100, "points_100"), (500, "points_500"), (1000, "points_1000"), (5000, "points_5000")]:
        if total_points >= threshold: try_award(badge_key)
    for threshold, badge_key in [(2, "streak_2"), (3, "streak_3"), (5, "streak_5"), (7, "streak_7"), (14, "streak_14"), (30, "streak_30"), (60, "streak_60"), (100, "streak_100")]:
        if streak_current >= threshold: try_award(badge_key)
    with closing(get_connection()) as conn:
        goal_hit_days = conn.execute(
            f"SELECT COUNT(*) FROM (SELECT date(created_at) AS d FROM user_session_stats "
            f"WHERE user_id = ? AND action_type IN ({COUNTED_ACTIONS_SQL}) "
            "GROUP BY d HAVING COUNT(*) >= ?)",
            (user_id, prefs["daily_goal"]),
        ).fetchone()[0]
    for threshold, badge_key in [(1, "goal_hit_1"), (7, "goal_hit_7"), (30, "goal_hit_30"), (100, "goal_hit_100")]:
        if goal_hit_days >= threshold: try_award(badge_key)
    if today["total"] >= 5 and today["dislike"] == 0 and today["unsure"] == 0 and today["duplicate"] == 0: try_award("all_likes_day")
    if today["total"] >= 5 and today["like"] == 0 and today["unsure"] == 0 and today["duplicate"] == 0: try_award("all_dislikes_day")
    if today["like"] > 0 and today["dislike"] > 0 and today["unsure"] > 0 and today["duplicate"] > 0: try_award("mixed_day")
    now_hour = datetime.now().hour
    if now_hour < 8: try_award("early_bird")
    if now_hour >= 23: try_award("night_owl")
    if total_reviews >= 1:
        with closing(get_connection()) as conn:
            first_action = conn.execute(
                f"SELECT date(created_at) FROM user_session_stats WHERE user_id = ? "
                f"AND action_type IN ({COUNTED_ACTIONS_SQL}) ORDER BY created_at LIMIT 1",
                (user_id,),
            ).fetchone()
            last_action = conn.execute(
                f"SELECT date(created_at) FROM user_session_stats WHERE user_id = ? "
                f"AND action_type IN ({COUNTED_ACTIONS_SQL}) ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if first_action and last_action and first_action[0] != last_action[0]:
                first_date = datetime.strptime(first_action[0], "%Y-%m-%d").date()
                last_date = datetime.strptime(last_action[0], "%Y-%m-%d").date()
                if (last_date - first_date).days >= 7: try_award("comeback")
    with closing(get_connection()) as conn:
        perfect_count = conn.execute("SELECT COUNT(*) FROM user_session_stats WHERE user_id = ? AND job_score >= 90", (user_id,)).fetchone()[0]
        if perfect_count >= 1: try_award("perfect_match")
        high_count = conn.execute("SELECT COUNT(*) FROM user_session_stats WHERE user_id = ? AND job_score >= 80", (user_id,)).fetchone()[0]
        if high_count >= 10: try_award("high_relevance_10")
        curated_count = conn.execute("SELECT COUNT(*) FROM user_session_stats WHERE user_id = ? AND job_score >= 70", (user_id,)).fetchone()[0]
        if curated_count >= 50: try_award("curated_50")
    if user:
        try:
            created = datetime.strptime(user["created_at"][:10], "%Y-%m-%d").date()
            age_days = (date.today() - created).days
            for threshold, badge_key in [(30, "veteran_30"), (60, "veteran_60"), (180, "veteran_180"), (365, "veteran_365")]:
                if age_days >= threshold: try_award(badge_key)
        except Exception: pass
    if total_reviews >= 100 and total_likes >= 50 and streak["longest"] >= 7: try_award("scholar")
    if total_dups >= 100: try_award("duplicate_master")
    return newly_awarded


# ── Streak freezes ───────────────────────────────────────────────────────────────
def get_streak_freezes(user_id):
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM streak_freezes WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]

def use_streak_freeze(user_id, date_str):
    try:
        freeze_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError("date must use YYYY-MM-DD format") from exc
    if freeze_date > date.today():
        raise ValueError("A streak freeze cannot be recorded in the future")
    date_str = freeze_date.isoformat()
    with closing(get_connection()) as conn:
        existing = conn.execute(
            "SELECT id FROM streak_freezes WHERE user_id = ? AND used_on = ?",
            (user_id, date_str),
        ).fetchone()
        if existing:
            return False, "A freeze is already recorded for " + date_str
        conn.execute(
            "INSERT INTO streak_freezes (user_id, used_on, source) VALUES (?, ?, 'manual')",
            (user_id, date_str),
        )
        conn.commit()
        return True, "Streak freeze recorded for " + date_str


# ── Skills ───────────────────────────────────────────────────────────────────────
def get_user_skills(user_id):
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM skill_assessments WHERE user_id = ? ORDER BY skill ASC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]

def upsert_skill_assessment(user_id, skill, self_rating=3, notes=None, market_demand=3, original_skill=None):
    """Insert or update a skill row and immediately recompute its demand.

    `market_demand` is a legacy manual value: kept only to satisfy the NOT NULL
    constraint on first insert — updates no longer touch it. Real demand is
    computed from job counts via shared_schema.count_skill_job_matches — the
    same matcher the daemon's 24h bulk pass uses — so a just-saved skill shows
    its Matching Jobs / Demand numbers right away instead of a blank until the
    next daemon cycle.
    """
    skill = str(skill or "").strip()
    if not skill:
        raise ValueError("skill name is required")
    try:
        self_rating = int(self_rating)
    except (TypeError, ValueError) as exc:
        raise ValueError("self_rating must be an integer from 1 to 5") from exc
    if not 1 <= self_rating <= 5:
        raise ValueError("self_rating must be between 1 and 5")
    lookup_skill = str(original_skill or skill).strip()

    with closing(get_connection()) as conn:
        existing = conn.execute(
            "SELECT id FROM skill_assessments WHERE user_id = ? AND skill = ? COLLATE NOCASE",
            (user_id, lookup_skill),
        ).fetchone()
        if existing:
            try:
                conn.execute(
                    "UPDATE skill_assessments SET skill=?, self_rating=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id = ?",
                    (skill, self_rating, notes, existing["id"]),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"A skill named '{skill}' already exists") from exc
            skill_id = existing["id"]
        else:
            conn.execute(
                "INSERT INTO skill_assessments (user_id, skill, self_rating, market_demand, notes) VALUES (?, ?, ?, ?, ?)",
                (user_id, skill, self_rating, market_demand, notes),
            )
            skill_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        count = count_skill_job_matches(skill, conn)
        score = demand_score_for_count(count)
        conn.execute(
            "UPDATE skill_assessments SET demand_auto = ?, demand_job_count = ?, "
            "demand_updated_at = ? WHERE id = ?",
            (score, count, datetime.now().isoformat(), skill_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM skill_assessments WHERE id = ?", (skill_id,)
        ).fetchone()
        return dict(row)

def delete_skill_assessment(user_id, skill):
    """Delete a skill row; raise KeyError when it doesn't exist (API → 404)."""
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            "DELETE FROM skill_assessments WHERE user_id = ? AND skill = ? COLLATE NOCASE",
            (user_id, skill),
        )
        if cursor.rowcount == 0:
            raise KeyError("Skill not found")
        conn.commit()

# ── Cover letters ───────────────────────────────────────────────────────────────
def get_cover_letters(user_id):
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM cover_letters WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]

def create_cover_letter(user_id, title, body, job_id=None):
    with closing(get_connection()) as conn:
        if job_id is not None and conn.execute(
            "SELECT 1 FROM jobs WHERE id = ?", (job_id,)
        ).fetchone() is None:
            raise KeyError("Job not found")
        conn.execute(
            "INSERT INTO cover_letters (user_id, title, body, job_id) VALUES (?, ?, ?, ?)",
            (user_id, title, body, job_id),
        )
        conn.commit()
        last = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = conn.execute(
            "SELECT * FROM cover_letters WHERE id = ?", (last,)
        ).fetchone()
        return dict(row)


def delete_cover_letter(user_id, letter_id):
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT id FROM cover_letters WHERE id = ? AND user_id = ?",
            (letter_id, user_id),
        ).fetchone()
        if row is None:
            raise KeyError("Cover letter not found")
        conn.execute("DELETE FROM cover_letters WHERE id = ?", (letter_id,))
        conn.commit()


# ── Analytics summary ─────────────────────────────────────────────────────────────
def get_analytics_summary(user_id):
    with closing(get_connection()) as conn:
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        daily = conn.execute(
            "SELECT date(created_at) as d, COUNT(*) as total FROM user_session_stats "
            f"WHERE user_id = ? AND action_type IN ({COUNTED_ACTIONS_SQL}) "
            "AND date(created_at) >= ? GROUP BY d ORDER BY d ASC",
            (user_id, thirty_days_ago),
        ).fetchall()
        by_track = conn.execute(
            "SELECT j.track, COUNT(*) as total, "
            "SUM(CASE WHEN s.action_type = 'like' THEN 1 ELSE 0 END) as liked, "
            "SUM(CASE WHEN s.action_type = 'apply' THEN 1 ELSE 0 END) as applied, "
            "AVG(CASE WHEN s.job_score > 0 THEN s.job_score END) as avg_score "
            "FROM user_session_stats s "
            "JOIN jobs j ON j.id = s.job_id "
            f"WHERE s.user_id = ? AND s.action_type IN ({COUNTED_ACTIONS_SQL}) AND date(s.created_at) >= ? "
            "GROUP BY j.track ORDER BY total DESC",
            (user_id, thirty_days_ago),
        ).fetchall()
        actions = conn.execute(
            "SELECT action_type, COUNT(*) as total FROM user_session_stats "
            "WHERE user_id = ? AND date(created_at) >= ? GROUP BY action_type",
            (user_id, thirty_days_ago),
        ).fetchall()
        by_source = conn.execute(
            "SELECT j.source_tab, COUNT(*) as total FROM user_session_stats s "
            "JOIN jobs j ON j.id = s.job_id "
            f"WHERE s.user_id = ? AND s.action_type IN ({COUNTED_ACTIONS_SQL}) AND date(s.created_at) >= ? "
            "GROUP BY j.source_tab ORDER BY total DESC",
            (user_id, thirty_days_ago),
        ).fetchall()
        top_liked = conn.execute(
            "SELECT j.company, COUNT(*) as total FROM user_session_stats s "
            "JOIN jobs j ON j.id = s.job_id "
            "WHERE s.user_id = ? AND s.action_type = 'like' AND date(s.created_at) >= ? "
            "GROUP BY j.company ORDER BY total DESC LIMIT 10",
            (user_id, thirty_days_ago),
        ).fetchall()
        avg_score = conn.execute(
            "SELECT AVG(job_score) as avg_score FROM user_session_stats "
            "WHERE user_id = ? AND job_score IS NOT NULL AND job_score > 0",
            (user_id,),
        ).fetchone()[0] or 0
        action_counts = {row["action_type"]: row["total"] for row in actions}
        reviewed = sum(action_counts.get(action, 0) for action in ("like", "dislike", "unsure", "duplicate"))
        liked = action_counts.get("like", 0)
        applied = action_counts.get("apply", 0)
        ready_to_apply = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status = ?",
            (READY_STATUS,),
        ).fetchone()[0]
        queue_count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status = ?",
            (REVIEW_STATUS,),
        ).fetchone()[0]
        return {
            "daily_reviews": [dict(r) for r in daily],
            "by_track": [dict(r) for r in by_track],
            "by_source": [dict(r) for r in by_source],
            "top_liked_companies": [dict(r) for r in top_liked],
            "actions": action_counts,
            "pipeline": {
                "reviewed": reviewed,
                "liked": liked,
                "applied": applied,
                "ready_to_apply": ready_to_apply,
                "queue_count": queue_count,
            },
            # job_score is stored on the 0-100 badge scale; expose it on the
            # same 1-10 scale as jobs.relevance_score (frontend renders "/10").
            "avg_relevance_score": round(float(avg_score) / 10, 1),
            "period_days": 30,
        }
