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

The tooling lives **in this repo, next to this file** — the skill is
self-contained: `seedlib.py` (SQL emitter), `normalize.py` (fence-aware
apostrophe pass), `pipeline.sh` (the whole generate→verify→prod cycle as one
command).
Finished content batches (one-off artifacts, deliberately outside the repo)
live on the dev Mac in `~/tech/open-course/content-seed-2026-07-05/`: the 8
frontend-path courses + Python course are reference examples
(`konspekt_js.py`, `konspekt_react.py`, …; `seedlib.py` there is a symlink
back to this repo's copy). If that directory is unavailable, nothing is lost —
write a fresh content module from the contract below.

## Workflow (per course)

**Batch discipline: one course per run.** Authoring several courses in one
session bloats the context (compactions, token burn) and multi-file prod
loops fail messily (a mid-loop failure once silently skipped the files after
it). Author one `konspekt_<kurs>.py`, take it all the way to prod with
`pipeline.sh`, then start the next course fresh.

1. **Inspect structure** — query modules + lessons (id, order, slug, title):
   the lesson titles are your only source about video content, so read them
   carefully; check for pre-existing quizzes/articles first (see "Existing
   content" below).
2. **Write one content module** `konspekt_<kurs>.py` following the contract
   (below). Author everything in it: konspekts, descriptions, quizzes.
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
4. **Ship**: re-run the same command with `--prod`. The script does the
   module-id divergence check, fresh backup, scp + dbshell apply, prod
   invariants and live-page curls, then cleans up /tmp.

   **Module-id gotcha** (pipeline checks this, know why): for a course
   created recently (separate INSERTs on local and prod), serial module ids
   can DIVERGE between the two DBs — the SQL then fails with a NULL `"order"`
   or silently targets wrong modules. If the check fails, remap the content
   module's ids by slug (see `gen_dl94_prod.py` in the content-seed dir).
   Long-standing courses are safe (local DB is a prod copy).

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
