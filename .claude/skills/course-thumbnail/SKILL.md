---
name: course-thumbnail
description: Generate the branded Ochiq Kurs thumbnail (1280x720 PNG) for a course, learning path, or any card image. Use whenever a new course/path is added, a thumbnail is missing or off-brand, or the user asks for a course rasmi/thumbnail/muqova.
---

# Course thumbnail generator

Produces the standard Ochiq Kurs card image: flat emerald-charcoal background
(`#0A1411`), solid category-accent tick + label, big Bricolage Grotesque title,
`OCHIQ KURS` wordmark, one subtle radial glow. No gradients, no emoji, no stock
imagery — this matches the site's de-genericized design system.

## Usage

One image (new course, or a path — use label `YO'NALISH` for paths):

```bash
python .claude/skills/course-thumbnail/generate.py \
  --title "Kurs nomi" --label "BACKEND" --color emerald \
  --out media/course_thumbnails/kurs-slug.png
```

Regenerate every course from the local DB (prints the `UPDATE` SQL to stdout):

```bash
python .claude/skills/course-thumbnail/generate.py --all-courses media/
```

Run with the project venv python (needs Pillow). Fonts ship in `fonts/`
(Bricolage Grotesque + Hanken Grotesk variable TTFs, OFL-licensed).

## Rules

- **`--color` must be the course's `Category.color`** (sky, emerald, violet,
  amber, slate, rose, indigo) and **`--label` its `Category.name`** — query the
  DB, don't guess. Consistency per category is the point.
- File name = course slug; goes to `media/course_thumbnails/<slug>.png`
  (paths: `media/path_thumbnails/<slug>.png`). Then set the DB field:
  `UPDATE learning_course SET thumbnail='course_thumbnails/<slug>.png' WHERE slug='<slug>';`
- After generating, **look at the PNG** (Read tool) — check the title wraps to
  ≤3 lines and nothing collides. Long titles auto-shrink, but verify.
- For prod: rsync the PNGs to `myserver:~/opencourse/media/course_thumbnails/`
  and run the same UPDATE via `manage.py dbshell`. Never regenerate on prod —
  generate locally, ship files.
- Don't restyle (colors, fonts, layout) without an explicit ask; if the design
  system changes, update this script rather than one-off images.
