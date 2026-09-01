# Jobhunt Local App

A lightweight Flask app for reviewing job listings in a Tinder-like workflow, tracking which ones are worth applying to, and managing follow-up state.

The app keeps data in SQLite, supports review filtering and reclassification, and exposes a small JSON API that the frontend uses for the swipe queue and application dashboard.

## What this app does

- Review jobs in a swipe-style queue
- Filter the queue by source and track
- Reclassify a job into a different track while reviewing
- Mark jobs as unsure, liked, or not interested
- Manage applications in a Ready to Apply list
- Track jobs that are awaiting response
- Keep the database schema safe for existing SQLite data

## Core workflow

1. Import or load job data into the SQLite database.
2. Open the review queue at `/review`.
3. Swipe through listings:
   - like → moves to Ready to Apply
   - dislike → marks as Not Interested
   - unsure → flags the record and removes it from review
4. Reclassify jobs by track if the suggested category is wrong.
5. Use the application manager to review, apply to, and track jobs.

## Review queue behavior

The review queue is intentionally ordered to surface jobs with more useful descriptions first.

It prioritizes jobs that have:
- a non-empty description
- a real description rather than placeholder values such as `None`, `N/A`, or very short filler text
- enough text to indicate meaningful job details

This means jobs with weak or placeholder descriptions are pushed lower in the queue than better-quality listings.

## App structure

```text
app.py
api/
  routes.py
database.py
services/
  job_service.py
static/
  css/
  js/
templates/
  applications.html
  base.html
  notifications.html
  swipe.html
jobs.sqlite3
requirements.txt
```

## Key files

- `app.py` — Flask app bootstrap and route registration
- `api/routes.py` — API endpoints used by the frontend
- `database.py` — SQLite schema creation and additive migration safety
- `services/job_service.py` — business logic for queueing, filters, swipe actions, and status updates
- `templates/swipe.html` — review queue UI
- `static/js/swipe.js` — client-side swipe/filter behavior
- `static/css/styles.css` — UI styling

## Setup

From the project root:

```bash
python -m venv jobs-env
source jobs-env/bin/activate
pip install -r requirements.txt
python app.py
```

Then open:

```text
http://127.0.0.1:5000/
```

## Routes

### Pages

- `/` — redirects to the review queue
- `/review` — swipe review page
- `/applications` — application manager
- `/notifications` — follow-up tracking page

### API

- `GET /api/review/queue` — fetch jobs in the review queue
- `GET /api/review/filter-options` — fetch distinct values for filters
- `POST /api/jobs/<id>/swipe` — like, dislike, or unsure action
- `POST /api/jobs/<id>/reclassify` — reassignment to a different track
- `GET /api/applications` — get ready-to-apply jobs
- `POST /api/jobs/<id>/apply` — mark a job as applied
- `GET /api/notifications` — list jobs awaiting response

## Database notes

The app uses SQLite via `jobs.sqlite3` and a schema managed by `database.py`.

The database layer is built to be safe for existing data:
- it creates tables if they are missing
- it adds missing columns to existing tables instead of dropping data
- it keeps SQLite compatibility with existing automation scripts

## Status values used in the app

- `Review to Apply`
- `Ready to Apply`
- `Applied`
- `Not Interested`
- `Awaiting Response`

## Development notes

This project is intentionally simple and local-first:
- no external auth
- no deployment stack
- no complex background jobs
- all functionality centers on SQLite-backed review and tracking

That makes it easy to run and extend for personal job-hunting workflows or lightweight internal tooling.

## Future improvements

Possible follow-ups include:
- saved custom filters
- exporting applications to CSV
- better job-source metadata
- richer sorting and scoring rules
- email or calendar reminders for follow-up tasks
s