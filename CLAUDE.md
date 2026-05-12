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
| Images | Pillow 12.1.1 (course thumbnails) |
| Time zone | Asia/Tashkent (UTC+5) |

---

## Repository Structure

```
opencourse/                          # Repository root (also Django project root)
├── config/                          # Django project settings
│   ├── settings.py                  # All settings (DB, security, static, apps)
│   ├── urls.py                      # Root URL routing
│   ├── asgi.py
│   └── wsgi.py
├── users/                           # User management app
│   ├── models.py                    # UserProfile, TelegramAuthToken, TelegramProfile
│   ├── views.py                     # Auth, profile, admin panel, YouTube API
│   ├── urls.py
│   ├── forms.py
│   └── migrations/
├── learning/                        # Course content app
│   ├── models.py                    # Course, Module, Lesson, LessonProgress, VideoSession, VideoEvent, Note
│   ├── views.py                     # Course/lesson views, video session tracking
│   ├── urls.py
│   ├── forms.py
│   ├── utils.py                     # Markdown rendering helper
│   ├── admin.py
│   ├── templatetags/
│   │   └── learning_extras.py       # Custom filters (duration, dict_get)
│   ├── management/commands/
│   │   └── fill_durations.py        # Populates lesson duration_seconds from YouTube API
│   └── migrations/
├── templates/                       # Django HTML templates
│   ├── base.html                    # Shared layout (navbar, sidebar, footer)
│   ├── home.html
│   ├── registration/login.html      # Telegram auth page
│   ├── learning/                    # course_list, course_detail, module_detail, lesson_detail
│   └── users/                       # profile, admin_panel, signup
├── static/
│   ├── css/style.css
│   └── js/
│       ├── lesson_tracker.js        # YouTube IFrame API: record one view per play, mark complete
│       ├── lesson_notes.js          # Markdown notes, save/preview
│       ├── ui.js                    # Theme toggle, user dropdown, mobile drawer
│       └── search.js                # Debounced navbar search suggestions
├── playlist-fetcher/
│   └── fetcher.py                   # Standalone YouTube playlist fetching utility
├── .github/workflows/
│   └── deploy.yml                   # CI/CD: push to master → SSH deploy
├── manage.py
├── requirements.txt
├── Pipfile
├── .env.example
└── README.md
```

---

## Data Models

### Content Hierarchy: `Course → Module → Lesson`

```
Course      (title, slug, subtitle, description, thumbnail, category FK,
             level, language, instructor FK, instructor_name, instructor_bio,
             what_you_learn, requirements, is_featured, avg_rating,
             rating_count, order)
  └─ Module (title, slug, description, course FK, order)
       └─ Lesson (title, slug, description, module FK, youtube_video_id,
                  duration_seconds, is_preview, order)
```

- **Course.thumbnail** — optional `ImageField` (uploaded to `course_thumbnails/`). Falls back to YouTube thumbnail of the first lesson via `get_thumbnail_url()`.
- **Course.what_you_learn** / **Course.requirements** — newline-separated text blobs, surfaced as Python lists via `.what_you_learn_list` and `.requirements_list` for templates.
- **Course.avg_rating** / **Course.rating_count** — denormalised aggregates; recomputed by `course.update_rating()` after each review save.
- **Course.instructor_display()** — returns `instructor_name`, else the linked User's full name, else `"Ochiq kurs jamoasi"`.

### Discovery & Catalog Models

- **Category** — `name`, `slug` (unique), `description`, `icon` (Lucide name), `color`, `order`. `Course.category` is a nullable FK.

### Tracking Models

- **LessonProgress** — `unique_together(user, lesson)`: `is_completed`, `last_watched_at`. Manual "Tugatildi" click OR auto-set the first time a user plays a lesson.
- **LessonView** — `unique_together(user, lesson, viewed_on)`: one row per user per lesson per **day** (Asia/Tashkent). Sole driver of the activity heatmap and streak. Created by the `record_view` endpoint when the YouTube player fires its `PLAYING` state.

### Engagement Models

- **Enrollment** — `unique_together(user, course)`: lightweight "My Learning" marker. Auto-created on first lesson visit; also creatable via the explicit "Yozilish" button on the course page.
- **CourseReview** — `unique_together(user, course)`: `rating` (1–5), `comment`. Saving calls `course.update_rating()`.
- **Certificate** — `unique_together(user, course)`: `code` (unique slug), `issued_at`. Auto-issued when every lesson in the course has `LessonProgress.is_completed=True` (checked from both `record_view` and `mark_lesson_complete`).

### User Models

- **UserProfile** — OneToOne with Django User: `current_streak`, `longest_streak`, `last_activity_date`
- **TelegramAuthToken** — `token`, `created_at`, `confirmed_at`, `user` (nullable FK), `is_new_user`; expires after 10 minutes
- **TelegramProfile** — OneToOne with User: `telegram_id`, `first_name`, `last_name`, `username`, `photo_url`

---

## URL Structure

| Path | App | Description |
|---|---|---|
| `/` | — | Home page (hero, featured courses, categories, testimonials) |
| `/malaka/` | learning | Course list with category/level/sort filters |
| `/malaka/qidiruv/` | learning | Search (HTML; `?format=json` returns suggestions for the navbar) |
| `/malaka/kategoriya/<slug>/` | learning | Courses inside a category |
| `/malaka/<course>/` | learning | Course detail (tabbed: Umumiy / Dastur / Sharhlar / O'qituvchi) |
| `/malaka/<course>/yozilish/` | learning | POST: enroll in course |
| `/malaka/<course>/sharh/` | learning | POST: create or update review |
| `/malaka/<course>/sertifikat/` | learning | Printable certificate page (auto-issues if all lessons complete) |
| `/malaka/<course>/<module>/` | learning | Module detail |
| `/malaka/<course>/<module>/<lesson>/` | learning | Lesson page |
| `/malaka/<course>/<module>/<lesson>/complete/` | learning | POST: mark complete (manual) |
| `/malaka/<course>/<module>/<lesson>/note/` | learning | POST: save note (JSON) |
| `/malaka/<course>/<module>/<lesson>/davom/korildi/` | learning | POST: record a daily LessonView (fired from JS on YT `PLAYING`) |
| `/users/login/` | users | Telegram login (token generated) |
| `/users/signup/` | users | Same flow as login |
| `/users/profile/` | users | Dashboard (streak, stats, continue learning, certificates) |
| `/users/admin/` | users | Admin panel (staff only) |
| `/users/admin/bulk-create/` | users | Bulk create course tree |
| `/users/admin/fetch-playlist/` | users | YouTube playlist fetch |
| `/api/auth/confirm/` | users | Telegram bot callback |
| `/api/auth/check/<token>/` | users | Browser polling (rate-limited) |

URL namespaces: `learning:` and `users:`

URL path segments use Uzbek words where possible: `malaka` (skill/course), `qidiruv` (search), `kategoriya` (category), `yozilish` (enroll), `sharh` (review), `sertifikat` (certificate), `davom` (continue), `korildi` ("watched"). The explicit `qidiruv/`, `kategoriya/<slug>/` etc. **must** be listed in `learning/urls.py` before the `<slug:course_slug>/` catch-all so they win the match.

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

### Lesson View Tracking (simplified — no per-second watch tracking)
- `lesson_tracker.js` loads the YouTube IFrame API solely to detect the `PLAYING` state. On the first `PLAYING` event per page load it POSTs to `/davom/korildi/` and stops listening — no heartbeats, no beacons, no seek/pause events, no session resume logic.
- The server endpoint (`record_view`) is idempotent: `LessonView.get_or_create(user, lesson, viewed_on=today_uzt)`. Multiple plays on the same day collapse to a single row.
- Playing a lesson also flips `LessonProgress.is_completed=True` (auto-completion). The manual "Tugatildi" button remains for users who want to mark a lesson done without watching the video.
- `record_view` also calls `_update_streak()` and `_maybe_issue_certificate()`.
- No CSRF-exempt beacon endpoint anymore; `record_view` is `@login_required` + standard CSRF.

### Streak System
- Updated whenever a `LessonView` is recorded **or** the manual complete button is pressed.
- `current_streak` = consecutive days with at least one qualifying activity; `longest_streak` = max ever seen.
- All streak calculations use Asia/Tashkent timezone (`_today_uzt()` in `learning/views.py`).

### Activity Heatmap
- Backed by `LessonView` (not minutes-watched). The dashboard counts distinct lessons per day and bucket-renders them as:
  - `level-0`: no views, `level-1`: 1 lesson, `level-2`: 2 lessons, `level-3`: 3–4 lessons, `level-4`: 5+ lessons.
- Tooltip shows `"YYYY-MM-DD — N dars"` or `"faollik yo'q"`.

### Course Completion & Certificates
- A course is "complete" when every lesson under it has `LessonProgress.is_completed=True`.
- `_maybe_issue_certificate(user, course)` is called from `record_view`, `mark_lesson_complete`, and `CourseDetailView` (for legacy completers). `Certificate.code` is a `secrets.token_urlsafe(10)` slug, shown on the printable certificate page.

### Ratings & Reviews
- `CourseReviewForm` uses an integer `rating` hidden input fed by a CSS-only 5-star radio widget (`.star-input`).
- After save, `course.update_rating()` re-aggregates avg and count and saves them on the Course row so card grids stay cheap.
- The course detail "Sharhlar" tab renders a 5→1 star breakdown with a percentage bar per bucket.

### Notes
- One note per user per lesson (`unique_together(user, lesson)`)
- Stored as raw Markdown, rendered via `learning/utils.py` (markdown → bleach sanitization)
- Notes live inside the `Eslatma` tab on the lesson page (one of `Tavsif` / `Eslatma` / `Resurslar` / `Savollar`); there is no longer a sticky side panel. Markup IDs (`note-preview`, `note-editor`, `note-content`, `btn-edit-note`, `btn-save-note`, `note-status`) are preserved so `lesson_notes.js` keeps working.
- Unauthenticated users see an empty-state prompt inside the tab; they cannot save.

### Admin Bulk Create
- Accepts nested JSON: `course → modules → lessons` with YouTube video IDs
- Auto-generates slugs from titles
- Optional `include_description` flag to include video descriptions from YouTube
- YouTube playlist fetch available for automation

### Course Thumbnails
- Courses support an optional uploaded thumbnail (`ImageField`)
- `Course.get_thumbnail_url()` returns the uploaded image URL, or falls back to the YouTube `hqdefault` thumbnail of the first lesson in the course
- Requires Pillow; media files served from `/media/`

### fill_durations Management Command
- `python manage.py fill_durations` — fetches `duration_seconds` from the YouTube API for all lessons missing duration data
- Useful after bulk-importing a course to populate accurate lesson lengths

### Course Detail Page
- `CourseDetailView` renders a dark hero strip (title, rating, instructor, level), a sticky `enroll-card` on the right (thumbnail + "Davom etish"/"Yozilish" CTA + feature list + share buttons), and a tabbed content area: `Umumiy` (what-you-learn grid, requirements, markdown description), `Dastur` (module accordion), `Sharhlar` (rating breakdown + review form + review list), `O'qituvchi` (instructor card).
- The accordion (`<details>` blocks) — first module open by default — shows a progress bar, completion percentage, and total duration per module; completed lessons get a green check.
- A "Davom etish" button on the enroll card links to the first incomplete lesson across the whole course; if all lessons are done, the sticky card shows a "Sertifikatimni ko'rish" button.
- View builds a `modules_data` list with per-module `total`, `completed`, `percent`, and `total_seconds`, using a single `LessonProgress` query keyed by lesson id. It also builds a `rating_breakdown` (5→1 star buckets) from a single `course.reviews.values('rating').annotate(Count(...))` query.

### Dashboard (`/users/profile/`)
- Hero strip with avatar, greeting, current streak + lessons completed + enrollments counts.
- Four stat tiles: current streak, longest streak, completed lessons, total `LessonView` count.
- Continue-learning grid (recent in-progress courses with progress bar + "Davom etish" / "Sertifikat" CTA).
- 53×7 activity heatmap (last 365 days) driven by `LessonView`, with a JS tooltip.
- Certificates wall.
- Profile-edit form + admin shortcut (staff only).

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
- Config for JS modules is injected via embedded `<script>` JSON in `lesson_detail.html`. The current `lesson-config` keys are `lesson_id`, `video_id`, `csrf_token`, `is_authenticated`, `url_record`, `url_complete` (the old `url_start`/`url_event`/`url_beacon` are gone).
- All AJAX uses the Fetch API with CSRF tokens. There is **no** Beacon API and **no** `visibilitychange`/`pagehidden` listener anymore — view recording is a single fire-and-forget POST on the YouTube `PLAYING` state.
- Highlight.js used for code block syntax highlighting in lesson descriptions/notes
- Design system: emerald brand + amber accent, Inter (UI) + Plus Jakarta Sans (headings) loaded from Google Fonts in `base.html`. Tokens in `:root` in `static/css/style.css`. Dark mode is opt-in via `html[data-theme="dark"]`, toggled by `ui.js` and persisted in `localStorage`.
- Icons are inline Lucide-style SVGs (no icon font / no sprite system).
- Sidebar (module/lesson navigation) is only shown on the lesson detail page. Views that should render the sidebar must set `show_sidebar`, `sidebar_course`, and `sidebar_modules` in context — `base.html` guards on `{% if show_sidebar %}`. Course and module detail pages intentionally omit the sidebar.
- `.content-full` (applied when no sidebar) is capped at `--container-wide` (1440px) and centered.
- Reusable card include: `templates/learning/_course_card.html` — use `{% include "learning/_course_card.html" %}` inside a `for course in ...` loop. The loop variable **must** be named `course` and ideally annotated with `lesson_count`, `total_duration`, `student_count` (see `_course_card_annotations()` in `learning/views.py`).

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
cd opencourse
cp .env.example .env   # fill in values
pipenv install
pipenv shell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### Common Commands
```bash
python manage.py makemigrations        # after model changes
python manage.py migrate               # apply migrations
python manage.py collectstatic         # for production static files
python manage.py shell                 # Django REPL
python manage.py fill_durations        # populate lesson durations from YouTube API
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

- CSRF protection on every POST endpoint. There are **no** CSRF-exempt endpoints in the learning app — the previous `/davom/xabar/` beacon was removed when video-session tracking was retired.
- Telegram bot callback (`/api/auth/confirm/`) is `@csrf_exempt` but gated by the `X-Bot-Secret` header check against `BOT_SECRET`.
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
| View (LessonView) | A row stamped when a user pressed play on a lesson on a given day |
| Progress | Per-user per-lesson completion state (`is_completed`) |
| Enrollment | Per-user per-course "My Learning" marker |
| Streak | Consecutive days with at least one LessonView or manual complete |
| Certificate | Auto-issued credential after all lessons in a course are completed |
| Category | Top-level taxonomy used to group courses on home / filter bar |
| Review | A 1–5 star rating + optional comment, one per user per course |
| davom | Uzbek: "continue" — kept as the URL segment for view recording |
| korildi | Uzbek: "was watched" (passive) — URL segment that records a daily LessonView |
| qidiruv | Uzbek: "search" |
| kategoriya | Uzbek: "category" |
| yozilish | Uzbek: "enrollment" |
| sharh | Uzbek: "review" |
| sertifikat | Uzbek: "certificate" |
