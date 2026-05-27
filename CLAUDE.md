# CLAUDE.md — Ochiq Kurs LMS

## Project Overview

**Ochiq Kurs** is a Django-based Learning Management System (LMS) for open online video courses in Uzbek. It features YouTube-embedded video lessons, article/text lessons, per-lesson quizzes (multiple-choice + true/false), learning paths (multi-course tracks), progress tracking, Telegram-based authentication, Markdown note-taking, gamified streaks with a GitHub-style activity graph, a wishlist, video timestamp bookmarks, per-lesson Q&A, attachable resources, announcements, a public leaderboard, public certificate verification, instructor profile pages, and a Udemy-style catalog UI with pagination.

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
│   ├── models.py                    # Course, Module, Lesson, LessonProgress, LessonView, Note,
│   │                                #   Enrollment, CourseReview, Certificate, Wishlist,
│   │                                #   LessonResource, LessonQuestion, LessonAnswer, Announcement,
│   │                                #   Quiz, QuizQuestion, QuizChoice, QuizAttempt, QuizAnswer,
│   │                                #   LearningPath, LearningPathCourse, LearningPathEnrollment,
│   │                                #   LearningPathCertificate, VideoBookmark
│   ├── views.py                     # Course/lesson views, quiz, bookmarks, learning paths,
│   │                                #   instructor profiles, certificate verification
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
│   │                                #   wishlist, my_learning, leaderboard, _course_card,
│   │                                #   quiz_detail, quiz_take, quiz_result,
│   │                                #   learning_path_list, learning_path_detail, path_certificate,
│   │                                #   public_certificate, instructor_detail
│   └── users/                       # profile, admin_panel, signup
├── static/
│   ├── css/style.css
│   └── js/
│       ├── lesson_tracker.js        # YouTube IFrame API: record one view per play, mark complete, article auto-record
│       ├── lesson_notes.js          # Markdown notes, save/preview
│       ├── lesson_bookmarks.js      # Video timestamp bookmarks: add, delete, seek YT player
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
             rating_count, status, published_at, order)
  └─ Module (title, slug, description, course FK, order)
       └─ Lesson (title, slug, description, module FK, lesson_type, content,
                  youtube_video_id, duration_seconds, is_preview, order)
```

- **Course.thumbnail** — optional `ImageField` (uploaded to `course_thumbnails/`). Falls back to YouTube thumbnail of the first lesson via `get_thumbnail_url()`.
- **Course.what_you_learn** / **Course.requirements** — newline-separated text blobs, surfaced as Python lists via `.what_you_learn_list` and `.requirements_list` for templates.
- **Course.avg_rating** / **Course.rating_count** — denormalised aggregates; recomputed by `course.update_rating()` after each review save.
- **Course.status** — `draft` / `published` / `archived` (default `published`). Only published courses appear in catalog views. Non-staff users get 404 on draft courses.
- **Course.published_at** — auto-set when a course is first published via admin bulk action.
- **Course.instructor_display()** — returns `instructor_name`, else the linked User's full name, else `"Ochiq kurs jamoasi"`.
- **Lesson.lesson_type** — `video` / `article` / `quiz` (default `video`). Article lessons render Markdown content instead of a YouTube embed. Quiz lessons render their attached quiz as the lesson's main content (no video, no tab bar).
- **Lesson.content** — Markdown body for article lessons.
- **Lesson.youtube_video_id** — optional (blank for article lessons).

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

### Quiz Models

- **Quiz** — FK to `Lesson`, `title`, `description`, `pass_percent` (default 70), `max_attempts` (0 = unlimited). The FK still allows multiple quizzes per lesson, but only `lesson_type='quiz'` lessons surface a quiz in the UI; quizzes attached to video/article lessons are not rendered (inline quizzes were removed — the FK is kept for a possible future inline-quiz feature).
- **QuizQuestion** — FK to `Quiz`, `question_type` (`multiple_choice` / `true_false`), `text`, `order`, `explanation` (shown after answering). Questions are ordered by `order`.
- **QuizChoice** — FK to `QuizQuestion`, `text`, `is_correct`, `order`. Rendered as radio options in the quiz UI.
- **QuizAttempt** — FK to `User` + `Quiz`, `score`, `max_score`, `passed` (bool), `started_at`, `completed_at`. Tracks each user's quiz submission. `percentage()` method returns 0-100.
- **QuizAnswer** — FK to `QuizAttempt` + `QuizQuestion` + `QuizChoice`, `is_correct`. One per question per attempt. `unique_together(attempt, question)`.

### Learning Path Models

- **LearningPath** — `title`, `slug` (unique), `description`, `thumbnail`, `order`, `is_featured`, `created_at`. Curated multi-course track like Udacity Nanodegree.
- **LearningPathCourse** — FK to `LearningPath` + `Course`, `order`. Through model: `unique_together(path, course)`.
- **LearningPathEnrollment** — FK to `User` + `LearningPath`. Per-user enrollment marker: `unique_together(user, path)`.
- **LearningPathCertificate** — FK to `User` + `LearningPath`, `code` (unique, auto-generated), `issued_at`. Auto-issued when all courses in the path are complete.

### Video Bookmark

- **VideoBookmark** — FK to `User` + `Lesson`, `timestamp_seconds`, `note` (optional text), `created_at`. Ordered by `timestamp_seconds`. Indexed on `(user, lesson)`. `formatted_timestamp()` returns `M:SS` or `H:MM:SS`.

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
| `/malaka/yonalishlar/` | learning | Learning path catalog (curated multi-course tracks) |
| `/malaka/yonalish/<slug>/` | learning | Learning path detail (sequential courses with progress) |
| `/malaka/yonalish/<slug>/yozilish/` | learning | POST: enroll in a learning path |
| `/malaka/yonalish/<slug>/sertifikat/` | learning | Learning path certificate |
| `/malaka/sertifikat/tekshirish/<code>/` | learning | Public certificate verification (no login required) |
| `/malaka/oqituvchi/<username>/` | learning | Public instructor profile (bio, stats, courses) |
| `/malaka/<course>/` | learning | Course detail (tabbed: Umumiy / Dastur / Sharhlar / O'qituvchi) |
| `/malaka/<course>/yozilish/` | learning | POST: enroll in course |
| `/malaka/<course>/sevimli/` | learning | POST: toggle wishlist (JSON; idempotent) |
| `/malaka/<course>/sharh/` | learning | POST: create or update review |
| `/malaka/<course>/sertifikat/` | learning | Printable certificate page (auto-issues if all lessons complete) |
| `/malaka/<course>/<module>/` | learning | Module detail |
| `/malaka/<course>/<module>/<lesson>/` | learning | Lesson page (tabs: Tavsif/Eslatma/Resurslar/Xatcho'plar/Savol-javob/E'lonlar; quiz-type lessons render the quiz as main content, no tabs) |
| `/malaka/<course>/<module>/<lesson>/complete/` | learning | POST: mark complete (manual) |
| `/malaka/<course>/<module>/<lesson>/note/` | learning | POST: save note (JSON) |
| `/malaka/<course>/<module>/<lesson>/davom/korildi/` | learning | POST: record a daily LessonView (fired from JS on YT `PLAYING`) |
| `/malaka/<course>/<module>/<lesson>/savol/` | learning | POST: ask a question on the lesson |
| `/malaka/<course>/<module>/<lesson>/savol/<id>/javob/` | learning | POST: answer a question |
| `/malaka/<course>/<module>/<lesson>/test/<quiz_id>/` | learning | Quiz overview (description, pass %, past attempts) |
| `/malaka/<course>/<module>/<lesson>/test/<quiz_id>/boshlash/` | learning | POST: start quiz attempt |
| `/malaka/<course>/<module>/<lesson>/test/<quiz_id>/urinish/<attempt_id>/savol/tekshir/` | learning | POST: check + record one question's answer (JSON); finalizes the attempt when all are answered |
| `/malaka/<course>/<module>/<lesson>/test/<quiz_id>/urinish/<attempt_id>/javob/` | learning | POST: submit all quiz answers at once (JSON; legacy, unused by UI) |
| `/malaka/<course>/<module>/<lesson>/test/<quiz_id>/urinish/<attempt_id>/natija/` | learning | Quiz result with per-question review |
| `/malaka/<course>/<module>/<lesson>/xatchop/` | learning | POST: save video bookmark (JSON: timestamp, note) |
| `/malaka/<course>/<module>/<lesson>/xatchop/<id>/ochirish/` | learning | POST: delete video bookmark |
| `/users/login/` | users | Telegram login (token generated) |
| `/users/signup/` | users | Same flow as login |
| `/users/profile/` | users | Dashboard (streak, stats, continue learning, certificates) |
| `/users/admin/` | users | Admin panel (staff only) |
| `/users/admin/bulk-create/` | users | Bulk create course tree |
| `/users/admin/fetch-playlist/` | users | YouTube playlist fetch |
| `/api/auth/confirm/` | users | Telegram bot callback |
| `/api/auth/check/<token>/` | users | Browser polling (rate-limited) |

URL namespaces: `learning:` and `users:`

URL path segments use Uzbek words where possible: `malaka` (skill/course), `qidiruv` (search), `kategoriya` (category), `yozilish` (enroll), `sevimli` / `sevimlilar` (favorite/wishlist), `sharh` (review), `sertifikat` (certificate), `davom` (continue), `korildi` ("watched"), `savol` (question), `javob` (answer), `reyting` (rating/leaderboard), `mening-kurslarim` (my courses), `yonalish` / `yonalishlar` (learning path/s), `oqituvchi` (instructor), `xatchop` (bookmark), `tekshirish` (verification). All explicit prefixed paths (`qidiruv/`, `sevimlilar/`, `mening-kurslarim/`, `reyting/`, `kategoriya/<slug>/`, `yonalishlar/`, `yonalish/<slug>/`, `sertifikat/tekshirish/<code>/`, `oqituvchi/<username>/`) **must** be listed in `learning/urls.py` before the `<slug:course_slug>/` catch-all so they win the match.

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

### Course Publishing Workflow
- Courses have a `status` field: `draft`, `published`, `archived` (default `published` for existing).
- All public catalog views (`CourseListView`, `SearchView`, `CategoryDetailView`, `HomeView`) filter to `status='published'`.
- `CourseDetailView` returns 404 for non-published courses unless the user is staff/superuser.
- Admin: `list_filter` by status, three bulk actions (`make_published`, `make_draft`, `make_archived`).

### Quizzes
- Quizzes are surfaced only on `lesson_type='quiz'` lessons, and are **taken inline on the lesson page** (in place of the video) — there is no separate take page. Video/article lessons have no "Test" tab (inline-on-other-lessons quizzes were removed; the `Quiz.lesson` FK is kept for a possible future feature). The view only builds quiz context when `lesson_type='quiz'`.
- The quiz content area has three states, chosen in `LessonDetailView`:
  1. **No active attempt** → "hero" (title, meta, "Testni boshlash") + past-attempt history (`quizzes_with_meta`).
  2. **In-progress attempt** → the question UI renders inline (`active_quiz` / `active_attempt` / `active_questions` / `active_answered_ids_json`). `_next_lesson()` powers the inline result's forward link.
  3. **Finished** → the JS reveals an inline result summary (no page load).
- POST `/boshlash/` (`start_quiz`) creates a `QuizAttempt` (max attempts enforced server-side) and **redirects back to the lesson page**, where the in-progress attempt now renders inline.
- Taking is **one question at a time** with immediate per-question feedback. A choice is picked, then "Javobni tekshirish" (disabled until a choice is selected) POSTs that single answer to `/savol/tekshir/` (`check_quiz_answer`). The server records the `QuizAnswer` (`update_or_create` on attempt+question) and returns `{is_correct, correct_choice_id, explanation, answered, total, finished, result}`; the UI locks the choices, highlights correct/wrong (green/red), shows the `explanation`, and the button becomes "Keyingi savol →" (or "Natijani ko'rish" on the last question). A progress bar + "N / total" counter track position. CSRF is read from the `csrftoken` cookie.
- Grading is fully server-side (correct answers are never sent to the page until checked). When every question has an answer, `check_quiz_answer` calls `_finalize_quiz_attempt()` — sets score/passed/`completed_at`, returns the final `result`, and on pass marks the lesson `is_completed=True`, updates the streak, and may issue the course certificate.
- Reload-resume: the inline JS reads `active_answered_ids_json` and skips to the first unanswered question. A completed attempt is no longer "active", so the page falls back to the hero + history.
- Inline result: pass/fail badge, score, a primary "Keyingi dars →" (forward navigation, or "Kursga qaytish" at course end), and a "To'liq tahlil" link to the full per-question review page (`quiz_result`).
- `quiz_result` page (`/natija/`): full per-question review (correct-answer highlight + explanation); reached from "To'liq tahlil" and from the history table's "Ko'rish".
- `submit_quiz_answer` (`/javob/`) is the legacy all-at-once JSON grader — retained (routes through `_finalize_quiz_attempt()`) but no longer used by the UI. The old `quiz_attempt_view` / `quiz_take.html` / `quiz_attempt` URL were removed.

### Video Bookmarks (Xatcho'plar)
- Per-user per-lesson timestamp bookmarks for video lessons only.
- Capture current YouTube time via `player.getCurrentTime()`. Optional note text.
- Bookmark list shows formatted timestamps (`M:SS` or `H:MM:SS`), optional notes, and delete buttons.
- Clicking a bookmark timestamp seeks the YT player to that position via `player.seekTo()`.
- `lesson_bookmarks.js` integrates with the YT player reference exposed by `lesson_tracker.js` via `window.__bmSetPlayer()`.

### Learning Paths (Yo'nalishlar)
- Curated multi-course tracks displayed on a dedicated catalog page (`/malaka/yonalishlar/`).
- Path detail page shows sequential courses with per-course progress bars (for enrolled users).
- Enrollment: `POST /yozilish/` creates `LearningPathEnrollment`.
- Path certificate auto-issued when all courses in the path are 100% complete.
- Featured paths shown on the homepage.
- Nav link "Yo'nalishlar" in the main navbar.

### Public Certificate Verification
- `/malaka/sertifikat/tekshirish/<code>/` — public page, no login required.
- Displays certificate with a green "Haqiqiy sertifikat" verification badge.
- Copy link button for sharing.
- Certificate detail page links to this verification URL.

### Instructor Profiles
- Public page at `/malaka/oqituvchi/<username>/` showing instructor's Telegram avatar (or initial), bio, stats (courses, students, lessons, avg rating), and a grid of their published courses.
- Instructor name on course detail page (hero strip + instructor tab) links to the profile.
- Only works for courses that have `course.instructor` (FK to User) set.

### Home Page Personalization
- Authenticated users see "Davom ettirish" section (up to 3 in-progress courses with progress bars), recent activity line, and "Sizga yoqishi mumkin" — category-based recommendations (6 courses in same categories as enrolled, not yet enrolled).
- Anonymous users see the standard hero + trust strip.
- Featured learning paths section shown for all users when paths exist.

### Article Lessons
- Lessons with `lesson_type='article'` render Markdown content (`lesson.content`) instead of a YouTube embed.
- Article wrapper styled like a reading pane (max-width 820px, padded).
- `lesson_tracker.js` auto-records a view on page load for article lessons (no video play needed).
- Lesson type badge displayed in the subtitle meta area.

### Pagination
- Course catalog uses Django `Paginator`, 24 courses per page.
- Page navigation preserves all active filter query params (category, level, sort, search query).
- Parameter name: `?sahifa=<N>`.

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
- Tabs: `Tavsif` / `Eslatma` / `Resurslar` / `Xatcho'plar` (video only) / `Savol-javob` / `E'lonlar` (the last tab only renders when there are announcements). Tabs with content show a small count pill. Quiz-type lessons skip the tab bar entirely and render the quiz as the main content.
- `Savol-javob` includes an ask form for authenticated users and a list of questions, each with an expandable answers `<details>` block and a quick-reply form. The tab auto-opens when the URL hash starts with `#qa` or `#q`.

### Dashboard (`/users/profile/`)
- Hero strip with avatar, greeting, and four clickable stats: enrollments (→ My Learning), current streak, completed lessons, leaderboard link.
- Four stat tiles: current streak, longest streak, completed lessons, total `LessonView` count.
- Continue-learning grid (recent in-progress courses with progress bar + "Davom etish" / "Sertifikat" CTA).
- 53×7 activity heatmap (last 365 days) driven by `LessonView`, with a JS tooltip.
- Certificates wall.
- Profile-edit form + admin shortcut (staff only).

### Home Page
- **Authenticated users**: "Davom ettirish" section (up to 3 in-progress courses with progress bars), recent activity, "Sizga yoqishi mumkin" recommendations, featured learning paths section.
- **Anonymous users**: Pro hero with a Telegram-style hero card stack on the right, a pill-search field, and a trust strip of stats.
- Then: featured learning paths (if any), trust strip, category grid, **Featured** row, "Why us" feature row, **Trending** row, one row per category (top 6 categories × 6 courses each), **Newest** row, testimonials, and a final CTA banner.
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
- Config for JS modules is injected via embedded `<script>` JSON in `lesson_detail.html`. The current `lesson-config` keys are `lesson_id`, `video_id`, `csrf_token`, `is_authenticated`, `is_article`, `url_record`, `url_complete`, `url_save_bookmark`.
- All AJAX uses the Fetch API with CSRF tokens. There is **no** Beacon API and **no** `visibilitychange`/`pagehidden` listener anymore — view recording is a single fire-and-forget POST on the YouTube `PLAYING` state.
- Highlight.js used for code block syntax highlighting in lesson descriptions/notes
- Design system: emerald brand + amber accent. Fonts (Google Fonts in `base.html`, exposed as `:root` tokens): **Hanken Grotesk** (UI/body, `--font-ui`), **Bricolage Grotesque** (headings, `--font-head`), **JetBrains Mono** (code, `--font-mono`). All tokens live in `:root` in `static/css/style.css`. Decorative two-tone brand gradients (and gradient-clipped text) have been flattened to solid brand colors as a deliberate de-genericization choice — kept only for functional/subtle effects (progress bars, loading skeletons, podium medals, subtle radial atmosphere glows). Dark mode is opt-in via `html[data-theme="dark"]` and uses an **emerald-toned charcoal** palette (e.g. `--bg:#0A1411`, `--surface:#10211B`), not blue slate; toggled by `ui.js` and persisted in `localStorage`.
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
| Quiz | Per-lesson assessment with multiple-choice or true/false questions |
| QuizAttempt | One user's submission of a quiz, with score and pass/fail status |
| Learning Path (Yo'nalish) | Curated sequential multi-course track; completing all courses awards a path certificate |
| Video Bookmark (Xatcho'p) | Per-user timestamp marker on a video lesson with optional note |
| Article Lesson (Maqola) | Text-based lesson with rendered Markdown content; no video |
| Course Status | `draft` / `published` / `archived` — controls catalog visibility |
| Public Certificate Verification | Anyone can verify a certificate code at `/malaka/sertifikat/tekshirish/<code>/` |
| Instructor Profile | Public page at `/malaka/oqituvchi/<username>/` with instructor bio and courses |
| yonalish / yonalishlar | Uzbek: "direction" / "directions" — URL segments for learning paths |
| xatcho'p | Uzbek: "bookmark" — URL segment for video bookmarks |
| oqituvchi | Uzbek: "teacher" — URL segment for instructor profiles |
| tekshirish | Uzbek: "verification" — URL segment for certificate verification |
| sahifa | Uzbek: "page" — URL query param for pagination |
