# Jobhunt Web App

Flask-based web application for job tracking and review.

## Visual design refresh — Design System v2 (2026-09-16)

What changed and why:

- **`static/css/styles.css`** — a "DESIGN SYSTEM v2" layer is appended at the
  end of the file (after the original ~2,100 lines). The CSS cascade makes it
  override earlier rules, so the base styles were not rewritten. It adds:
  - Design tokens: spacing scale (`--space-*`), radius scale
    (`--radius-sm/md/lg/pill`), motion (`--transition-fast/base`), accent
    gradient (`--accent-gradient`, `--accent-glow`).
  - Sidebar: gradient background, emoji nav icons, indigo left-accent bar on
    the active link, avatar + username footer, hover transforms.
  - Buttons: unified transitions, press (`scale(0.97)`), gradient primary with
    glow shadow, proper disabled state.
  - Glassmorphism page headers (`backdrop-filter: blur`), track-colored
    card left borders with hover lift, dark-theme surface refinements.
  - Toasts: slide-in animation + type icons (✅/⛔/⚠️/ℹ️) via `::before`.
  - Modals: backdrop blur + scale-in animation; energy warning gets a warm
    gradient treatment.
  - Empty state pulse, animated progress-bar fills, pill filter selects.
  - **Mobile (<768px):** the sidebar becomes a bottom tab bar, action buttons
    become a fixed bottom bar (44px touch targets), full-width toasts.
  - **Accessibility:** `:focus-visible` outlines, skip-to-content link,
    `@media (prefers-reduced-motion: reduce)` disables all animation.
- **`templates/base.html`** — skip link, `<main id="main-content">` landmark,
  emoji icons in nav links, avatar initial in the sidebar footer.
- **`templates/swipe.html`** — clean swipe page with a filter bar (location, job type, relevance score, apply type), a vertically centered card display, five action buttons (dislike, unsure, like, superdislike, undo, help), and a daily-goal/streak/badge progress strip.
- **`static/js/swipe.js`** — restored filter handling and filter-dropdown population from `/api/review/filter-options`, plus keyboard shortcuts (←/D dislike, →/L like, ↓/U unsure, S no fit, Ctrl+Z undo), touch and mouse drag swipe animation, undo, duplicate-candidate loading/merge, daily goal/streak/badge progress, and a `loadFilterOptions` call on page init.
- No new dependencies, env vars, or config keys. No backend behavior change.

How to verify: run the web test suite (`./.venv/bin/python -m unittest
discover -s tests`), boot an isolated server (`JOBHUNT_DB=/tmp/test.sqlite3`),
log in, and check `/review` renders the new sidebar/modal in both themes.
Headless-Chromium screenshots at 1280×900 verified light + dark themes with
no page errors (only the pre-existing login-page 401).

## Python auto-reload verification (2026-09-16)

`/home/gabby/Documents/projects/job-hunt/app.py` now passes
`use_reloader=True` when launched directly, independently of `FLASK_DEBUG`.
Debug mode remains controlled by the existing environment variable; no new
configuration or dependencies were added. This is Flask's development server,
not a production zero-downtime deployment mechanism.

An isolated HTTP test changed a Python route in four cases. The original
setting reloaded with debug on but not off; the edited setting reloaded in
both cases. Test script: `/tmp/prefmig/test_reloader.py`; results:
`/tmp/prefmig/reloader-results.txt`. Run with the web virtualenv Python.
These temporary test files may not survive a reboot.

The live port-5000 server was observed running as a standalone reloader
parent/child pair, not under the inactive `job-hunt-web.service`. That unit
has effective `FLASK_DEBUG=0`. No live process was manually restarted.
Python reload does not automatically refresh an already-open browser tab.


## Notifications and swipe verification

`/home/gabby/Documents/projects/job-hunt/static/js/notifications.js` corrects
notification banner string quoting so the script can parse and render jobs.
`/home/gabby/Documents/projects/job-hunt/static/css/styles.css` stacks the
four status sections as full-width rows (previously responsive columns); the
dead top tab bar was removed from `templates/notifications.html` because it
duplicated the collapsible section headers with no click handler wired up —
counts live on the headers, which stay visible so a collapsed section can
always be reopened. Populated panels open initially.

Headless Chromium verification on an isolated Flask server (port 5001) found
four panels, a populated notification card, working collapse/re-expand, and
no page errors. A Like-button action returned HTTP 200 and advanced to the
next review card with no console errors. This did not reproduce a broken
swipe backend or prove that pointer-drag swiping works in every browser; no
production database path was hard-coded and no swipe backend change was made.

Manual check: hard-refresh Notifications, confirm the four sections stack as
full-width rows with no duplicate tab bar, click a header twice and confirm
its jobs hide/reappear. On an isolated test database,
open Review, click Like and check that the next card appears and the swipe
request succeeds. Run the web regression suite with:

```sh
cd /home/gabby/Documents/projects/job-hunt
./.venv/bin/python -m unittest discover -s tests -v
```

No new application dependencies, environment variables or config keys.
Browser tooling used for verification was installed under temporary paths,
not added as an application dependency. Production services were left running.


## Overview

This is the frontend webapp for the Job Hunt Command Center. It provides a swipe-based interface for reviewing job listings, managing applications, tracking badges, and more.

The service is designed for a trusted local network. Usernames separate
preferences, badges, and personal feature data, while the core job pipeline
(`jobs.status`, applications, and notifications) is deliberately shared by
everyone using the instance. It is not a tenant-isolated hosted service.

## Tech Stack

- **Backend:** Flask 3.x (Python)
- **Database:** SQLite (shared with jobhunt-daemon)
- **Frontend:** Vanilla JavaScript with CSS custom properties for theming

## Project Structure

```
job-hunt/
├── app.py              # Flask app factory, route definitions
├── database.py         # SQLite access layer, schema migrations
├── requirements.txt    # Python dependencies (Flask>=3.0)
├── api/                # API blueprints
│   ├── __init__.py
│   ├── routes.py       # Main API endpoints (jobs, reviews, badges, etc.)
│   └── auth.py        # Auth endpoints (login, logout, preferences, regions)
├── services/           # Business logic layer
│   ├── __init__.py
│   ├── job_service.py  # Job CRUD, swipe actions, review queue
│   └── user_service.py # User accounts, sessions, badges, streaks
├── templates/          # Jinja2 HTML templates
│   ├── base.html       # Base layout with sidebar navigation
│   ├── swipe.html      # Main swipe review interface
│   ├── login.html      # Login page
│   └── ...             # Other page templates
├── static/
│   ├── css/
│   │   └── styles.css  # All styles (light/dark theme support)
│   └── js/
│       ├── common.js   # Utility functions (escapeHTML, showToast, theme)
│       ├── auth.js     # Client-side auth helpers
│       ├── nav.js      # Sidebar nav count refreshers
│       ├── swipe.js    # Main swipe review logic
│       └── ...         # Page-specific JS files
└── tests/              # Unit tests
    └── tests.md        # Test documentation
```

## Quick Start

```bash
cd /home/gabby/Documents/projects/job-hunt
source .venv/bin/activate
python app.py
```

The app runs on `http://localhost:5000` by default.

## Database

The webapp shares the SQLite database with the daemon (`jobhunt-daemon`). The database path is resolved in `database.py`:

1. `JOBHUNT_DB` environment variable (if set)
2. `/home/gabby/Documents/projects/jobs.sqlite3` (preferred)
3. Fallback candidates

The schema is defined in `shared_schema.py` (shared with the daemon) and extended in `database.py` with additive migrations.

## What's New (Phase 2 — Application Manager Upgrade)

### Application Manager (`/applications`)
- **Detail drawer** — click any row to slide in a side panel showing full description, salary range, location, and a deadline date-picker inline editor.
- **Inline deadline editing** — change `application_deadline` directly from the drawer; writes via `POST /api/jobs/<id>/deadline`.
- **Row-click drawer** — `application.js` `openDrawer()` / `closeDrawer()` with `Esc` to close and overlay click-to-close.

### Interview Prep (`/interviews`)
- **Edit / Delete** — each row has Edit (pencil) and Delete (trash) buttons; edit pre-fills the form for update via `interview_id`.
- **Prefill from job** — "Schedule interview" deep link from `/notifications` passes `job_id`; form auto-fills company and role.
- **Relative dates** — `interview_date` / `follow_up_at` show "today", "tomorrow", "in 3d" instead of raw `YYYY-MM-DD`.

### Navigation (`base.html` + `nav.js`)
- **Grouped sidebar** — sections: Review, Applications, Follow-up (Notifications + Interviews), Network (Contacts + Skills), Insights (Analytics + Profile).
- **Section headers** are non-clickable dividers; active state highlights the current page within its group.

## What's New (Phase 0+1 — De-vibe Pass)

### Swipe Review (`/review`)
- **Undo (Ctrl+Z / Cmd+Z)** — misclicks are recoverable; the last 20 swipe actions can be reverted via `/api/jobs/<id>/revert`.
- **Help modal (`?`)** — all keyboard shortcuts in one place, also reachable via the `?` button in the header.
- **Deadline urgency pill** — `card-deadline` turns orange when <3 days, red when overdue (was plain text).
- **Apply-type filter** — the review filter bar has an "Apply type" select (Easy Apply / Uses ATS / Uses AI), applied client-side like the score filter.
- **Shared rendering helpers** — `scoreBucket`, `atsBadgeHTML`, `scoreBadgeHTML`, `cleanSalaryText`, `cleanLocations`, `deadlinePillHTML` all live in `ui.js`. Page-level fallbacks only apply when `ui.js` fails to load.

### Application Manager (`/applications`)
- **Sort** by Score / Deadline / Newest / Company.
- **Filter** by apply type (Easy Apply / ATS / Uses AI).
- **Deadline highlight** — overdue rows red, urgent (≤2d) orange, soon (≤7d) amber.
- **Mark-Applied modal** — records resume used, cover letter template, date applied, and notes in one flow. Writes `submitted_resume`, `submitted_cover_letter`, `notes` columns.
- **"Skip" path** — one-click apply without the detail form.
- **Top 3 Today strip** — highest-scored, non-expired, oldest-first ready-to-apply jobs.
- **Live count** — `Applications (42)` in the nav and header.

### Regions editor (Profile → Preferences)
- **No more `prompt()`/`confirm()`** — delete is now a two-click "Delete → Confirm?" with a 2.5s timeout (matches the inline-editor style of the rest of the app).
- **Repaired (2026-09-11)** — `regions.js` had been left with a broken delete (Confirm? armed but nothing happened) and an unbalanced brace that made the whole script fail to parse, so the Regions card rendered nothing. Rewrote the mangled blocks: delete now actually calls `DELETE /api/auth/regions/<id>` on the second click, aliases render as one chip list (removable in edit mode, Enter to add), and the badge color picker is back in edit mode. Added `.region-add-form`/`.chip-remove` styles. Aliases drive the review-queue region filter (see `services/job_service.py`).

### Notifications (`/notifications`)
- **Relative dates** — "today", "tomorrow", "3d ago" instead of raw ISO.
- **Actionable cards** — "Open posting" link and "View in Interviews" deep link when an interview is scheduled.

### Job Tracks (Profile → Preferences)
- **Regions-style track editor (2026-09-11)** — each track is an editable card: display name, a **Job titles** list, and a **Keywords** list (both add-with-Enter and removable chips while editing), with two-click delete and an add-track form. Each card also shows the posting count for that track label (display-only). Stored in `user_tracks` / `user_track_terms` (mirrors `user_regions` / `user_location_aliases`), API at `/api/auth/tracks`. Seeded per user with Game Developer, Software Engineer, Data Analyst, GIS/Spatial, ML/AI (never "not a fit" — it's reserved: hidden from the list, blocked from creation/rename/delete server-side). Deleting a track removes only the editor definition — **jobs are kept**. The legacy `default_tracks` preference stays in sync so the review filter and daemon still see the same track names.
- **Relabel dropdowns (2026-09-13)** — the swipe-card track select and the Applications drawer track select list the user's **enabled editor tracks** (merged with tracks seen on queued jobs), so a track stays assignable even when no queued job carries it.
- **Review queue scoping (2026-09-13)** — the swipe review queue only offers jobs whose track is one of the user's **enabled tracks** (plus unclassified jobs, which stay swipable for assignment). Deleting or disabling a track keeps its jobs but stops them resurfacing in review; re-adding the track brings them back. Jobs the daemon auto-classified as `not a fit` also leave the queue.

### Data Layer
- `mark_applied()` service function now accepts `applied_at`, `submitted_resume`, `submitted_cover_letter`, `notes` — all written in a single `UPDATE`.
- `/api/jobs/<id>/apply` route passes the new fields through.
- **Write-behind cache for busy-DB writes (2026-09-14)** — `database.queue_write()` tries the write with a short timeout, and if the daemon holds the lock it caches the statement in memory instead of failing. A background flusher thread (`start_write_queue_flusher()`, started in `app.py`, every 5s) retries and applies cached writes once the DB is free. `set_job_archived()` is the first adopter: the Applications page archive toggle never 500s on `database is locked`, and the UI updates optimistically. See "SQLite concurrency" below.
- **Region-aware review filter** — `get_review_queue()` matches the canonical region code OR the user's own `user_location_aliases` (exact alias or city-prefix, so verbose `"Toronto, Ontario, Canada"` rows match the ON filter). "Remote" still qualifies under every filter. `/api/review/filter-options` now lists the user's enabled regions (falls back to distinct canonical values if the user has none).
- **Location migration** (`_migrate_locations.py`, run 2026-09-11) — rewrote 138 verbose `job_locations` values to canonical codes, dropped generic country-only rows, re-synced 3,073 `jobs.location` blobs. DB backup in `db_backups/`. Re-run is safe (idempotent: already-canonical values are skipped).

### UI polish
- `.table-wrap` adds horizontal overflow for tables on mobile.
- `.modal-overlay` / `.modal-card` shared by both the Help and Apply modals.
- `.deadline-overdue` / `.deadline-urgent` / `.deadline-soon` utility classes.
- Removed dead `window.openStatsModal` / `/profile?focus=stats` fallback (no longer exists).

## API Endpoints

### Auth (`/api/auth/*`)
- `POST /api/auth/login` - Log in/register user
- `POST /api/auth/logout` - Log out
- `GET /api/auth/me` - Get current user + preferences + regions
- `GET/POST /api/auth/profile/preferences` - Get/set user preferences
- `GET /api/auth/profile/stats` - Get user stats
- `GET /api/auth/profile/badges` - Get all badges (earned + locked)
- `GET /api/auth/regions` - List user regions
- `POST /api/auth/regions` - Save all regions
- `DELETE /api/auth/regions/<id>` - Delete a region

### Jobs (`/api/jobs/*`)
- `POST /api/jobs/<id>/swipe` - Apply swipe action (like/dislike/superdislike/unsure/expired)
- `POST /api/jobs/<id>/duplicate` - Mark as duplicate
- `POST /api/jobs/<id>/reclassify` - Change job track
- `POST /api/jobs/<id>/notes` - Save job notes
- `POST /api/jobs/<id>/archive` - Toggle archive
- `POST /api/jobs/<id>/apply` - Mark as applied
- `POST /api/jobs/<id>/expired` - Mark as expired (removes from active views, keeps preference)

### Review (`/api/review/*`)
- `GET /api/review/queue` - Get jobs in review queue (with filters)
- `GET /api/review/filter-options` - Get available filter options

### Other
- `GET /api/notifications` - Get notification count + list
- `GET /api/skills` - List user skills
- `POST /api/skills` - Add/update skill assessment
- `GET /api/cover-letters` - List cover letters
- `POST /api/cover-letters` - Create cover letter
- `GET /api/analytics` - Get analytics summary
- `GET /api/streak` - Get streak info
- `POST /api/streak/freeze` - Use a streak freeze

## Known Issues

### Fixed: Swipe.js initialization missing handlers when DOM already loaded

**Issue:** When the page loads and `document.readyState` is already `'loading'` complete (not `'loading'`), the `else` branch in the initialization code was missing several handler bindings:
- `bindCardButtons()` - Archive button in job cards
- `bindTouchSwipe()` - Touch swipe gestures on mobile
- `bindEnergyWarning()` - Energy limit acknowledgment button

This caused the swipe interface to appear broken on page load - buttons wouldn't work, touch swipes wouldn't register, and the energy warning couldn't be dismissed.

**Fix:** Added the missing initialization calls to the `else` branch (lines 619-623 in `swipe.js`).

**Verification:** 
1. Load the app in a browser
2. The swipe buttons (Like, Dislike, etc.) should respond to clicks
3. On mobile, swiping left/right on job cards should trigger actions
4. If you hit your daily review limit, the energy warning button should dismiss the warning

### Added: ATS indicator on Swipe + Applications

**Feature:** Each job now carries `uses_ats` / `ats_name` / `apply_type`,
computed heuristically in `shared_schema.detect_ats()` from the posting
`link` + `description` (no schema migration, no network calls). Known ATS
domains (Greenhouse, Lever, Workday, Taleo, iCIMS, …) → `🤖 ATS · <Name>`;
`Easy Apply` in the description → `⚡ Easy Apply` (no external ATS);
otherwise `❔ ATS unknown`.

**Files changed:**
- `../shared_schema.py` - Added `ATS_SIGNATURES`, `EASY_APPLY_PHRASES`, `detect_ats()`
- `database.py` - Re-exported `detect_ats`
- `services/job_service.py` - `_job_row_to_dict()` enriches every job (review queue + applications) with the three ATS fields
- `static/js/swipe.js` - `atsBadge()` rendered in the card header next to the score
- `static/js/application.js` + `templates/applications.html` - New `ATS` table column with the same badge
- `static/css/styles.css` - `.ats-badge` / `.ats-yes` / `.ats-no` / `.ats-unknown` styles
- `tests/test_database_config.py` - `AtsDetectionTests` + queue/applications enrichment test

**Verification:**
1. `./.venv/bin/python -m unittest tests.test_database_config -v` — all pass
2. Open `/review` — each card header shows the ATS badge beside the score
3. Open `/applications` — each row shows the ATS badge in the new ATS column

### Added: Uses-AI hiring marker + Apply-type filter options

**Feature:** Alongside the ATS badge, each job now carries `uses_ai` /
`ai_signal`, computed heuristically in `shared_schema.detect_ai_hiring()` from
the posting `link` + `description` (no schema migration, no network calls).
Signatures are hiring-funnel-only — HireVue, Spark Hire, Modern Hire,
VidCruiter, Talview, Paradox, one-way/on-demand video interviews, "AI-powered
screening/matching/recruiting/hiring", "our AI will review", automated resume
screening, Citi-style "automated processing, including artificial
intelligence" footers — so postings for AI *roles* ("AI Engineer",
"experience with artificial intelligence") never trigger it. Beyond the
substring table, a sentence-level pass catches the many disclosure phrasings
("may use AI tools to aid the screening…", "AI is used in a portion of our
upfront screening process", "AI notetakers", "LinkedIn Hiring Assistant")
via use-word + AI-word + hiring-funnel-noun triples, while employer denials
("We do not use AI…", "AI is not used … at this time") — which take
precedence posting-wide, since a denial sentence can share keywords with
role-AI sentences that trip the generic triple — and scraped LinkedIn
chrome ("Use AI to assess how you fit") are explicitly excluded. Matched jobs show `🧠 AI hiring`
(tooltip names the signal) next to the ATS badge on Swipe cards, in the
Applications ATS column, and in the Top-3 strip. The Apply-type filter gains a
**Uses AI** option on both `/applications` and the `/review` filter bar
(Easy Apply / Uses ATS / Uses AI).

**Files changed:**
- `../shared_schema.py` — Added `AI_HIRING_SIGNATURES`, `detect_ai_hiring()`
- `database.py` — Re-exported `detect_ai_hiring`
- `services/job_service.py` — `_job_row_to_dict()` enriches every job with `uses_ai` / `ai_signal`
- `static/js/ui.js` — `aiBadgeHTML()` appended by `atsBadgeHTML()`
- `static/js/swipe.js` — fallback badge + Apply-type filter (filter state, `getFilterValues`, `applyAtsFilter`, change/clear bindings)
- `static/js/application.js` — fallback badge + `uses_ai` filter branch; removed dead `state.prefs` duplicate
- `templates/swipe.html` — "Apply type" filter group in the review filter bar
- `templates/applications.html` — "Uses AI (hiring)" option in the Apply-type filter
- `static/css/styles.css` — `.ats-ai` badge style (amber)
- `tests/test_database_config.py` — `AiHiringDetectionTests` + `test_queue_and_applications_carry_uses_ai`

**Verification:**
1. `./.venv/bin/python -m unittest tests.test_database_config -v` — all pass (now 21 tests)
2. Open `/review` → ⚙ Filters → Apply type "Uses AI" — only AI-hiring postings remain
3. Open `/applications` → Apply type "Uses AI (hiring)" — same, plus the 🧠 badge in the ATS column

### Fixed: applications.js SyntaxError + double-loaded shared scripts

**Symptoms (Firefox console):** `missing } in template string application.js:24`
→ `ReferenceError: loadApplications is not defined`; plus
`redeclaration of const THEME_KEY` (common.js) and `redeclaration of let
_currentUser` (auth.js).

**Root causes:**
1. The `🧠 AI hiring` fallback badges added in `swipe.js` / `application.js`
   had an unbalanced paren inside a nested template literal
   (`escapeHTML(String(job.ai_signal)))` — three `)` for two `(`). A parse
   error kills the whole file, hence the missing `loadApplications`.
2. `applications.html` re-included `common.js` / `auth.js` / `api.js`, which
   `base.html` already loads. Top-level `const`/`let` (`THEME_KEY`,
   `_currentUser`) throw "redeclaration" when a classic script evaluates
   twice. `api.js`/`nav.js` only declare functions, so their double load was
   harmless.

**Fixes:**
- Rewrote both fallback badges to precompute the tooltip title string
  (`aiTitle`) — no nested template literals left to mis-nest.
- `applications.html` now includes only `application.js`; shared scripts come
  from `base.html` alone. (`login.html` is standalone and keeps its own
  `common.js` include — verified.)

**Verification:** balance check on all shared/page scripts passes (parens,
braces, brackets, backticks); 17/17 unit tests; hard-refresh the browser
(Firefox caches JS) and the console is clean.

### Added: Mark as Expired for Applications

**Feature:** Added a new "Expired" button in the Application Manager that:
- Marks the job as `Passed` status
- Sets `passed_at` timestamp
- Removes the job from the applications list
- Keeps the like/dislike preference intact (preserving your swiping history)
- Awards badges for the "expired" action

**Files changed:**
- `services/job_service.py` - Added `mark_expired()` function
- `api/routes.py` - Added `POST /api/jobs/<id>/expired` endpoint
- `templates/applications.html` - No changes (JS renders the button)
- `static/js/application.js` - Added `markExpired()` function and event handler

**Verification:**
1. Go to `/applications` page
2. Each job row now has an "Expired" button next to "Mark as Applied"
3. Clicking it removes the job from the list with a toast notification
4. The job is not deleted - it's just marked as passed and hidden from active views

### Changed: Preferences + Badges merged under the Profile page

**Issue:** Badges and Preferences were two separate pages with their own sidebar
entries, and the Badges page showed numeric earned/locked counts.

**Fix:**
- New `/profile` page (`templates/profile.html`) hosts **Job Search Preferences**
  and **Badges** as sub-sections switchable via an in-page sub-menu (pill tabs).
- The sub-menu has two items — "Job Search Preferences" and "Badges". Clicking one
  shows that section (the other is hidden), so each acts like its own sub-page.
- Deep links work via URL hash: `/profile#preferences` (default) or
  `/profile#badges`.
- Sidebar shows a single **Profile** link (no separate Preferences/Badges items).
- `/preferences` and `/badges` now redirect to `/profile` (old links still work).
- Removed numeric badge counts from the UI:
  - The "X earned / Y locked" summary pills are gone.
  - `badges.js` no longer renders counts or "X of Y earned" — just the badge cards.
  - `nav.js` no longer fetches/renders a badge-count pill in the sidebar (kept the
    notifications count).

**Files changed:**
- `templates/profile.html` — new combined page with a profile sub-menu and two
  switchable sections (preferences + badges)
- `static/js/profile.js` — new: sub-menu tab switching + `#hash` deep links
- `app.py` — added `/profile` route; `/preferences` and `/badges` redirect to it
- `templates/base.html` — single Profile nav link, removed badge-count pill
- `static/js/nav.js` — dropped badge count refresh (notifications only)
- `static/js/badges.js` — removed earned/locked count rendering
- `static/js/swipe.js` — `i` shortcut fallback now points at `/profile?focus=stats`
- `static/css/styles.css` — added `.profile-tabs`, `.profile-tab`, and
  `.profile-section` / `.profile-section-header`

**Verification:**
1. Go to `/profile` — sub-menu tabs render ("Job Search Preferences" active by
   default). Click "Badges" to switch; click back to switch again.
2. Sidebar shows Profile (no separate Preferences/Badges entries, no badge number).
3. `/preferences` and `/badges` redirect to `/profile`.
4. `/profile#badges` opens directly on the Badges sub-section.
5. Badge cards render with no numeric counts.

### Fixed: "Mark as Expired" button in the swipe menu

**Issue:** The "Expired" (⏰/E) button in the review swipe menu threw a 409 error
(`Preference must be 'liked', 'disliked', or 'superdisliked'`), so clicking it did
nothing. The direct Application Manager endpoint (`POST /api/jobs/<id>/expired`)
worked fine because it uses `mark_expired()`, but the swipe menu sends
`action: 'expired'` through the generic swipe route, which calls
`apply_swipe_action()`.

**Root cause:** `apply_swipe_action()` unconditionally called
`_record_job_preference(conn, job_id, preference, ...)` even for
`expired`/`duplicate`, whose `preference` is `None`. That helper rejects anything
other than `liked`/`disliked`/`superdisliked`, so the whole swipe (including the
status UPDATE, which runs in the same uncommitted transaction) was rolled back.

**Fix:** In `services/job_service.py`, `apply_swipe_action()` now:
- Only writes a preference row when `preference is not None` (like/dislike/superdislike).
- Sets `passed_at = CURRENT_TIMESTAMP` for `expired`, matching `mark_expired()` semantics.

**Verification:**
1. Open the swipe review page (`/review`)
2. Click the ⏰ Expired button (or press `E`) on a card
3. The card animates out and the job's status becomes `Passed` (`passed_at` timestamped)
4. No preference row is written for never-swiped jobs (prior like/dislike history is preserved)

### Fixed: Not a Fit (Superdislike) now updates track to "not a fit"

**Issue:** The "Not a Fit" (superdislike) button only marked the preference as superdisliked but didn't change the job's track.

**Fix:** Modified `apply_swipe_action()` in `job_service.py` to set `track = 'not a fit'` when superdislike is used. This helps filter out jobs that aren't suitable for your career path.

**Verification:**
1. Swipe left on a job and select "Not a Fit" (or press S)
2. Check the job's track - it should now show "not a fit"
3. The job will be filtered out from future review if you filter by track

### Changed: Notifications now show email responses

**Issue:** Notifications were showing "unsure" jobs instead of email responses from companies.

**Fix:** Modified `get_notifications()` in `job_service.py` to return jobs with email response statuses:
- `Interviewing` - Company wants to schedule an interview
- `Rejected` - Application was rejected
(Unsure/Awaiting Response jobs are excluded — the daemon rescrapes those and returns them to `Review to Apply`.)

The email tracker (`jobhunt-daemon/mail_tracker/tracker.py`) updates job statuses when it detects responses from company emails.

**Verification:** 
1. Run the email tracker: `jobs_tool.py email` (in jobhunt-daemon)
2. Go to `/notifications` page
3. You should see your applied jobs; those with employer replies show an email badge and link
4. The banner shows count of active alerts needing attention

### Fixed: Distorted salaries + unbounded location blobs

**Issue:** Scraped rows stored garbage pay strings like `None-None None` and
location strings that grew into unbounded comma-joined blobs
(`Scarborough, Ontario, Canada, Toronto, Ontario, Canada, ...` repeated).

**Root causes:**
- `fetcher.py` built `jobs.salary` with an f-string that stringifies
  `None`/`NaN` amounts into `None-None None`.
- Similar-job merges (daemon `fetcher.py` + webapp `merge_duplicate_jobs`)
  appended raw un-normalized location strings on every merge and deduped on
  case only, so the blob grew per merge. `normalize_location` echoed unknown
  fragments (`Canada`, `Scarborough`) unchanged.

**Fixes:**
- `shared_schema.format_salary()` — junk-safe, renders `$50,000 - $70,000 USD` /
  `From $50,000 USD` / `Up to $70,000 USD`, `""` when no usable amounts.
- `normalize_location` fallback — collapses pure-country/generic fragments to
  `""`, keeps `Remote` as a preserved wildcard token; merges now normalize
  before dedupe so `jobs.location` stays a canonical comma-join.
- Display backstops in `swipe.js` / `application.js` hide `/none|nan/i` or
  empty pay strings and dedupe location lists client-side.
- Review queue location filter matches the canonical code OR `Remote`
  (wildcard — remote jobs appear under every region filter).
- Redundant prefs merged: Locations card folded into Regions (single location
  editor, `default_locations` accepted-but-ignored); Job Types folded into
  Job Tracks (`default_job_types` accepted-but-ignored); Preferred Keywords
  folded into Keywords (`preferred_keywords` accepted-but-ignored). Columns
  kept in the schema (additive-only rule) but no longer read/written.

**One-off cleanup (already run):**
```bash
cd /home/gabby/Documents/projects/job-hunt
./.venv/bin/python scripts/clean_data.py --dry-run   # preview counts
./.venv/bin/python scripts/clean_data.py             # apply (idempotent)
```
Applied results: 2622 garbage salary rows blanked, 1905 location rows/blobs
collapsed to canonical codes, re-run dry-run reports 0 (idempotent).

**Verification:**
1. `./.venv/bin/python -m unittest tests.test_database_config` — all pass
2. Open `/review` or `/applications` — no `None-None None` pay strings, no
   mega-blob locations (canonical codes or `Location not listed`)
3. `scripts/clean_data.py --dry-run` reports 0 for salaries/locations

## What's New (Phase 3 — Cover Letters & Final Polish)

### Cover Letters (`/cover-letters`)
- **Template manager** — create, preview, copy-to-clipboard, and delete reusable cover letter templates.
- **Placeholders** — use `{{company}}` and `{{role}}` in templates; swap in values when applying from the Application Manager drawer.
- **Card grid layout** — `cover-letters.js` renders each template as a card with 160-char preview and action buttons.

### Application Manager Drawer — Cover Letter Picker
- When marking a job as applied via the drawer, the cover letter dropdown lists saved templates; selecting one auto-fills the `submitted_cover_letter` column.

### Contacts
- **Edit & Delete** — each row has Edit and Delete actions; edit pre-fills the form for update.
- **Search** — filter contacts by name, company, role, or notes.

### Skills (`/skills`)
- **Delete** — each skill row has a Delete action. `DELETE /api/skills/<name>` is
  backed by `user_service.delete_skill_assessment()`; previously the route called
  a function that didn't exist, so every delete returned 500.
- **Your input is only Self rating + notes** — the manual Market Demand dropdown
  was removed. Demand is computed into `skill_assessments.demand_auto` /
  `demand_job_count` / `demand_updated_at` (additive columns), and the table
  shows Demand (auto), Matching Jobs, and Gap = self − demand. `market_demand`
  stays in the schema but is no longer read/written by the UI.
- **Demand is never blank** — saving a skill recomputes its demand immediately
  (same matcher as the daemon: `shared_schema.count_skill_job_matches`), so a
  new skill like "AI" shows ~500 matching jobs the second it's saved instead of
  waiting up to 24h for the daemon cycle. A skill with zero matches shows
  **1/5** (lowest demand), never "0/5".
- **Smart matching** — besides the plain token ("Python", "C++", ".NET"), the
  matcher also catches dotted acronyms ("A.I."), concatenated/camelCase forms
  ("OpenAI", "GenAI"), and written-out aliases ("artificial intelligence" for
  AI, "machine learning" for ML, "geographic information system" for GIS) while
  excluding words that merely contain the letters ("training" ≠ AI).
- **Rename-safe edits** — if you edit a row and change its name, `skills.js`
  deletes the old-name row after the upsert so no duplicate lingers.
- **Hardened JS** — render/event wiring runs inside a DOMContentLoaded-guarded
  `initSkillsPage()`, element lookups are null-guarded, and the delete path
  surfaces the server's `data.error` instead of a generic "Failed to delete".

### Verification (re-verified 2026-09-14)
- Flask boots with **51 route paths (61 endpoints)**, no import errors.
- Skills API: `POST /api/skills` 200, `GET /api/skills` exposes `demand_auto`,
  `DELETE /api/skills/<name>` 200 `{"ok": true}`, repeat delete → 404.
- `python -m unittest tests.test_database_config` — 19 tests pass.
- All JS files parse without syntax errors.

## What's New (Phase 4 — Daemon-Computed Skills & Lock Fixes)

### SQLite concurrency alignment
- `database.get_connection()` now matches the daemon:
  `timeout=60`, `PRAGMA busy_timeout=30000`, `journal_mode=WAL`,
  `synchronous=NORMAL`. Previously the webapp used `timeout=5` with no
  busy_timeout, so any write that raced the daemon's long transactions died
  with `database is locked` (and the daemon logged the same error from its
  side). Both sides now wait on the lock instead of failing.
- **Durable pending-write side store (2026-09-14)** — waiting is not enough when the daemon
  holds the lock for a whole scrape run, and an in-memory queue loses writes when the web app
  restarts. Blocked writes are now staged in `web_pending_writes.sqlite3`, a tiny SEPARATE SQLite
  file the daemon never locks, via `pending_writes.py` (shared by both processes). Last write
  wins: one row per (target_table, row_key), so repeated toggles collapse instead of
  contradicting. Web reads overlay staged values (`_job_row_to_dict` for all staged
  job columns via `overlay_job_pending`, `get_user_preferences` for prefs) so the UI
  always reflects latest intent — the side store wins on contradiction.
  `database.queue_write()` keeps a fast 2s attempt and returns True=staged / False=applied;
  drained by the web flusher thread (5s) AND the daemon each cycle
  (`DaemonLoop._pending_drain`). Supported staged job columns beyond `archived`:
  status/notes/track/application_deadline/interview_date/follow_up_sent/salary_offered/
  applied_at/submitted_*/passed_at/unsure/is_modified/preference_added/
  not_interested_checked (services route `set_job_deadline` and `reclassify_job_track`
  through `queue_write` too). Verified end-to-end: with the DB write-locked,
  `POST /api/jobs/<id>/archive` returns 200 (`queued: true`), the side store holds the write,
  and after the lock is released the flusher/daemon applies it and clears the staged row.
- `app.py` calls the new `database.ensure_skill_demand_columns()` at import
  (idempotent ALTER-only) so `GET /api/skills` never selects a missing column.

### Skills page
- See the Skills section above — self-rating-only input model, delete fix,
  rename-safe edits, and a hardened `skills.js`.

## Environment Variables

- `FLASK_DEBUG` - Set to `0`, `false`, or `False` to disable debug mode (default: enabled)
- `JOBHUNT_DB` - Override the SQLite database path

## Keyboard Shortcuts (Review Page)

| Key | Action |
|-----|--------|
| `←` / `d` | Dislike |
| `→` / `l` | Like |
| `s` | Superdislike (Not a Fit) |
| `u` | Unsure (skip) |
| `x` | Mark duplicate |
| `e` | Mark expired |
| `r` | Refresh queue |
| `Ctrl+Z` | Undo last action |
| `?` | Show this help |

## Sessions

Sessions are stored in the `_sessions` table in SQLite. The session cookie name is `jh_session` with a 30-day TTL.
