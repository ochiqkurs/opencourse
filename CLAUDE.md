# CLAUDE.md — Ochiq Kurs LMS

## Project Overview

**Ochiq Kurs** is a Django-based Learning Management System (LMS) for open online video courses in Uzbek. It features YouTube-embedded video lessons, progress tracking, Telegram-based authentication, Markdown note-taking, gamified streaks with a GitHub-style activity graph, a wishlist, per-lesson Q&A, attachable resources, announcements, a public leaderboard, and a Udemy-style catalog UI.

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
│   ├── base.html                    # Shared layout (navbar, sidebar, footer, wishlist JS)
│   ├── home.html                    # Pro hero + curated rows (featured/trending/per-category/newest)
│   ├── registration/login.html      # Telegram auth page
│   ├── learning/                    # course_list, course_detail, module_detail, lesson_detail,
│   │                                #   wishlist, my_learning, leaderboard, _course_card
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
- **Wishlist** — `unique_together(user, course)`: per-user "favorite" markers. Toggled by the heart on every course card and from a button on the course/lesson detail page. Surfaced at `/malaka/sevimlilar/`.
- **LessonResource** — supplementary materials attached to a lesson: `title`, `url`, `kind` (`link` / `file` / `code` / `doc`), `order`. Rendered as a typed-icon list on the lesson "Resurslar" tab.
- **LessonQuestion / LessonAnswer** — per-lesson Q&A. Questions belong to a `Lesson` + `User`; answers belong to a `Question` + `User`. `LessonAnswer.is_instructor` is auto-set to `True` when the answering user has `is_staff` or `is_superuser`. Rendered in the "Savol-javob" tab.
- **Announcement** — `title`, `body`, optional `course` FK (null = global, shown on home + every course/lesson page), `is_pinned`. Ordered by `(-is_pinned, -created_at)`.

### User Models

- **UserProfile** — OneToOne with Django User: `current_streak`, `longest_streak`, `last_activity_date`
- **TelegramAuthToken** — `token`, `created_at`, `confirmed_at`, `user` (nullable FK), `is_new_user`; expires after 10 minutes
- **TelegramProfile** — OneToOne with User: `telegram_id`, `first_name`, `last_name`, `username`, `photo_url`

---

## URL Structure

| Path | App | Description |
|---|---|---|
| `/` | — | Home page (pro hero, curated rows: Featured/Trending/per-category/Newest, testimonials, CTA) |
| `/malaka/` | learning | Course list with sticky sidebar filters (category/level/sort) + grid/list view toggle |
| `/malaka/qidiruv/` | learning | Search (HTML; `?format=json` returns suggestions for the navbar) |
| `/malaka/sevimlilar/` | learning | Authenticated user's wishlist of courses |
| `/malaka/mening-kurslarim/` | learning | "My Learning" — enrolled courses with progress; tabs `?holat=all/in_progress/not_started/completed` |
| `/malaka/reyting/` | learning | Public leaderboard with podium + table; `?davr=all/month/week` |
| `/malaka/kategoriya/<slug>/` | learning | Courses inside a category |
| `/malaka/<course>/` | learning | Course detail (tabbed: Umumiy / Dastur / Sharhlar / O'qituvchi) |
| `/malaka/<course>/yozilish/` | learning | POST: enroll in course |
| `/malaka/<course>/sevimli/` | learning | POST: toggle wishlist (JSON; idempotent) |
| `/malaka/<course>/sharh/` | learning | POST: create or update review |
| `/malaka/<course>/sertifikat/` | learning | Printable certificate page (auto-issues if all lessons complete) |
| `/malaka/<course>/<module>/` | learning | Module detail |
| `/malaka/<course>/<module>/<lesson>/` | learning | Lesson page |
| `/malaka/<course>/<module>/<lesson>/complete/` | learning | POST: mark complete (manual) |
| `/malaka/<course>/<module>/<lesson>/note/` | learning | POST: save note (JSON) |
| `/malaka/<course>/<module>/<lesson>/davom/korildi/` | learning | POST: record a daily LessonView (fired from JS on YT `PLAYING`) |
| `/malaka/<course>/<module>/<lesson>/savol/` | learning | POST: ask a question on the lesson |
| `/malaka/<course>/<module>/<lesson>/savol/<id>/javob/` | learning | POST: answer a question |
| `/users/login/` | users | Telegram login (token generated) |
| `/users/signup/` | users | Same flow as login |
| `/users/profile/` | users | Dashboard (streak, stats, continue learning, certificates) |
| `/users/admin/` | users | Admin panel (staff only) |
| `/users/admin/bulk-create/` | users | Bulk create course tree |
| `/users/admin/fetch-playlist/` | users | YouTube playlist fetch |
| `/api/auth/confirm/` | users | Telegram bot callback |
| `/api/auth/check/<token>/` | users | Browser polling (rate-limited) |

URL namespaces: `learning:` and `users:`

URL path segments use Uzbek words where possible: `malaka` (skill/course), `qidiruv` (search), `kategoriya` (category), `yozilish` (enroll), `sevimli` / `sevimlilar` (favorite/wishlist), `sharh` (review), `sertifikat` (certificate), `davom` (continue), `korildi` ("watched"), `savol` (question), `javob` (answer), `reyting` (rating/leaderboard), `mening-kurslarim` (my courses). All explicit prefixed paths (`qidiruv/`, `sevimlilar/`, `mening-kurslarim/`, `reyting/`, `kategoriya/<slug>/`) **must** be listed in `learning/urls.py` before the `<slug:course_slug>/` catch-all so they win the match.

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
- Notes live inside the `Eslatma` tab on the lesson page (alongside `Tavsif` / `Resurslar` / `Savol-javob` / `E'lonlar`); there is no longer a sticky side panel. Markup IDs (`note-preview`, `note-editor`, `note-content`, `btn-edit-note`, `btn-save-note`, `note-status`) are preserved so `lesson_notes.js` keeps working.
- Unauthenticated users see an empty-state prompt inside the tab; they cannot save.

### Wishlist
- Heart button on every `_course_card.html` and on the course/lesson hero. Toggled via `POST /malaka/<course>/sevimli/` (returns `{wishlisted: bool}`).
- Views that render course cards must inject `wishlist_ids` (a set of course IDs the current user has favorited). Use the `_user_wishlist_ids(user)` helper in `learning/views.py`. The card template reads `course.id in wishlist_ids` to set the `active` class.
- The toggle JS lives at the bottom of `base.html` (only emitted for authenticated users) and uses delegated `click` on `[data-toggle-wishlist]`. CSRF is read from the cookie.

### Lesson Q&A
- `LessonQuestion` + `LessonAnswer`. Posted from forms in the "Savol-javob" tab on the lesson page.
- Anchors: the tab opens automatically when the URL hash is `#qa` or `#q<id>`; a newly posted question/answer redirects to `…lesson/#q<id>` so the user lands on their post.
- Instructor badge: any answer by a staff/superuser user gets `is_instructor=True` at save time and renders an "O'qituvchi" pill.
- Resolution: `LessonQuestion.is_resolved` is a manual flag (no UI to flip yet — set via Django admin).

### Lesson Resources
- Typed (`link` / `file` / `code` / `doc`) auxiliary materials managed in the Django admin. Each has a different icon/color in the lesson "Resurslar" tab.

### Announcements
- Pinnable banners. `course=None` → global, shown on the home page and on every course/lesson page. `course=<X>` → scoped to that course's detail page and lessons.
- The lesson page exposes an "E'lonlar" tab (only when there are announcements to show) in addition to the Overview-tab card on the course page.

### Leaderboard
- `/malaka/reyting/` ranks users by `LessonView` count over a window (`?davr=all|month|week`). Top 3 render as a gold/silver/bronze podium; the rest as a table with completed-lesson and streak columns. The page is public.

### My Learning
- `/malaka/mening-kurslarim/` shows every course the user is enrolled in (one card per `Enrollment`) with a progress percentage derived from `LessonProgress`. Tabs: all / in progress / not started / completed. Completed courses show a "Sertifikat" CTA instead of "Davom etish".

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
- `CourseDetailView` renders a dark hero strip (title, rating, instructor, level), a sticky `enroll-card` on the right (thumbnail with a hover "Tanishtiruv" preview button + "Davom etish"/"Yozilish" CTA + Wishlist toggle + feature list + share buttons), and a tabbed content area: `Umumiy` (announcements card, what-you-learn grid, requirements, markdown description), `Dastur` (module accordion), `Sharhlar` (rating breakdown + review form + review list), `O'qituvchi` (instructor card).
- The accordion (`<details>` blocks) — first module open by default — shows a progress bar, completion percentage, and total duration per module; completed lessons get a green check.
- A "Davom etish" button on the enroll card links to the first incomplete lesson across the whole course; if all lessons are done, the sticky card shows a "Sertifikatimni ko'rish" button.
- View builds a `modules_data` list with per-module `total`, `completed`, `percent`, and `total_seconds`, using a single `LessonProgress` query keyed by lesson id. It also builds a `rating_breakdown` (5→1 star buckets) from a single `course.reviews.values('rating').annotate(Count(...))` query.
- The view also exposes `is_wishlisted`, `announcements` (course-scoped + global), and `preview_lesson` (first `is_preview=True` lesson, else the very first lesson).

### Lesson Detail Page
- Above the video: a "course-progress-strip" with the course title, `N / total` completed lessons, and a progress bar.
- Lesson title row carries a wishlist toggle and a "Tugatildi" badge when applicable.
- Tabs: `Tavsif` / `Eslatma` / `Resurslar` / `Savol-javob` / `E'lonlar` (the last tab only renders when there are announcements). Tabs with content show a small count pill.
- `Savol-javob` includes an ask form for authenticated users and a list of questions, each with an expandable answers `<details>` block and a quick-reply form. The tab auto-opens when the URL hash starts with `#qa` or `#q`.

### Dashboard (`/users/profile/`)
- Hero strip with avatar, greeting, and four clickable stats: enrollments (→ My Learning), current streak, completed lessons, leaderboard link.
- Four stat tiles: current streak, longest streak, completed lessons, total `LessonView` count.
- Continue-learning grid (recent in-progress courses with progress bar + "Davom etish" / "Sertifikat" CTA).
- 53×7 activity heatmap (last 365 days) driven by `LessonView`, with a JS tooltip.
- Certificates wall.
- Profile-edit form + admin shortcut (staff only).

### Home Page
- Pro hero with a Telegram-style hero card stack on the right, a pill-search field, and a trust strip of stats.
- Then: trust strip, category grid, **Featured** row, "Why us" feature row, **Trending** row, one row per category (top 6 categories × 6 courses each), **Newest** row, testimonials, and a final CTA banner.
- Global announcements render as amber banners at the top of the page when present.

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
- Reusable card include: `templates/learning/_course_card.html` — use `{% include "learning/_course_card.html" %}` inside a `for course in ...` loop. The loop variable **must** be named `course` and ideally annotated with `lesson_count`, `total_duration`, `student_count` (see `_course_card_annotations()` in `learning/views.py`). The card reads `wishlist_ids` (a set of course IDs) from context to render the heart in active/inactive state — views that render cards for authenticated users **must** inject this set (`_user_wishlist_ids(request.user)`).
- Wishlist toggle JS: a single delegated `click` listener at the bottom of `base.html` (only emitted when `user.is_authenticated`) handles every `[data-toggle-wishlist]` button. Reads CSRF from the `csrftoken` cookie and POSTs to `data-url`.
- Course catalog (`/malaka/`) has its own layout: sticky left sidebar of filters (`catalog-side`) and a main column with a `Karta`/`Ro'yxat` view toggle that toggles `.view-grid` / `.view-list` classes on the card grid.

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
| sevimli / sevimlilar | Uzbek: "favorite" / "favorites" — URL segments for the wishlist |
| savol / javob | Uzbek: "question" / "answer" — Q&A URL segments |
| reyting | Uzbek: "rating" — used as the leaderboard URL segment |
| mening kurslarim | Uzbek: "my courses" — the My Learning page |
| Wishlist | Per-user "save for later" marker on a course |
| Q&A | Per-lesson public question/answer thread |
| Resource | Auxiliary material (link/file/code/doc) attached to a lesson |
| Announcement | Site- or course-scoped banner with optional pin |
| Leaderboard | Public ranking of users by `LessonView` count |
