---
name: course-description
description: Write the subtitle + Markdown description for an Ochiq Kurs course (SEO meta + "Kurs haqida" block). Use when a course is added or its tavsif/subtitle/description needs writing or improving.
---

# Course description writer

Fills `Course.subtitle` and `Course.description`. Both are user-facing AND
SEO-critical: the subtitle is the page's meta description (`_meta_desc` uses it
first), the description renders as Markdown in the "Kurs haqida" block. Uzbek,
`'` (U+2019) apostrophe.

## Subtitle (1 line, ≤ ~140 chars)

Concrete promise + scope, readable as a search snippet. Pattern that works:
*hook/positioning: topic list — qualifier*.

> `Python'ni noldan o'rganing: o'zgaruvchilar, shartlar, funksiyalar, OOP va
> amaliy loyihalar — barchasi o'zbek tilida.`

## Description (2 short paragraphs, Markdown)

- **P1 — what & why:** what the technology is / why it matters (a verifiable
  claim beats hype: "Docker, Kubernetes aynan Go'da yozilgan"), then what the
  course concretely covers — name the actual topics from the course's modules
  (query them, don't invent).
- **P2 — who & next:** who it's for, what prior knowledge is needed, and the
  natural next course **on this site** (cross-reference real courses:
  "Keyingi qadam — Django REST Framework kursi").

## Tone rules (de-genericization applies to copy too)

- Honest and specific; **no** "eng zo'r", "dunyoni o'zgartiring", exclamation
  stacking, or promises about jobs/salaries.
- No emoji. No filler ("Ushbu ajoyib kursda…").
- Don't state lesson counts/durations — the page computes those live.
- Mention real course-specific facts (projects built, tools used) — read the
  module/lesson titles first.
- Vary sentence openings across courses; 73 identical "Bu kursda …" first lines
  is an AI tell.

## Applying

Idempotent SQL keyed by slug, dollar-quoted (see
`~/tech/open-course/content-seed-2026-07-05/01_course_meta_*.sql`, outside this
repo on the dev Mac, for 73 examples of the style — or read any live course row):

```sql
UPDATE learning_course SET
  subtitle = $$…$$,
  description = $$…

…$$
WHERE slug = 'kurs-slug';
```

Apply locally first; verify by loading the course page — check the
`<meta name="description">` and the rendered "Kurs haqida" block. Watch for
stray Cyrillic characters slipping into Latin Uzbek text (grep `[а-яА-Я]`).
