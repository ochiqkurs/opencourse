#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic course-creation SQL emitter: playlist -> course + modules + lessons.

Replaces the per-course gen_<kurs>.py boilerplate: author ONE data module and
this script emits fully slug-keyed SQL (no serial ids), so the same file
applies unchanged on local and prod.

Data-module contract (course_<kurs>.py):
  COURSE = {
    "slug": "super-django-darslari",
    "title": "Super Django darslari",          # ASCII ' (site title style)
    "subtitle": "...",                          # <=~140 chars, meta description
    "description": "...",                       # 2 paragraphs, Markdown
    "instructor_name": "Timur Karabaev",
    "level": "beginner",                        # beginner|intermediate|advanced
    "category_id": 2,                           # SELECT id,name,color FROM learning_category
    "order": 76,                                # SELECT max("order")+1 FROM learning_course
    # optional: "language": "O'zbek", "is_featured": False
  }
  PLAYLIST_JSON = "django_timur.json"   # fetch_playlist.py output, relative to data module
  MODULES = [                            # lesson pos = "pos" field in the playlist JSON
    ("Module title", "module-slug", [
        (pos, "Lesson title", "lesson-slug", "1-2 sentence description"),
        ...]),
    ...]
  LEARNING_PATH = None                   # or ("path-slug", position) — think first:
                                         # don't duplicate an existing path course

Prose fields (subtitle/description/lesson descriptions) get the U+2019
apostrophe pass automatically; titles/slugs are left as authored.

Usage: new_course.py course_<kurs>.py [-o out.sql]
"""
import importlib.util
import json
import os
import re
import sys

APO = re.compile(r"(?<=[a-zA-Z])'(?=[a-zA-Z])")

DELETE_TEMPLATE = """
-- ---- wipe existing lessons of course {cid} (dependents first: no ORM cascade in raw SQL) ----
DELETE FROM learning_quizanswer_selected_choices WHERE quizanswer_id IN (
  SELECT qa.id FROM learning_quizanswer qa
  JOIN learning_quizattempt t ON qa.attempt_id = t.id
  JOIN learning_quiz q ON t.quiz_id = q.id
  WHERE q.lesson_id IN (SELECT l.id FROM learning_lesson l JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid}));
DELETE FROM learning_quizanswer WHERE attempt_id IN (
  SELECT t.id FROM learning_quizattempt t JOIN learning_quiz q ON t.quiz_id = q.id
  WHERE q.lesson_id IN (SELECT l.id FROM learning_lesson l JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid}));
DELETE FROM learning_quizattempt WHERE quiz_id IN (
  SELECT q.id FROM learning_quiz q
  WHERE q.lesson_id IN (SELECT l.id FROM learning_lesson l JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid}));
DELETE FROM learning_quizchoice WHERE question_id IN (
  SELECT qq.id FROM learning_quizquestion qq JOIN learning_quiz q ON qq.quiz_id = q.id
  WHERE q.lesson_id IN (SELECT l.id FROM learning_lesson l JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid}));
DELETE FROM learning_quizquestion WHERE quiz_id IN (
  SELECT q.id FROM learning_quiz q
  WHERE q.lesson_id IN (SELECT l.id FROM learning_lesson l JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid}));
DELETE FROM learning_quiz WHERE lesson_id IN (
  SELECT l.id FROM learning_lesson l JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid});
DELETE FROM learning_lessonanswer WHERE question_id IN (
  SELECT lq.id FROM learning_lessonquestion lq
  JOIN learning_lesson l ON lq.lesson_id = l.id JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid});
DELETE FROM learning_lessonquestion WHERE lesson_id IN (
  SELECT l.id FROM learning_lesson l JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid});
DELETE FROM learning_lessonprogress WHERE lesson_id IN (
  SELECT l.id FROM learning_lesson l JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid});
DELETE FROM learning_lessonview WHERE lesson_id IN (
  SELECT l.id FROM learning_lesson l JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid});
DELETE FROM learning_note WHERE lesson_id IN (
  SELECT l.id FROM learning_lesson l JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid});
DELETE FROM learning_videobookmark WHERE lesson_id IN (
  SELECT l.id FROM learning_lesson l JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid});
DELETE FROM learning_lessonresource WHERE lesson_id IN (
  SELECT l.id FROM learning_lesson l JOIN learning_module m ON l.module_id = m.id WHERE m.course_id = {cid});
DELETE FROM learning_lesson WHERE module_id IN (
  SELECT m.id FROM learning_module m WHERE m.course_id = {cid});
DELETE FROM learning_module WHERE course_id = {cid};
"""


def esc(s):
    assert "$$" not in s, s[:80]
    return s


def prose(s):
    """U+2019 apostrophe pass for user-facing prose (not titles/slugs)."""
    return APO.sub("’", s)


def load_data_module(path):
    path = os.path.abspath(path)
    spec = importlib.util.spec_from_file_location(
        os.path.basename(path)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.__dir__path = os.path.dirname(path)
    return mod


def emit_new_course_sql(data, out_path):
    c = data.COURSE
    slug = c["slug"]
    assert re.fullmatch(r"[a-z0-9-]+", slug), slug
    cid = f"(SELECT id FROM learning_course WHERE slug = '{slug}')"

    playlist = os.path.join(data.__dir__path, data.PLAYLIST_JSON)
    by_pos = {v["pos"]: v for v in json.load(open(playlist))}

    title = c["title"]
    subtitle = prose(c["subtitle"])
    description = prose(c["description"])
    language = c.get("language", "O'zbek")
    featured = "TRUE" if c.get("is_featured") else "FALSE"

    out = ["BEGIN;"]
    out.append(f"""
-- ---- course upsert (keyed by slug) ----
INSERT INTO learning_course (title, slug, description, "order", thumbnail, avg_rating,
  instructor_bio, instructor_name, is_featured, language, level, rating_count,
  requirements, subtitle, what_you_learn, category_id, published_at, status)
SELECT $${esc(title)}$$, '{slug}', $${esc(description)}$$, {c["order"]},
  'course_thumbnails/{slug}.png', 0, '', $${esc(c["instructor_name"])}$$, {featured},
  $${esc(language)}$$, '{c["level"]}', 0, '', $${esc(subtitle)}$$, '',
  {c["category_id"]}, NOW(), 'published'
WHERE NOT EXISTS (SELECT 1 FROM learning_course WHERE slug = '{slug}');

UPDATE learning_course SET
  title = $${esc(title)}$$, description = $${esc(description)}$$,
  subtitle = $${esc(subtitle)}$$, instructor_name = $${esc(c["instructor_name"])}$$,
  level = '{c["level"]}', category_id = {c["category_id"]}, status = 'published',
  thumbnail = 'course_thumbnails/{slug}.png'
WHERE slug = '{slug}';""")

    out.append(DELETE_TEMPLATE.format(cid=cid))

    n, total = 0, 0
    for m_order, (m_title, m_slug, lessons) in enumerate(data.MODULES, start=1):
        assert re.fullmatch(r"[a-z0-9-]+", m_slug), m_slug
        out.append(
            'INSERT INTO learning_module (title, slug, description, "order", course_id)\n'
            f"VALUES ($${esc(m_title)}$$, '{m_slug}', '', {m_order}, {cid});"
        )
        mid = f"(SELECT id FROM learning_module WHERE slug = '{m_slug}' AND course_id = {cid})"
        for l_order, (pos, l_title, l_slug, desc) in enumerate(lessons, start=1):
            v = by_pos[pos]
            assert not v.get("dead") and v.get("embeddable", True), (pos, v)
            out.append(
                "INSERT INTO learning_lesson (title, slug, description, youtube_video_id, "
                '"order", module_id, duration_seconds, is_preview, content, lesson_type)\n'
                f"VALUES ($${esc(l_title)}$$, '{l_slug}', $${esc(prose(desc))}$$, "
                f"'{v['video_id']}', {l_order}, {mid}, {v['duration_s']}, FALSE, '', 'video');"
            )
            n += 1
            total += v["duration_s"]

    lp = getattr(data, "LEARNING_PATH", None)
    if lp:
        path_slug, position = lp
        pid = f"(SELECT id FROM learning_learningpath WHERE slug = '{path_slug}')"
        out.append(f"""
-- ---- learning path: {path_slug} position {position} ----
INSERT INTO learning_learningpathcourse (path_id, course_id, "order")
SELECT {pid}, {cid}, {position}
ON CONFLICT (path_id, course_id) DO NOTHING;""")

    out.append("COMMIT;")
    with open(out_path, "w") as f:
        f.write("\n\n".join(out) + "\n")

    print(f"wrote {out_path}: {len(data.MODULES)} modules, {n} lessons, "
          f"total {total // 3600}h{total % 3600 // 60:02d}m")
    print(slug)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "-o"]
    if "-o" in sys.argv:
        data_path, out_path = args[0], args[1]
    else:
        data_path = args[0]
        out_path = os.path.splitext(os.path.abspath(data_path))[0] + ".sql"
    emit_new_course_sql(load_data_module(data_path), out_path)
