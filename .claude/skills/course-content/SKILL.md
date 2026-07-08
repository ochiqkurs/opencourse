---
name: course-content
description: Add a new Ochiq Kurs course from a YouTube playlist and/or fill a course with module konspekts, tests and lesson descriptions in one batch, using the shared seedlib pipeline. Use when asked to add a course ("kurs qo'sh"), "kursni to'ldir/jihozla", add konspekt+test to a whole course, or extend the treatment to a new course or learning path.
---

# Course content filler (new course + whole-course batch)

Covers the two halves of shipping a course: **creating it from a playlist**
(course + modules + lessons + thumbnail) and the full content treatment
(per-module **konspekt** + **test** + a 1–2 sentence **description for every
lesson**). Authoring rules live in the sibling skills — read `module-konspekt`
for konspekt structure/tone, `quiz-author` for question rules,
`course-description` for subtitle/description copy; this skill covers the
pipeline around them.

The tooling lives **in this repo, next to this file** — the skill is
self-contained: `fetch_playlist.py` (YouTube API → JSON), `new_course.py`
(course data → SQL), `new-course.sh` (whole course-creation cycle),
`seedlib.py` (konspekt/quiz SQL emitter), `normalize.py` (fence-aware
apostrophe pass), `pipeline.sh` (the whole content generate→verify→prod cycle).
Finished batches (one-off artifacts, deliberately outside the repo) live on
the dev Mac in `~/tech/open-course/content-seed-2026-07-05/`
(`course_superdjango.py` + `konspekt_superdjango.py` are the reference pair
for the current slug-keyed contract; `konspekt_js.py` etc. are older id-keyed
examples). If that directory is unavailable, nothing is lost — write fresh
modules from the contracts below.

## Adding a new course from a playlist

The only LLM work is TWO data files; everything else is one command each.

1. **Fetch + evaluate**:
   `python3 fetch_playlist.py PLAYLIST_ID out.json` (prints titles, durations,
   dead/embeddable flags). Read the listing critically:
   - **Compilation-video gotcha**: playlists often carry long "merged" videos
     duplicating the individual lessons (e.g. a 2h "3 - URLs & VIEWS" next to
     13 short `#03.x` lessons). Sum the durations to confirm, then use only
     the individual lessons.
   - Skip trailers/dead/non-embeddable videos (`new_course.py` asserts on
     dead/embed).
   - Check the course doesn't already exist under another name
     (`SELECT ... WHERE title ILIKE '%<tech>%'`).
2. **Author `course_<kurs>.py`** — the data-module contract is documented in
   `new_course.py`'s docstring (COURSE dict + PLAYLIST_JSON + MODULES +
   optional LEARNING_PATH). Facts you need from the DB, don't guess:
   - `category_id`: `SELECT id, name, color FROM learning_category;`
   - `order`: `SELECT max("order")+1 FROM learning_course;`
   - Slug constraints: module slug unique **per course**, lesson slug unique
     **per module** — so `kirish`/`xulosa` may repeat across modules.
   - Titles use ASCII `'`; prose fields get the U+2019 pass automatically.
   - **Learning paths**: default `LEARNING_PATH = None`. Don't slot a course
     into a path that already covers the same ground (precedent: Super Django
     stayed out of python-backend, which has Django asoslari) — propose,
     let the user decide.
3. **Run** `new-course.sh course_<kurs>.py -o NN_<kurs>_course.sql` —
   Cyrillic check → slug-keyed SQL → apply locally twice (idempotency) →
   invariants (no empty descriptions / video ids, duration > 0) → thumbnail
   via the course-thumbnail skill (category color from DB) → course + first
   lesson render 200. **Look at the PNG** (Read tool) before shipping.
4. **Ship**: same command with `--prod` (backup → apply → invariants → rsync
   thumbnail → live curls). The SQL contains no serial ids, so the same file
   works on both DBs.
5. Then give the course its content: steps below.

## Workflow (content, per course)

**Batch discipline: one course per run.** Authoring several courses in one
session bloats the context (compactions, token burn) and multi-file prod
loops fail messily (a mid-loop failure once silently skipped the files after
it). Author one `konspekt_<kurs>.py`, take it all the way to prod with
`pipeline.sh`, then start the next course fresh.

1. **Inspect structure** — query modules + lessons (order, slug, title):
   the lesson titles are your only source about video content, so read them
   carefully; check for pre-existing quizzes/articles first (see "Existing
   content" below).
2. **Write one content module** `konspekt_<kurs>.py` following the contract
   (below). Author everything in it: konspekts, descriptions, quizzes.
   (When the course was just created via `new_course.py`, lesson descriptions
   are already in the course SQL — leave `DESCRIPTIONS = {}`.)
   Apostrophes: prose uses `’` U+2019, code fences keep ASCII quotes (use
   double quotes in JS/HTML code strings) — the pipeline normalizes prose
   anyway (fence-aware) and hard-fails on Cyrillic look-alikes ("izohи").
3. **Run the local stage**:
   `.claude/skills/course-content/pipeline.sh konspekt_<kurs>.py -o NN_<kurs>_content.sql`
   One command = normalize → Cyrillic check → generate (via `seedlib`) →
   apply locally twice (idempotency proof) → DB invariants (per-module
   1 article + 1 quiz, konspekt before test, no empty descriptions, no
   correct-less questions) → render every new page on a throwaway dev server.
   Also eyeball seedlib's MC position spread in the output (should span 1–4)
   and spot-check one konspekt in the browser if layout could be affected
   (bleach strips `<sub>/<sup>` — use Unicode ₂/² in markdown tables).
4. **Ship**: re-run the same command with `--prod`. The script does a
   local/prod divergence check, fresh backup, scp + dbshell apply, prod
   invariants and live-page curls, then cleans up /tmp.

## Content-module contract (consumed by seedlib.emit_course_sql)

Slug-keyed (current — the emitted SQL carries no serial ids, so one file
applies unchanged on local and prod):

```python
COURSE_SLUG = "super-django-darslari"
MODULES = {"module-slug": "Uzbek module title"}   # test slug/title source
DESCRIPTIONS = {("module-slug", "lesson-slug"): "1-2 sentence description"}
KONSPEKTS = {"module-slug": (title, "module-slug-konspekt", meta_description, markdown)}
QUIZZES = {"module-slug": [(qtype, text, explanation, [(choice, is_correct), ...]), ...]}
MODULE_TITLES = {"module-slug": "New title"}      # optional renames
LESSON_TITLE_FIXES = {("module-slug", "lesson-slug"): "Fixed title"}  # optional
```

Legacy id-keyed modules (`COURSE_ID` + int keys — `konspekt_js.py` …
`konspekt_dl94.py`) still work byte-identically; **don't convert them**, but
write new files slug-keyed. The old **module-id gotcha** (serial ids diverge
local vs prod for freshly created courses → NULL `"order"` or wrong-module
writes → remap via `gen_dl94_prod.py`) only applies to id-keyed files;
`pipeline.sh` still hard-fails id-keyed runs on divergence, and for slug-keyed
runs verifies the course/module slugs exist on prod (if missing: run
`new-course.sh --prod` first).

MC/multi choices are authored **correct-first**; seedlib shuffles them
deterministically (seeded by module key + question index). TF choices stay
fixed To'g'ri/Noto'g'ri — vary *which* is correct across modules. Placement is
computed, never hardcoded: konspekt `order = MAX(video order)+1`, test `+2` —
re-runnable because video orders never change. Deletes are dependency-ordered
(raw SQL gets no ORM cascade) — seedlib handles it. **Re-applying content
deletes quiz attempts and progress on the affected konspekt/test lessons** —
before re-running against prod on a live course, check for real user activity
first and skip if it exists.

## Existing content — don't steamroll it

If a course already has quizzes (check before writing!), inspect them: if they
are hand-made with real attempts and sane correct-position spread, **keep
them** — only fill gaps (e.g. empty `explanation`, guarded with
`AND explanation = ''` so later manual edits are never overwritten). The HTML
course (quiz ids 1–7) is the precedent.

## Honesty limits

Konspekts are written from lesson titles, not from watching the videos. Stay
on standard-curriculum ground, don't invent course-specific details (project
names, instructor's exact phrasing), and tell the user this limitation when
delivering a batch. If a title is ambiguous ("Asoslar", "15"), write the
konspekt section at the safest generic level for that module's topic. Same
for course descriptions: state only the scope the playlist actually covers
(an unfinished series must not be described as complete).
