# Architecture Reference — Ochiq Kurs LMS

> Detailed reference split out of `CLAUDE.md` to keep the always-loaded project instructions under the size limit. This file is **not** auto-loaded into context — read it when you need model fields, the full URL map, per-feature business logic, or the domain glossary.

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
│   ├── management/commands/
│   │   └── clear_expired_tokens.py  # Deletes TelegramAuthToken rows past their 10-min TTL
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
│       ├── lesson_player.js         # Custom player chrome: play/pause/seek/volume/rate/fullscreen over a controls-less YouTube iframe
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
- **TelegramAuthToken** — `token`, `short_code` (6-digit, blank for browser-flow tokens), `created_at`, `confirmed_at`, `user` (nullable FK), `is_new_user`; expires after 10 minutes. `generate()` mints a pending browser-flow token (no `short_code`); `issue_for_user(user, is_new_user)` mints a pre-confirmed token **with** a `short_code` for the bot-issued code flow. Rows are deleted on successful code login (one-time use), swept opportunistically (~3% of login renders) and by the `clear_expired_tokens` command.
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
| `/users/login/` | users | Login page: bot-link polling + bot-issued 6-digit code + inline username/password (POST dispatches on fields; honors `?next=`; code & password each rate-limited 10/min per IP) |
| `/users/signup/` | users | Same flow as login (renders `login.html`; `signup.html` is unused) |
| `/users/kirish/parol/` | users | Username + password login (rate-limited 10/min per IP) |
| `/users/parol-ornatish/` | users | Set/change username + password (login required) |
| `/users/profile/` | users | Dashboard (streak, stats, continue learning, certificates) |
| `/users/admin/` | users | Admin panel (staff only) |
| `/users/admin/bulk-create/` | users | Bulk create course tree |
| `/users/admin/fetch-playlist/` | users | YouTube playlist fetch |
| `/api/auth/confirm/` | users | Telegram bot callback (bot-link flow) |
| `/api/auth/issue-code/` | users | Bot mints a 6-digit login code for the user (`X-Bot-Secret`) |
| `/api/auth/check/<token>/` | users | Browser polling (rate-limited) |

URL namespaces: `learning:` and `users:`

URL path segments use Uzbek words where possible: `malaka` (skill/course), `qidiruv` (search), `kategoriya` (category), `yozilish` (enroll), `sevimli` / `sevimlilar` (favorite/wishlist), `sharh` (review), `sertifikat` (certificate), `davom` (continue), `korildi` ("watched"), `savol` (question), `javob` (answer), `reyting` (rating/leaderboard), `mening-kurslarim` (my courses), `yonalish` / `yonalishlar` (learning path/s), `oqituvchi` (instructor), `xatchop` (bookmark), `tekshirish` (verification). All explicit prefixed paths (`qidiruv/`, `sevimlilar/`, `mening-kurslarim/`, `reyting/`, `kategoriya/<slug>/`, `yonalishlar/`, `yonalish/<slug>/`, `sertifikat/tekshirish/<code>/`, `oqituvchi/<username>/`) **must** be listed in `learning/urls.py` before the `<slug:course_slug>/` catch-all so they win the match.

---

## Key Business Logic

### Lesson View Tracking (simplified — no per-second watch tracking)
- `lesson_tracker.js` loads the YouTube IFrame API solely to detect the `PLAYING` state. On the first `PLAYING` event per page load it POSTs to `/davom/korildi/` and stops listening — no heartbeats, no beacons, no seek/pause events, no session resume logic.
- The server endpoint (`record_view`) is idempotent: `LessonView.get_or_create(user, lesson, viewed_on=today_uzt)`. Multiple plays on the same day collapse to a single row.
- Playing a lesson also flips `LessonProgress.is_completed=True` (auto-completion). The manual "Tugatildi" button remains for users who want to mark a lesson done without watching the video.
- `record_view` also calls `_update_streak()` and `_maybe_issue_certificate()`.
- No CSRF-exempt beacon endpoint anymore; `record_view` is `@login_required` + standard CSRF.

### Custom Video Player (`lesson_player.js`)
- **Why it exists:** YouTube's embed draws a title/channel + dark-gradient overlay whenever its chrome is awake (pause with native controls, hover, seeks). It cannot be removed by embed parameters (`showinfo` dead since 2018, `modestbranding` since 2023) — but it *stays asleep* if the iframe never sees a pointer event and never renders native controls. So the player loads with `playerVars: {controls:0, disablekb:1, playsinline:1, iv_load_policy:3, fs:0, rel:0}`, the iframe is `pointer-events:none`, and all interaction goes through our own chrome driving the IFrame API.
- **Markup** lives in `lesson_detail.html` inside `.video-wrapper.vp`: a gesture layer (`#vp-gesture`, click = instant play/pause, dblclick = fullscreen — the double-click's two click events cancel out, same as youtube.com), a buffering spinner (`#vp-spinner`, shown on `BUFFERING` and while a queued play waits for the player to bootstrap), a control bar (`#vp-bar`: seek slider, play/pause, mute + volume, elapsed/total time, playback-rate cycle button, fullscreen), a poster cover (`#vp-poster`, YT `maxresdefault` → `hqdefault` fallback, hides on first `PLAYING`), and an end overlay (`#vp-end`: "Qayta ko'rish" + "Keyingi dars →" — covers YouTube's related-videos wall and keeps navigation forward).
- **Slow-network resilience:** a click on play before the IFrame API has bootstrapped is queued (`pendingPlay`) and flushed in `onReady` instead of being dropped, with the spinner as immediate feedback. The play/pause icon follows `playIntent`, and intent only changes on **solid evidence** — never on YT's `getPlayerState()` cache alone, because on slow networks both the cache and the time updates lag seconds behind reality or arrive in bursts (observed in prod: video visibly playing while the cache still says paused). A 250 ms ticker runs permanently from `onReady`; on each tick an organic clock delta (0.01–1.5 s, so seeks don't count) refreshes `lastMoveAt`, and `moving` = clock moved within `MOVE_STICKY_MS` (2.5 s — bursty updates can't fake a freeze). Intent upgrades to playing when `moving`; it downgrades only when the clock has been frozen past the sticky window **and** the cache agrees (paused/ended/cued). Real `PLAYING`/`PAUSED`/`ENDED` events still set intent for snappiness (a `PAUSED`/`ENDED` straggler within 1.5 s of a fresh play is ignored), and for `INTENT_GRACE_MS` (3 s, deliberately > sticky) after an explicit play/pause no evidence may override the user. The spinner shows on `BUFFERING` while the clock isn't moving.
- **No quality selector (deliberate, for now):** the IFrame API cannot set video quality (`setPlaybackQuality` has been a no-op since 2019); the only real quality menu is YouTube's native gear, which our chrome disables. A "native YouTube mode" toggle that rebuilt the player with `controls:1` was built and verified on 2026-07-15 but shelved (its exit pill covered YT's top-right controls) — full rationale and restore-ready code: `docs/native-quality-mode.md`.
- `lesson_tracker.js` still owns the `YT.Player` instance (view/complete tracking unchanged); it hands the reference to the chrome via `window.__vpSetPlayer(player)` (same pattern as `__bmSetPlayer` for bookmarks). `lesson_player.js` is included **before** `lesson_tracker.js` on video lessons.
- **SVG icon toggling gotcha:** the bar's icon pairs (play/pause, vol/muted, max/min) are `<svg>` elements, and `SVGElement` has **no** `hidden` property — `el.hidden = x` is a silent no-op expando (this shipped broken: the play icon never changed for anyone, while DOM probes of `.hidden` read the expando back and looked correct). They must be toggled via the attribute (`setHidden()` helper: `setAttribute('hidden','')` / `removeAttribute('hidden')`), which the `.vp svg[hidden]{display:none}` rule then honors. Verify icon changes by rendered pixels (screenshot), not by reading properties.
- Control bar auto-hides after 3.6 s of mouse idle while playing (`.vp-idle`) — deliberately longer than YouTube's own awake-chrome fade at play-start, so the two panels don't vanish in a staggered two-step; always visible when paused/ended. Volume/mute/rate persist in `localStorage` (`vp:vol`, `vp:muted`, `vp:rate`). Keyboard: `space`/`k` toggle, `←`/`→` ±5 s, `m` mute, `f` fullscreen — suppressed while typing in inputs/textareas or when a control outside the player has focus. Fullscreen is wrapper-level (`shell.requestFullscreen()`, CSS `position:fixed` fallback for iOS) so our bar stays on top.
- **Residual YouTube chrome (accepted, irreducible):** the title overlay still flashes for ~3–4 s at play-start, after a resume, and after a seek made while playing (those transitions wake the embed's chrome internally; it auto-fades only while playing). Pausing *during* that awake window leaves the overlay visible until the next play; a seek made while cleanly paused does **not** wake it. A pause after ≥5 s of playback (the common case, and the original complaint) is completely clean. The wake-on-play cannot be suppressed: the embed's postMessage `apiInterface` was dumped and probed on 2026-07-10 — there is no controls/chrome-hiding command (`hideVideoInfo` toggles stats-for-nerds; `mutedAutoplay` doesn't start playback from the API; names like `hideControls` aren't in the interface and are ignored). Verified empirically with Playwright screenshots; the sleep/wake behavior is not documented by YouTube and may change.

### HTML Cache Policy
- `learning.middleware.HtmlNoCacheMiddleware` (last in `MIDDLEWARE`) adds `Cache-Control: no-cache` to every HTML response that doesn't set its own cache header. Static assets are manifest-hashed/immutable, but the HTML naming them shipped with no cache headers, so a browser could keep reusing a stale page — and its old hashed asset URLs — after a deploy (seen in prod: a user exercising superseded player JS). `no-cache` = store but revalidate, so bfcache still works. Non-HTML responses (robots.txt, sitemap.xml, JSON endpoints, WhiteNoise-served static) are untouched.

### Streak System
- Updated whenever a `LessonView` is recorded **or** the manual complete button is pressed.
- `current_streak` = consecutive days with at least one qualifying activity; `longest_streak` = max ever seen.
- `current_streak` is only bumped on activity, so the stored value goes stale once a user lapses. Displays (dashboard + leaderboard) read `UserProfile.live_streak`, which returns the stored streak only when the last activity was today or yesterday and `0` once it has been broken.
- All streak calculations use Asia/Tashkent timezone (`_today_uzt()` in `learning/views.py`; `live_streak` uses `timezone.localdate()`, which resolves to the same `Asia/Tashkent` date).

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
- All public catalog views (`CourseListView`, `SearchView`, `CategoryDetailView`, `HomeView`) filter to `status='published'` — `SearchView`'s lesson results are scoped to `module__course__status='published'` too, so draft lessons never leak into search.
- `CourseDetailView`, `ModuleDetailView`, and `LessonDetailView` all return 404 for non-published courses unless the user is staff/superuser, so a draft course's modules and lessons aren't reachable by direct URL.
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

## SEO / Discoverability

Organic-search foundation, wired so every page ships rich metadata with no per-page boilerplate.

- **Canonical origin**: `SITE_URL` (env, default `https://ochiqkurs.uz`) is the deterministic base for all absolute URLs — set so canonical/OG links don't depend on the request host or proxy scheme. `SECURE_PROXY_SSL_HEADER` lets `request.scheme` resolve to `https` behind Cloudflare.
- **Context processor** `learning.context_processors.seo` injects site-wide defaults (`meta_description`, `og_title`, `og_image`, `og_type`, `canonical_url`, verification/analytics tokens) into every template. Views override the per-page values by putting the same keys in their own context. `absolute_url(path)` turns a relative/media path into a `SITE_URL`-rooted URL and leaves already-absolute URLs (e.g. YouTube thumbs) untouched.
- **Meta tags**: `templates/includes/seo_meta.html` (included from `base.html` `<head>`) renders the description, `<link rel="canonical">`, Open Graph, and Twitter `summary_large_image` cards. `og:image` defaults to `course-hero-placeholder.png`; course/lesson pages use `Course.get_thumbnail_url()` made absolute.
- **JSON-LD** via the `{% jsonld data %}` tag (`learning_extras.py`, escapes `<` so user strings can't break out of the `<script>`). Built in views and rendered in each template's `{% block extra_head %}`:
  - Home → `WebSite` (with a `SearchAction` sitelinks search box pointing at `/malaka/qidiruv/?q=`) + `Organization`.
  - Course detail → `Course` (provider, `inLanguage=uz`, image, instructor, free `Offer`, `aggregateRating` when `rating_count`).
  - Lesson detail → `VideoObject` for video lessons (thumbnail, embedUrl, ISO-8601 `duration`).
- **Sitemap** at `/sitemap.xml` (`learning/sitemaps.py`, `SITEMAPS`): static views, published courses (`lastmod=published_at`), categories, learning paths, instructors. Domain comes from the request host (no `django.contrib.sites`); `protocol='https'`. Models expose `get_absolute_url()` for this.
- **robots.txt** at `/robots.txt` (`robots_txt` view in `config/urls.py`): disallows `/admin/`, `/api/`, `/users/`; advertises the sitemap. (Cloudflare prepends its own managed/content-signal block ahead of ours on the live response.)
- **Google site verification** — two supported methods, both env-gated:
  - *HTML tag*: `GOOGLE_SITE_VERIFICATION` renders a `<meta name="google-site-verification">`.
  - *HTML file* (**what prod uses**): `GOOGLE_VERIFICATION_FILE` is the filename Google issues (e.g. `google<hash>.html`); when set, `config.urls.google_verification_file` serves it at the site root with the expected `google-site-verification: <filename>` body. The route is registered at import time only when the env var is set (token stays out of source).
- **Cloudflare Web Analytics**: the site is proxied through Cloudflare, so it uses **"automatic setup"** — Cloudflare injects the beacon at the edge, **no token needed**. `CLOUDFLARE_ANALYTICS_TOKEN` is therefore left **empty** in prod (it would render our own beacon and double-count). It exists only for a non-proxied/manual setup.
- **Live state** (set up 2026-06-21): domain verified in Search Console via the HTML-file method, `/sitemap.xml` submitted (Success), Cloudflare Web Analytics on automatic. After future deploys nothing extra is needed; the sitemap/verification/analytics stay live on defaults + the prod `.env` vars.

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
