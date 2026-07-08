# -*- coding: utf-8 -*-
"""Shared SQL emitter for course content batches (konspekt + quiz + descriptions).

Content module contract, v2 (slug-keyed — PREFERRED for new files; the same
SQL applies unchanged on local AND prod because serial ids never appear):
  COURSE_SLUG      str  (e.g. "super-django-darslari")
  MODULES          {module_slug: uz_module_title}   # for test slug/title
  DESCRIPTIONS     {(module_slug, lesson_slug): description}
  KONSPEKTS        {module_slug: (title, slug, description, markdown)}
  QUIZZES          {module_slug: [(qtype, text, explanation, [(choice, correct), ...]), ...]}
                   MC/multi choices authored correct-FIRST; emitter shuffles
                   deterministically (quiz-author rule: vary correct position).
  MODULE_TITLES    optional {module_slug: new_title}  (rename modules)
  LESSON_TITLE_FIXES optional {(module_slug, lesson_slug): new_title}

Legacy v1 contract (id-keyed — konspekt_css.py … konspekt_dl94.py) is still
supported: COURSE_ID int, MODULES {module_id: (module_slug, title)},
DESCRIPTIONS {lesson_id: (slug, description)}, KONSPEKTS/QUIZZES keyed by
module_id, LESSON_TITLE_FIXES {lesson_id: (slug, new_title)}. v1 ids diverge
between local and prod for freshly created courses — that's why v2 exists.
"""
import random


def esc(s, tag="$$"):
    assert tag not in s, s[:80]
    return s


def lesson_delete_block(mid, slug):
    sub = (f"SELECT id FROM learning_lesson WHERE module_id = {mid} "
           f"AND slug = '{slug}'")
    return f"""
DELETE FROM learning_quizanswer_selected_choices WHERE quizanswer_id IN (
  SELECT qa.id FROM learning_quizanswer qa
  JOIN learning_quizattempt t ON qa.attempt_id = t.id
  JOIN learning_quiz q ON t.quiz_id = q.id WHERE q.lesson_id IN ({sub}));
DELETE FROM learning_quizanswer WHERE attempt_id IN (
  SELECT t.id FROM learning_quizattempt t JOIN learning_quiz q ON t.quiz_id = q.id
  WHERE q.lesson_id IN ({sub}));
DELETE FROM learning_quizattempt WHERE quiz_id IN (
  SELECT id FROM learning_quiz WHERE lesson_id IN ({sub}));
DELETE FROM learning_quizchoice WHERE question_id IN (
  SELECT qq.id FROM learning_quizquestion qq JOIN learning_quiz q ON qq.quiz_id = q.id
  WHERE q.lesson_id IN ({sub}));
DELETE FROM learning_quizquestion WHERE quiz_id IN (
  SELECT id FROM learning_quiz WHERE lesson_id IN ({sub}));
DELETE FROM learning_quiz WHERE lesson_id IN ({sub});
DELETE FROM learning_lessonanswer WHERE question_id IN (
  SELECT lq.id FROM learning_lessonquestion lq WHERE lq.lesson_id IN ({sub}));
DELETE FROM learning_lessonquestion WHERE lesson_id IN ({sub});
DELETE FROM learning_lessonprogress WHERE lesson_id IN ({sub});
DELETE FROM learning_lessonview WHERE lesson_id IN ({sub});
DELETE FROM learning_note WHERE lesson_id IN ({sub});
DELETE FROM learning_videobookmark WHERE lesson_id IN ({sub});
DELETE FROM learning_lessonresource WHERE lesson_id IN ({sub});
DELETE FROM learning_lesson WHERE module_id = {mid} AND slug = '{slug}';"""


def course_ref(content):
    """Course reference for SQL: int id (v1) or a slug subselect (v2)."""
    slug = getattr(content, "COURSE_SLUG", None)
    if slug:
        return f"(SELECT id FROM learning_course WHERE slug = '{slug}')"
    return content.COURSE_ID


def emit_course_sql(content, out_path):
    v2 = bool(getattr(content, "COURSE_SLUG", None))
    cid = course_ref(content)
    course_label = getattr(content, "COURSE_SLUG", None) or content.COURSE_ID

    if v2:
        # normalize both contracts to: modules {key: (m_slug, m_title)},
        # mref(key) -> SQL expression for the module id
        modules = {s: (s, t) for s, t in content.MODULES.items()}

        def mref(key):
            return (f"(SELECT id FROM learning_module WHERE course_id = {cid} "
                    f"AND slug = '{key}')")
    else:
        modules = content.MODULES

        def mref(key):
            return key

    out = ["BEGIN;", f"-- ==== course {course_label}: titles / fixes ===="]

    for mk, title in getattr(content, "MODULE_TITLES", {}).items():
        out.append(f"UPDATE learning_module SET title = $${esc(title)}$$ "
                   f"WHERE id = {mref(mk)} AND course_id = {cid};")
    for key, val in getattr(content, "LESSON_TITLE_FIXES", {}).items():
        if v2:
            (m_slug, l_slug), title = key, val
            out.append(f"UPDATE learning_lesson SET title = $${esc(title)}$$ "
                       f"WHERE module_id = {mref(m_slug)} AND slug = '{l_slug}';")
        else:
            lid, (slug, title) = key, val
            out.append(f"UPDATE learning_lesson SET title = $${esc(title)}$$ "
                       f"WHERE id = {lid} AND slug = '{slug}';")

    out.append("\n-- ==== lesson descriptions ====")
    for key, val in content.DESCRIPTIONS.items():
        if v2:
            (m_slug, l_slug), desc = key, val
            out.append(f"UPDATE learning_lesson SET description = $${esc(desc)}$$ "
                       f"WHERE module_id = {mref(m_slug)} AND slug = '{l_slug}';")
        else:
            lid, (slug, desc) = key, val
            out.append(f"UPDATE learning_lesson SET description = $${esc(desc)}$$ "
                       f"WHERE id = {lid} AND slug = '{slug}';")

    out.append("\n-- ==== konspekts + quizzes ====")
    pos_stat = {1: 0, 2: 0, 3: 0, 4: 0}
    for mk in sorted(content.KONSPEKTS):
        k_title, k_slug, k_desc, k_md = content.KONSPEKTS[mk]
        m_slug, m_title = modules[mk]
        mid = mref(mk)
        q_slug = f"{m_slug}-test"
        q_title = f"{m_title} — test"
        max_video = (f"(SELECT MAX(\"order\") FROM learning_lesson v "
                     f"WHERE v.module_id = {mid} AND v.lesson_type = 'video')")

        out.append(f"\n-- module {mk}: {k_slug} + {q_slug}")
        out.append(lesson_delete_block(mid, k_slug))
        out.append(lesson_delete_block(mid, q_slug))
        out.append(f"""
INSERT INTO learning_lesson (title, slug, description, youtube_video_id,
  "order", module_id, duration_seconds, is_preview, content, lesson_type)
VALUES ($${esc(k_title)}$$, '{k_slug}', $${esc(k_desc)}$$, '',
  {max_video} + 1, {mid}, NULL, FALSE, $md${esc(k_md, "$md$")}$md$, 'article');

INSERT INTO learning_lesson (title, slug, description, youtube_video_id,
  "order", module_id, duration_seconds, is_preview, content, lesson_type)
VALUES ($${esc(q_title)}$$, '{q_slug}', $${esc(m_title)} bo’yicha qisqa test.$$, '',
  {max_video} + 2, {mid}, NULL, FALSE, '', 'quiz');

INSERT INTO learning_quiz (title, description, pass_percent, max_attempts, created_at, lesson_id)
VALUES ($${esc(q_title)}$$, '', 70, 0, NOW(),
  (SELECT id FROM learning_lesson WHERE module_id = {mid} AND slug = '{q_slug}'));""")

        quiz_sub = (f"(SELECT q.id FROM learning_quiz q JOIN learning_lesson l "
                    f"ON q.lesson_id = l.id WHERE l.module_id = {mid} "
                    f"AND l.slug = '{q_slug}')")
        for qi, (qtype, text, expl, choices) in enumerate(content.QUIZZES[mk], start=1):
            out.append(f"""
INSERT INTO learning_quizquestion (question_type, text, "order", explanation, quiz_id)
VALUES ('{qtype}', $${esc(text)}$$, {qi}, $${esc(expl)}$$, {quiz_sub});""")
            ch = list(choices)
            if qtype != "true_false":
                random.Random(f"{mk}-{qi}").shuffle(ch)
            q_sub = (f"(SELECT qq.id FROM learning_quizquestion qq "
                     f"WHERE qq.quiz_id = {quiz_sub} AND qq.\"order\" = {qi})")
            for ci, (ctext, correct) in enumerate(ch, start=1):
                if qtype == "multiple_choice" and correct:
                    pos_stat[ci] += 1
                out.append(
                    f"INSERT INTO learning_quizchoice (text, is_correct, \"order\", question_id) "
                    f"VALUES ($${esc(ctext)}$$, {'TRUE' if correct else 'FALSE'}, {ci}, {q_sub});"
                )

    out.append("COMMIT;")
    with open(out_path, "w") as f:
        f.write("\n".join(out) + "\n")
    n_q = sum(len(v) for v in content.QUIZZES.values())
    print(f"wrote {out_path}: {len(content.DESCRIPTIONS)} descriptions, "
          f"{len(content.KONSPEKTS)} konspekts, {n_q} questions")
    print(f"MC correct positions 1..4: {pos_stat}")
