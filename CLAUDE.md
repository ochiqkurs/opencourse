# CLAUDE.md — Ochiq Kurs LMS

## Project Overview

**Ochiq Kurs** is a Django-based Learning Management System (LMS) for open online video courses in Uzbek. It features YouTube-embedded video lessons, article/text lessons, per-lesson quizzes (multiple-choice + true/false), learning paths (multi-course tracks), progress tracking, Telegram-based authentication, Markdown note-taking, gamified streaks with a GitHub-style activity graph, a wishlist, video timestamp bookmarks, per-lesson Q&A, attachable resources, announcements, a public leaderboard, public certificate verification, instructor profile pages, and a Udemy-style catalog UI with pagination.

---

## Architecture Reference (read on demand)

Detailed reference lives in **[`docs/architecture.md`](docs/architecture.md)** — it is **not** auto-loaded. Read it when you need:

- **Repository Structure** — the full directory tree and what each file holds.
- **Data Models** — every model and its fields (`Course → Module → Lesson`, tracking, engagement, quiz, learning path, video bookmark, user models).
- **URL Structure** — the complete URL → view map and namespaces.
- **Key Business Logic** — per-feature behavior (view tracking, streaks, heatmap, certificates, reviews, notes, wishlist, Q&A, announcements, leaderboard, quizzes, bookmarks, learning paths, instructor profiles, pagination, bulk create, thumbnails, course/lesson/dashboard/home page composition).
- **Domain Language** — the glossary of terms and Uzbek URL segments.

Keep `docs/architecture.md` in sync when you change models, URLs, or feature behavior — and keep this CLAUDE.md under the 40k-char context limit (move new long-form reference into `docs/`, not here).

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

## Authentication Flow

1. User visits `/users/login/` → server creates `TelegramAuthToken` (10-min TTL)
2. Frontend shows a Telegram bot link embedding the token
3. Browser polls `/api/auth/check/<token>/` every 2 seconds (rate-limited to 60 req/min)
4. Telegram bot POSTs to `/api/auth/confirm/` with `BOT_SECRET` header, `telegram_id`, `first_name`, etc.
5. Server confirms token, creates/updates User + TelegramProfile, logs user in via Django session
6. Browser receives confirmed status, redirects to `/malaka/`

New users get `set_unusable_password()` — Telegram-only auth by default.

### The login page (`/users/login/`)
One page hosts all three sign-in methods. The Telegram bot button is the primary CTA; the **code form** and **inline password form** live inside a collapsed `<details>` ("Boshqa kirish usullari") disclosure that auto-opens when either form returns an error. `TelegramLoginView.post` **dispatches** on the submitted fields: a `username`/`password` POST routes to the password handler, otherwise to the code handler. All three methods honor `?next=` (open-redirect-safe via `_safe_next` / `url_has_allowed_host_and_scheme`; the Telegram poller applies `next` client-side). `_client_ip` prefers the `CF-Connecting-IP` header (set by Cloudflare, unspoofable), then falls back to the **last** `X-Forwarded-For` entry, then `REMOTE_ADDR` — so the rate limiter can't be bypassed and isn't collapsed into one Cloudflare-edge bucket.

### Code-based login (other device)
For users on a device without Telegram, the bot issues the code (not the website). User sends `/login` to the bot; the bot POSTs the Telegram identity to `/api/auth/issue-code/` (gated by `X-Bot-Secret`), which calls `_get_or_create_telegram_user(...)` (shared with `/api/auth/confirm/`) and creates a pre-confirmed `TelegramAuthToken` via `TelegramAuthToken.issue_for_user(user, is_new_user)` — `confirmed_at=now`, `user` set, `short_code` set to a fresh 6-digit numeric (unique among tokens issued within the last 10 minutes). Endpoint returns `{short_code, expires_in_seconds: 600}`. The bot replies with the formatted code (e.g. `123 456`). The user types it on `/users/login/`; the code handler (rate-limited 10/min per IP via `prefix='code'`) strips non-digits, looks up the latest confirmed unexpired token by `short_code`, logs the user in, and **deletes the token** (one-time use; replays return the same "kod noto'g'ri" error). New users redirect to `/users/profile/`, returning users to `?next=` or `LOGIN_REDIRECT_URL`. `TelegramAuthToken.generate()` no longer sets a `short_code` — only `issue_for_user` does, so browser-flow tokens never collide with bot-issued codes.

### Username + password login
A Telegram-authenticated user can set a username + password at `/users/parol-ornatish/` (`SetUsernamePasswordForm`; username regex `^[a-z0-9_]{3,30}$`, stored lowercased, `validate_password`, `update_session_auth_hash` keeps the session). They can then log in without Telegram — **inline on the login page** (the password handler renders credential errors inline, no separate-page bounce) or via the standalone `/users/kirish/parol/` (`UsernamePasswordLoginView`). Both are rate-limited 10/min per IP via `prefix='login'`. `UsernamePasswordLoginForm` **lowercases** the username before `authenticate` to match the stored casing. A password-less account that tries password login gets a specific "set a password first" message rather than a generic error. **Forgot password:** there is no email reset (accounts are Telegram-only) — the login page tells users to sign in via Telegram and reset from their profile (`/users/parol-ornatish/`). A dedicated reset flow is not implemented.

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
- Config for JS modules is injected via embedded `<script>` JSON in `lesson_detail.html`. The current `lesson-config` keys are `lesson_id`, `video_id`, `csrf_token`, `is_authenticated`, `is_article`, `is_completed`, `url_record`, `url_complete`, `url_save_bookmark`.
- All AJAX uses the Fetch API with CSRF tokens. There is **no** Beacon API and **no** `visibilitychange`/`pagehidden` listener. **Viewing vs completing are separate signals** (`lesson_tracker.js`): a *view* is a single fire-and-forget POST to `record_view` on the YouTube `PLAYING` state (or on article page load) — it enrolls + bumps the streak/activity but does **not** complete the lesson. *Completion* POSTs to `mark_lesson_complete` and fires when the video is watched to ≥90% (polled `getCurrentTime/getDuration`) or `ENDED`, or on the manual "mark complete" button. Auto-complete updates the button in place (no reload); only the manual click reloads. Certificates issue from `mark_lesson_complete` (and the explicit `/sertifikat/` view), never from a view.
- Highlight.js used for code block syntax highlighting in lesson descriptions/notes
- Design system: emerald brand + amber accent. Fonts (Google Fonts in `base.html`, exposed as `:root` tokens): **Hanken Grotesk** (UI/body, `--font-ui`), **Bricolage Grotesque** (headings, `--font-head`), **JetBrains Mono** (code, `--font-mono`). All tokens live in `:root` in `static/css/style.css`. Decorative two-tone brand gradients (and gradient-clipped text) have been flattened to solid brand colors as a deliberate de-genericization choice — kept only for functional/subtle effects (progress bars, loading skeletons, podium medals, subtle radial atmosphere glows). Dark mode is opt-in via `html[data-theme="dark"]` and uses an **emerald-toned charcoal** palette (e.g. `--bg:#0A1411`, `--surface:#10211B`), not blue slate; toggled by `ui.js` and persisted in `localStorage`.
- Icons are inline Lucide-style SVGs (no icon font / no sprite system). A `{% lucide name size %}` template tag (`learning/templatetags/learning_extras.py`) renders an icon by name from a curated path set (fallback `book-open`) — used for the category-card icons and to keep emoji out of the UI (emoji-as-icons read as AI-slop). Category cards derive a per-category icon (from `Category.icon`, a Lucide name) and accent colour (from `Category.color` via a `--cat-color` var + `color-mix`).
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

### URL routing gotcha
All explicit prefixed paths (`qidiruv/`, `sevimlilar/`, `mening-kurslarim/`, `reyting/`, `kategoriya/<slug>/`, `yonalishlar/`, `yonalish/<slug>/`, `sertifikat/tekshirish/<code>/`, `oqituvchi/<username>/`) **must** be listed in `learning/urls.py` **before** the `<slug:course_slug>/` catch-all so they win the match. URL namespaces: `learning:` and `users:`. URL path segments use Uzbek words (see the Domain Language glossary in `docs/architecture.md`).

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
python manage.py createcachetable      # provision the DB cache table (rate limiter)
python manage.py clear_expired_tokens  # delete TelegramAuthToken rows past their 10-min TTL
python manage.py graph_models -a -g -o models_graph.png  # regenerate models_graph.png (requires DEBUG=True for django_extensions)
```

### Tests
A focused Django `TestCase` suite lives in `learning/tests.py` (run with `python manage.py test`; ~39 tests). It covers: progress/enrollment integrity (no progress on draft/archived courses, GET stays side-effect free, a play records a view + enrolls but does **not** complete, the manual button completes), multi-select quiz grading (exact-set match) and quiz history (finished attempts only), the Telegram auth flows (`/api/auth/confirm/`, `/api/auth/issue-code/`, code login, the `check` poll), streak logic (`_update_streak` + `live_streak`), certificate auto-issue, and avatar localization (`_localize_avatar`). Auth tests use `override_settings` with a fixed `BOT_SECRET` and an in-memory cache (the prod DB cache table isn't created in the test DB); template-rendering tests swap in the plain static backend (no manifest in tests). UI/visual changes are still verified by rendering pages in a headless browser (both themes), not just unit tests. Add tests here when changing progress, enrollment, certificate, quiz, auth, streak, or avatar logic.

---

## Deployment

CI/CD via GitHub Actions (`.github/workflows/deploy.yml`):
- Triggers on push to `master`
- SSHes into the production server (`~/opencourse`)
- Runs (`set -euo pipefail`): `git fetch` → `git reset --hard origin/master` (survives untracked-file collisions, unlike `git pull`) → `pip install` → **`makemigrations --check --dry-run`** (fails the deploy before the DB is touched if a model change shipped without its migration) → `migrate` → `createcachetable` → `clear_expired_tokens` → `collectstatic` → `systemctl restart gunicorn-ochiqkurs` → **post-restart health check** (curls the gunicorn unix socket; a 5xx/connection failure fails the deploy so a broken release doesn't report success)
- The Cloudflare purge step uses `curl --fail`, so a rejected purge (e.g. bad `CLOUDFLARE_API_TOKEN`) fails loudly instead of passing silently.
- Then purges the Cloudflare cache

`createcachetable` provisions the `cache_table` the rate limiter needs (idempotent). Production Gunicorn binds a unix socket (`~/opencourse/gunicorn.sock`) behind nginx, not a TCP port. The Telegram bot is a separate repo/process on the same server (systemd unit `telegram-bot-ochiqkurs`, dir `~/opencourse-bot`) and is **not** deployed by this workflow — it has **its own** GitHub Actions CI/CD in the `muzaffar-murodovich/opencourse-bot` repo (push to its `master` → SSH deploy → `systemctl restart telegram-bot-ochiqkurs` → `systemctl is-active` health check). The bot deploy uses a **dedicated passphraseless** SSH deploy key (the personal `~/.ssh/id_ed25519` is passphrase-protected and only works locally via the macOS Keychain, so it can't be used by Actions).

Production server: Ubuntu with Gunicorn serving the Django app. WhiteNoise handles static files.

**Do not force-push to `master`** — it triggers deployment.

---

## Security Notes

- CSRF protection on every POST endpoint. There are **no** CSRF-exempt endpoints in the learning app — the previous `/davom/xabar/` beacon was removed when video-session tracking was retired.
- Telegram bot callback (`/api/auth/confirm/`) and `/api/auth/issue-code/` are `@csrf_exempt` but gated by the `X-Bot-Secret` header check against `BOT_SECRET`.
- User-submitted Markdown is sanitized with `bleach` before rendering
- All security headers enabled: `X-Frame-Options DENY`, `SECURE_BROWSER_XSS_FILTER`, `SECURE_CONTENT_TYPE_NOSNIFF`
- Rate limiting on `/api/auth/check/<token>/` (60 req/min), the code login (10/min per IP, `prefix='code'`), and the password login (10/min per IP, `prefix='login'`). Backed by a **DatabaseCache** (`CACHES` → `cache_table`) so limits are shared across Gunicorn workers and survive restarts — not the per-process default `LocMemCache`. `_client_ip` prefers `CF-Connecting-IP`, then the last `X-Forwarded-For` entry, then `REMOTE_ADDR`, to resist spoofing. Telegram avatars are downloaded server-side to local `/media/avatars/` (`_localize_avatar`, called in both the confirm and issue-code flows) so the bot-token-bearing `api.telegram.org/file/bot<TOKEN>/…` URL is never stored or rendered to the browser. Telegram serves photos as `application/octet-stream`, so the download is validated by **magic bytes** (JPEG `FF D8 FF` / PNG) rather than the content-type header; it's best-effort (any failure → no avatar, never blocks sign-in).
