# CLAUDE.md — Ochiq Kurs LMS

## Project Overview

**Ochiq Kurs** is a Django-based Learning Management System (LMS) for open online video courses in Uzbek. It features YouTube-embedded video lessons, session/progress tracking, a Telegram-based authentication flow, note-taking with Markdown, gamified streaks, and a GitHub-style activity graph.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6.0.2, Python 3.12 |
| Database | PostgreSQL |
| WSGI | Gunicorn 25.1.0 |
| Static files | WhiteNoise 6.12.0 |
| Frontend | Django Templates + vanilla JavaScript |
| Markdown | `markdown` 3.10.2 + `bleach` 6.3.0 |
| Auth | Django sessions + Telegram bot |
| Time zone | Asia/Tashkent (UTC+5) |

---

## Repository Structure

```
main-site/
├── config/               # Django project settings
│   ├── settings.py       # All settings (DB, security, static, apps)
│   ├── urls.py           # Root URL routing
│   ├── asgi.py
│   └── wsgi.py
├── users/                # User management app
│   ├── models.py         # UserProfile, TelegramAuthToken, TelegramProfile
│   ├── views.py          # Auth, profile, admin panel, YouTube API
│   ├── urls.py
│   └── forms.py
├── learning/             # Course content app
│   ├── models.py         # Course, Module, Lesson, LessonProgress, VideoSession, VideoEvent, Note
│   ├── views.py          # Course/lesson views, video session tracking
│   ├── urls.py
│   ├── forms.py
│   ├── utils.py          # Markdown rendering helper
│   └── templatetags/     # Custom filters (duration, dict_get)
├── templates/            # Django HTML templates
│   ├── base.html         # Shared layout (navbar, sidebar, footer)
│   ├── home.html
│   ├── registration/     # login.html (Telegram auth)
│   ├── learning/         # course_list, course_detail, module_detail, lesson_detail
│   └── users/            # profile, admin_panel, signup
├── static/
│   ├── css/style.css
│   └── js/
│       ├── lesson_tracker.js   # YouTube IFrame API, session events, heartbeat
│       └── lesson_notes.js     # Markdown notes, save/preview
├── .github/workflows/
│   └── deploy.yml        # CI/CD: push to master → SSH deploy
├── requirements.txt
├── Pipfile
└── .env.example
```

---

## Data Models

### Content Hierarchy: `Course → Module → Lesson`

```
Course      (title, slug, description, order)
  └─ Module (title, slug, description, course FK, order)
       └─ Lesson (title, slug, description, module FK, youtube_video_id, duration_seconds, order)
```

### Tracking Models

- **LessonProgress** — `unique_together(user, lesson)`: `is_completed`, `watched_seconds`, `last_watched_at`
- **VideoSession** — per-play-session tracking: `started_at`, `ended_at`, `last_position_seconds`, `actual_watched_seconds`, `max_reached_seconds`, `last_play_position`
- **VideoEvent** — fine-grained events: `event_type` in `(play, pause, seek, ended, speed_change, page_hidden, heartbeat)`, `position_seconds`, `metadata` (JSON)

### User Models

- **UserProfile** — OneToOne with Django User: `current_streak`, `longest_streak`, `last_activity_date`
- **TelegramAuthToken** — `token`, `created_at`, `confirmed_at`, `user` (nullable FK), `is_new_user`; expires after 10 minutes
- **TelegramProfile** — OneToOne with User: `telegram_id`, `first_name`, `last_name`, `username`, `photo_url`

---

## URL Structure

| Path | App | Description |
|---|---|---|
| `/` | — | Home page |
| `/malaka/` | learning | Course list |
| `/malaka/<course>/` | learning | Course detail |
| `/malaka/<course>/<module>/` | learning | Module detail |
| `/malaka/<course>/<module>/<lesson>/` | learning | Lesson page |
| `/malaka/<course>/<module>/<lesson>/complete/` | learning | POST: mark complete |
| `/malaka/<course>/<module>/<lesson>/note/` | learning | POST: save note (JSON) |
| `/malaka/<course>/<module>/<lesson>/session/start/` | learning | POST: start video session |
| `/malaka/<course>/<module>/<lesson>/session/event/` | learning | POST: video event |
| `/malaka/<course>/<module>/<lesson>/session/beacon/` | learning | POST: beacon (CSRF-exempt) |
| `/users/login/` | users | Telegram login (token generated) |
| `/users/signup/` | users | Same flow as login |
| `/users/profile/` | users | Profile + streak + activity graph |
| `/users/admin/` | users | Admin panel (staff only) |
| `/users/admin/bulk-create/` | users | Bulk create course tree |
| `/users/admin/fetch-playlist/` | users | YouTube playlist fetch |
| `/api/auth/confirm/` | users | Telegram bot callback |
| `/api/auth/check/<token>/` | users | Browser polling (rate-limited) |

URL namespaces: `learning:` and `users:`

---

## Authentication Flow

1. User visits `/users/login/` → server creates `TelegramAuthToken` (10-min TTL)
2. Frontend shows a Telegram bot link embedding the token
3. Browser polls `/api/auth/check/<token>/` every 2 seconds (rate-limited to 60 req/min)
4. Telegram bot POSTs to `/api/auth/confirm/` with `BOT_SECRET` header, `telegram_id`, `first_name`, etc.
5. Server confirms token, creates/updates User + TelegramProfile, logs user in via Django session
6. Browser receives confirmed status, redirects to `/malaka/`

New users get `set_unusable_password()` — Telegram-only auth by default.

---

## Key Business Logic

### Video Session Tracking
- Resume logic: if same lesson session ended < 30 minutes ago, resume it; otherwise create new session
- `last_play_position` tracks state-machine accuracy for incremental watch-time
- Auto-completion: lesson marked complete when `watched_seconds >= 0.8 * duration_seconds`
- Event throttling: heartbeat events throttled to 1-second minimum; state-critical events always processed
- Beacon API endpoint is CSRF-exempt but verifies user authentication separately

### Streak System
- Updated when a lesson is completed or reaches 80% watched
- `current_streak` = consecutive days with qualifying activity
- All streak calculations use Asia/Tashkent timezone (`datetime.now(tz=TZ).date()`)

### Notes
- One note per user per lesson (`unique_together(user, lesson)`)
- Stored as raw Markdown, rendered via `learning/utils.py` (markdown → bleach sanitization)
- Unauthenticated users see the notes panel but cannot save

### Admin Bulk Create
- Accepts nested JSON: `course → modules → lessons` with YouTube video IDs
- Auto-generates slugs from titles
- YouTube playlist fetch available for automation

---

## Environment Variables

Defined in `.env.example`. All must be set in production:

```bash
SECRET_KEY=
DEBUG=False
ALLOWED_HOSTS=yourdomain.com

DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=5432

YOUTUBE_API_KEY=
BOT_SECRET=           # Shared secret with Telegram bot
TELEGRAM_BOT_USERNAME=ochiqkurs_bot

# Production security flags
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

For local dev, copy `.env.example` to `.env` (not committed).

---

## Frontend Conventions

- **No JS framework** — vanilla JS in IIFE pattern
- Config for JS modules is injected via embedded `<script>` JSON in `lesson_detail.html`
- All AJAX uses the Fetch API with CSRF tokens from cookies
- Session storage used for video resume state between page loads
- Beacon API (`navigator.sendBeacon`) used on `visibilitychange`/`pagehidden` events
- Highlight.js used for code block syntax highlighting in lesson descriptions/notes

---

## Code Conventions

### Python
- Snake_case for variables, functions, fields
- Class-based views for standard CRUD; function-based views for complex logic
- `@login_required` for authenticated routes; `@user_passes_test(lambda u: u.is_staff or u.is_superuser)` for admin
- Migrations: always run after model changes (`python manage.py makemigrations && python manage.py migrate`)
- Markdown rendered with: `markdown.markdown(content, extensions=['fenced_code', 'tables'])` then bleach-sanitized

### Templates
- Extend `base.html`; define `{% block content %}`
- Use `{% url 'namespace:name' args %}` for all URL references
- Custom template tags live in `learning/templatetags/`

### JavaScript
- IIFE modules: `(function() { ... })();`
- Embed server config in HTML: `const CONFIG = {{ config_json|safe }};`
- All POST requests include `X-CSRFToken` header

### Database
- Use slugs for all URL routing (never expose PKs in URLs)
- Add `order` field to models that need manual ordering
- Add `unique_together` constraints to prevent duplicate user/content combinations
- Use `select_related` and `prefetch_related` when fetching nested content

---

## Development Workflow

### Setup
```bash
git clone <repo>
cd main-site
cp .env.example .env   # fill in values
pipenv install
pipenv shell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### Common Commands
```bash
python manage.py makemigrations    # after model changes
python manage.py migrate           # apply migrations
python manage.py collectstatic     # for production static files
python manage.py shell             # Django REPL
```

### No Test Suite
There are no automated tests. Manual testing is the current approach. When adding features, test manually via the browser. If adding tests, use Django's `TestCase` in `tests.py` within each app.

---

## Deployment

CI/CD via GitHub Actions (`.github/workflows/deploy.yml`):
- Triggers on push to `master`
- SSHes into the production server
- Runs: `git pull` → `pip install` → `migrate` → `collectstatic` → `systemctl restart gunicorn-ochiqkurs`

Production server: Ubuntu with Gunicorn serving the Django app. WhiteNoise handles static files.

**Do not force-push to `master`** — it triggers deployment.

---

## Security Notes

- CSRF protection on all POST forms/endpoints; CSRF-exempt only on `/session/beacon/` (uses Beacon API)
- Telegram bot callback secured by `BOT_SECRET` header check
- User-submitted Markdown is sanitized with `bleach` before rendering
- All security headers enabled: `X-Frame-Options DENY`, `SECURE_BROWSER_XSS_FILTER`, `SECURE_CONTENT_TYPE_NOSNIFF`
- Rate limiting on `/api/auth/check/<token>/` (60 req/min)

---

## Domain Language

| Term | Meaning |
|---|---|
| Course | Top-level learning track |
| Module | Section/chapter within a course |
| Lesson | Individual video lesson within a module |
| Session | A single continuous video watch session |
| Progress | Per-user per-lesson completion state |
| Streak | Consecutive days of learning activity |
| Activity | Any lesson completion or 80%+ watch |
