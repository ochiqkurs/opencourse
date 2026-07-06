---
name: module-konspekt
description: Write a detailed konspekt (article lesson) summarizing an Ochiq Kurs module — structure, tone, depth and SQL insert pattern. Use when asked to add a konspekt/maqola/article dars to a module or expand an existing thin one.
---

# Module konspekt writer

A konspekt is an `article`-type lesson placed at the end of a module (right
before the module test). It is the student's re-readable reference for
everything the module's videos taught. Written in Uzbek, Markdown
(`fenced_code` + `tables` extensions are enabled; highlight.js colors code).

## Depth: this is a chapter, not a recap

Model the structure on python.sariq.dev lessons (explain-then-show, output
after every example), but keep the tone neutral-instructional — plain statements,
no "Keling…"-style chattiness. And remember scale: **their page covers ONE
video; a konspekt covers a whole MODULE**. Target ≈700–1200 Uzbek words of
prose PLUS code blocks and tables (small intro/outro modules may be shorter) —
every lesson in the module gets real coverage, not a one-line mention. The
14 konspekts of `pythonda-dasturlash-asoslari` are the reference examples.

Structure:

1. One-sentence opener: what this module covered.
2. **One `##` section per topic/lesson** in the module's order. In each:
   - explain the concept in 2–4 sentences (why it exists, not just what);
   - a runnable code example, followed by its output:
     ```python
     print("Salom")
     ```
     `Natija:` `Salom` — show the result explicitly, sariq.dev-style;
   - a common beginner mistake for that topic and how to read/fix its error.
3. A comparison table where topics contrast (list vs tuple, `/` vs `//`,
   pickle vs json…).
4. **`## Amaliyot`** at the end: 3–5 numbered practice tasks with real-world
   framing, ordered easy→hard, solvable using only this module + earlier ones.
5. Closing line pointing to the module test.

Rules: no filler enthusiasm, no emoji-as-icons; code samples must actually run
(check apostrophes — Uzbek text uses `'` U+2019, code strings use ASCII quotes);
don't teach material from later modules.

## Placement / schema

- `lesson_type='article'`, content in `content` (Markdown), plus a 1–2 sentence
  `description` (it becomes the page's meta description).
- Title `"<Mavzu> — konspekt"`, slug `"<module-slug>-konspekt"`, empty
  `youtube_video_id`, `duration_seconds` NULL, `order` = MAX+1 in the module
  (before the test lesson if adding both — konspekt first, test after).

## SQL pattern

**Canonical pipeline**: `.claude/skills/course-content/seedlib.py` (in this
repo) — write a `konspekt_<kurs>.py` content module and let
`seedlib.emit_course_sql` produce the SQL; see the `course-content` skill for
the whole-course workflow and the contract. It
handles dollar-quoting (`$md$…$md$`), keying by `module_id + slug`, computed
`order` (konspekt = `MAX(video order)+1`, test after it at `+2`) and the
dependency-ordered deletes (raw SQL gets no ORM cascade).

Two rendering gotchas: bleach strips raw `<sub>/<sup>` in markdown — use
Unicode (₂, ²); run the apostrophe pass (ASCII `'` → `’` between letters,
**outside code fences only**) plus a `[а-яА-Я]` grep before generating. Apply
locally, then render the page (both themes if layout-relevant) and check:
markdown renders, code blocks highlighted, tables don't overflow, sidebar
shows the lesson with the article icon.
