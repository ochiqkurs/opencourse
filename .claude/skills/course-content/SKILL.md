---
name: course-content
description: Fill an entire Ochiq Kurs course with module konspekts, tests and lesson descriptions in one batch, using the shared seedlib pipeline. Use when asked to "kursni to'ldir/jihozla", add konspekt+test to a whole course, or extend the treatment to a new course or learning path.
---

# Course content filler (whole-course batch)

Orchestrates the full treatment one course gets: per-module **konspekt**
(article lesson) + **test** (quiz lesson) + a 1–2 sentence **description for
every lesson**. Authoring rules live in the sibling skills — read
`module-konspekt` for konspekt structure/tone and `quiz-author` for question
rules; this skill covers the pipeline around them.

The emitter lives **in this repo, next to this file**:
`.claude/skills/course-content/seedlib.py` — the skill is self-contained.
Finished content batches (one-off artifacts, deliberately outside the repo)
live on the dev Mac in `~/tech/open-course/content-seed-2026-07-05/`: the 8
frontend-path courses + Python course are reference examples
(`konspekt_js.py`, `konspekt_react.py`, …; `seedlib.py` there is a symlink
back to this repo's copy). If that directory is unavailable, nothing is lost —
write a fresh content module from the contract below.

## Workflow (per course)

1. **Inspect structure** — query modules + lessons (id, order, slug, title):
   the lesson titles are your only source about video content, so read them
   carefully; check for pre-existing quizzes/articles first (see "Existing
   content" below).
2. **Write one content module** `konspekt_<kurs>.py` following the contract
   (below). Author everything in it: konspekts, descriptions, quizzes.
3. **Normalize apostrophes** — run the regex pass `(?<=[a-zA-Z])'(?=[a-zA-Z])`
   → `’` (U+2019) **outside code fences only** (split on ```` ``` ```` blocks
   first; code keeps ASCII quotes — use double quotes in JS/HTML code strings).
   Then `grep -n '[а-яА-Я]'` — Latin-Uzbek text picks up Cyrillic look-alikes
   ("izohи", "ekranда") surprisingly often.
4. **Generate + apply locally**: 3-line `gen_<kurs>.py` calling
   `seedlib.emit_course_sql(...)` (import it from this skill's directory)
   → `NN_<kurs>_content.sql`; apply with
   `psql -v ON_ERROR_STOP=1 -d ochiqkurs -f`. Local dev server:
   `~/.local/share/virtualenvs/web-site-_VaapEyK/bin/python manage.py
   runserver 8077` (plain `pipenv run` resolves the wrong venv).
5. **Verify** (all must pass):
   - every module: 1 article + 1 quiz, konspekt order **before** test;
   - zero lessons with empty `description` in the course;
   - zero questions without a correct choice;
   - MC correct-answer positions spread across 1–4 (seedlib prints this);
   - konspekt + test pages return 200; tables/code render (bleach strips
     `<sub>/<sup>` — use Unicode ₂/² in markdown tables);
   - re-run the SQL once — idempotency proof.
6. **Prod**: fresh backup (`ssh myserver 'bash ~/backups/pg_backup.sh'`), scp
   the SQL, apply via `manage.py dbshell -- -q -v ON_ERROR_STOP=1 -f`, re-run
   the count checks there, curl 2–3 live pages.

## Content-module contract (consumed by seedlib.emit_course_sql)

```python
COURSE_ID = 23
MODULES = {module_id: ("module-slug", "Uzbek module title")}   # test slug/title source
DESCRIPTIONS = {lesson_id: ("slug", "1-2 sentence description")}  # guarded by id AND slug
KONSPEKTS = {module_id: (title, "slug-konspekt", meta_description, markdown)}
QUIZZES = {module_id: [(qtype, text, explanation, [(choice, is_correct), ...]), ...]}
MODULE_TITLES = {module_id: "New title"}          # optional renames
LESSON_TITLE_FIXES = {lesson_id: ("slug", "Fixed title")}  # optional
```

MC/multi choices are authored **correct-first**; seedlib shuffles them
deterministically (`random.Random(f"{mid}-{qi}")`). TF choices stay fixed
To'g'ri/Noto'g'ri — vary *which* is correct across modules. Placement is
computed, never hardcoded: konspekt `order = MAX(video order)+1`, test `+2` —
re-runnable because video orders never change. Deletes are dependency-ordered
(raw SQL gets no ORM cascade) — seedlib handles it.

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
konspekt section at the safest generic level for that module's topic.
