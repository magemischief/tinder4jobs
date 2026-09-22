# Maintenance Log
# Maintenance Log

## 2026-09-16 — Fixed: web flusher crash-loop (`drain_write_queue` NameError)

**Symptom:** web app felt down/flaky; `logs/webapp.log` spammed
`NameError: name 'drain_write_queue' is not defined` every 5 seconds from the
write-queue flusher thread, and staged side-store writes never drained from
the web side.

**Root cause:** a botched edit had eaten the `def drain_write_queue():` line
in `job-hunt/database.py` — the drain body (docstring + `_ensure_pending_store()`
+ `pending_writes.drain_pending(DB_PATH, conn)`) was glued onto the end of
`locked_connection` as dead code. The flusher then called the now-undefined
name; `locked_connection` silently ran a full drain as a side effect on every
exit.

**Fix:** restored the missing `def drain_write_queue():` line before the
docstring (single-line insert; `locked_connection` ends at
`pending_writes.invalidate_overlay()` again). Verified: module imports, both
functions callable at module level, `locked_connection` still a generator
function, direct `drain_write_queue()` call returns 0 with an empty side
store, zero flusher errors since restart.

**How to verify:** `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/login`
→ 200; `tail logs/webapp.log` shows no `NameError`; side store
`web_pending_writes.sqlite3` stays at 0 rows after actions.



## 2026-09-16 — Purge of unnecessary files (~4.9G freed)

- `db_backups/`: deleted the Sep-2 3.3G pre-cleanup copy (`jobs.sqlite3`) and
  the Sep-11 pre-location-migration backup; per the daemon's keep=2 policy the
  two newest remain (Sep-13 `prerclassify`, Sep-14 daily).
- `job-hunt/job-env/` deleted (303M dead venv; zero code/unit references —
  `.venv` is the real web venv; README commands updated).
- `credentials.json` deleted from both worktrees (unreferenced GCP
  service-account key — see Secrets note above; revoke the key in GCP).
- Stale debris: `job-hunt/jobs_dev.sqlite`, stale Aug-27 copies of
  `daemon_state.json` / `linkedin_state.json` (live ones are in
  `jobhunt-daemon/`), empty `migrations/` dir, one-off migration/inspection
  scripts (`_backfill_track_colors.py`, `_fix_tracks_color2.py`, `_inspect.py`,
  `_inspect_regions.py`, `_migrate_locations.py`, `verify_fields.py` — all
  migrations already applied and re-applied idempotently by `init_db()`).
- Caches/logs: all non-venv `__pycache__/`, rotated `jobs_tool.log.[12]`,
  `/tmp/{web,daemon}-freeze.txt`; 1.0M `webapp.log` truncated (file kept —
  it is held open by the web service).
- **Kept deliberately:** `blacklist.config`, `writing_samples.txt`,
  `Gabriel_Joakim_Resume.pdf` (user data), `apps/www/src/components/Swap.tsx`
  + `src/lib.ts` (untracked React experiment — say the word and they go too).

## 2026-09-16 — Hardening pass (web + daemon)

### Secrets (critical)
- `jobhunt-daemon/config.ini`: `EMAIL_ACCOUNT`/`EMAIL_APP_PASSWORD` blanked.
- New `jobhunt-daemon/secrets.env` (chmod 600, gitignored) holds
  `JOBHUNT_EMAIL_ACCOUNT` / `JOBHUNT_EMAIL_PASSWORD`. Loaded by
  `job-hunt-daemon.service` via `EnvironmentFile`; `core/config.py` `_secret()`
  reads the env vars with config.ini as fallback.
- **Action needed:** rotate the Gmail app password (it was in git history) at
  https://myaccount.google.com/apppasswords, then update `secrets.env`.
- `job-hunt/scripts/config.ini` untracked from git (`git rm --cached`).
- `credentials.json` removed from both worktrees (2026-09-16 purge; no code
  referenced it). The underlying GCP service-account key (project
  `sinuous-photon-390413`) is still valid in Google Cloud — revoke it under
  IAM & Admin → Service Accounts → Keys, since it sat unencrypted on disk.

### Watchdog
- `job-hunt-watchdog.service` `ExecStart` fixed (was pointing at a non-existent
  `job-hunt/scripts/watchdog.sh` → 203/EXEC crash loop).
- `jobhunt-daemon/watchdog.sh` now watches all daemon source dirs
  (core/ daemon/ fetching/ scraping/ processing/ mail_tracker/ state/ cli/)
  instead of only `jobs_tool.py`, so Python edits actually restart the daemon.

### Durability (pending-write side store)
- All web job mutators now route through `queue_write` (apply-when-free,
  stage-under-lock): `mark_job_status`, `mark_expired`, `revert_last_action`,
  `reclassify_job_track`, `set_job_deadline`, `set_job_archived`, `save_job_notes`,
  `mark_applied`. Previously only archive/deadline/reclassify were durable —
  contacts/interviews/notes writes could 500 under a daemon lock hold.
- `pending_writes.apply_pending_write` gained a `__raw__` branch: verbatim DML
  replay for non-overlay tables. Guards: single statement, INSERT/UPDATE/DELETE
  only, no DDL — a poisoned row can't drop tables or run multi-statement SQL.
  Staged raw ops were previously poison-dropped (data loss).
- Daemon `_pending_drain` now drains chunk-by-chunk (short lock per op via
  `make_sqlite_executor`) instead of one long `write_connection` transaction
  that blocked fetch/scrape writers. Hard cap ~5000 ops per cycle.

### Notification counts
- `get_notification_counts` fixed: stale Rejected jobs were counted forever
  because the freshness check used `OR` between `updated_at` and
  `email_received_at` conditions — either being NULL made the job "fresh".
  Now requires both to be recent (`AND`).
- `get_notifications` still intentionally mutates `unsure=1` on read (page
  semantics: read = triaged). Left as-is per user decision.

### DB / paths
- Deleted the 0-byte `job-hunt/jobs.sqlite3` stub. `database.py._resolve_db_path`
  now resolves only the canonical `/home/gabby/Documents/projects/jobs.sqlite3`
  (or `JOBHUNT_DB` env) and **raises** if missing instead of silently booting
  on an old backup (split-brain vs the daemon).

### Clocks
- All `datetime.utcnow()` replaced with `datetime.now(timezone.utc)` (daemon
  loop active-hours math, passed_checker stamps, user_service). DB stays naive;
  stamps are naive-UTC to match `CURRENT_TIMESTAMP` storage.

### Web app exposure / auth
- `app.run` binds `127.0.0.1` only (was 0.0.0.0 — no password/CSRF, so LAN
  exposure handed over the whole DB). Reloader now follows `FLASK_DEBUG`
  (prod unit sets 0; always-on reloader forked twice and confused systemd).
- Auth is still username-only (`get_or_create_user`) — acceptable for a
  localhost-only single-user tool; revisit before ever exposing it.

### Daemon shutdown
- `DaemonLoop.shutdown` waits 30s per pipeline (was 300s × 7 = 35 min worst
  case) and uses `cancel_futures=True`.

### Misc
- `skill_demand._write_with_retry`: removed double `commit()` inside
  `write_connection` (which already commits on clean exit).
- Deleted dead duplicate `get_notification_counts` (lines ~102-146).

### Requirements
- Both `requirements.txt` files now fully pinned to the freeze of their
  deployed venvs (web `.venv`, daemon `jobdaemon-venv`).

### Testing / verification
- `jobhunt-daemon/tests/test_write_queue.py` — 8/8 pass.
- `job-hunt/tests/test_database_config.py` — 21/21 pass.
- All three services active after `daemon-reload` + restart: daemon cycles
  clean (drain ran, pipelines scheduled, sleeping normally), web serves
  (`/` → 302 → login 200 on 127.0.0.1:5000).
- Still no tests covering `pending_writes` raw replay or notification counts —
  worth adding next.

### Known remaining (accepted / follow-up)
- DB is ~1.3 GB (user declined the DB-size work this pass); `compact_database`
  VACUUM threshold stays at 1.5 GB.
- Gmail app password is still in LOCAL-only git refs (old `scripts/config.ini`
  via reflog / Cline checkpoints) — rotate it; origin never received it.
- Both repos were committed and pushed 2026-09-22 — see the sync entry below.


## 2026-09-22 — Repo sync push (both repos, current code)

- `jobhunt-daemon`: pushed as `f33f64a` (52 files: write queue, `rules/`, new
  CLI commands, dead-module drops). `secrets.env`, `config.ini`, `*.json` state
  and logs stayed gitignored; push payload scanned clean (no secrets, no
  conflict markers).
- `job-hunt`: a stale in-progress pull merge was finalized by rebuilding the
  commit on top of `origin/main` (identical tree, single parent) so only the
  current code ships. The old local commit `3634327` ("inital commit for sub
  repository"), which ADDED `scripts/config.ini` (Gmail app password +
  Gemini key), was deliberately not pushed. Verified:
  `git log origin/main..HEAD -- scripts/config.ini` → empty;
  `git ls-tree -r HEAD --name-only | grep config.ini` → empty;
  origin's history never contained the file.
- Left untracked on purpose (one-off scratch): `job-hunt/_check_syntax.py` and
  `jobhunt-daemon/{fix_all_modules,fix_main,test_imports,verify_swipe_ai_tmp}.py`.
- Still local-only and holding the old secret: reflog + the 23
  `refs/cline/checkpoints/*` commits. Gmail app-password rotation still
  pending (see Secrets note above).
- How to verify: `git status -sb` in both repos shows a clean tree apart from
  the scratch files; `git log --oneline -3` in `job-hunt` ends at
  `Seperate from daemon` → root (`Web app`).
