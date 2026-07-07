---
name: quiz-author
description: Author quiz (test) lessons for Ochiq Kurs modules — question writing rules, choice-position balancing, DB schema and idempotent SQL patterns. Use when asked to add tests/savollar/quiz to a course or module, or to review existing quiz content.
---

# Quiz author

Creates a `quiz`-type lesson at the end of a module plus its `Quiz` →
`QuizQuestion` → `QuizChoice` rows. All content in Uzbek, `'` (U+2019) apostrophe.

## The #1 rule: vary the correct answer's position

**Never leave the correct choice as option 1.** The site renders choices in
`order` — it does not shuffle. Distribute correct answers roughly evenly across
positions 1–4. When generating via script, shuffle deterministically:

```python
random.Random(f'{module_id}-{q_order}').shuffle(choices)
```

Verify before delivering (should be ~evenly spread, never all on 1):

```sql
SELECT qc."order", count(*) FROM learning_quizchoice qc
JOIN learning_quizquestion qq ON qq.id=qc.question_id
WHERE qc.is_correct AND qq.question_type='multiple_choice'
  AND qq.quiz_id IN (<new quiz ids>) GROUP BY 1 ORDER BY 1;
```

## Question writing rules

- **5 questions per module test**: ~3 `multiple_choice` (4 choices, 1 correct),
  1 `true_false`, and where it fits 1 `multi_select` (4 choices, 2–3 correct —
  grading is exact-set match, so make correct ones unambiguous).
- Test **what the module actually taught** — read the module's lesson titles
  (and konspekt if present) first. No trivia beyond the videos.
- Every question gets an `explanation` (one sentence, shown after answering —
  say *why*, don't just repeat the answer).
- Wrong choices must be plausible (typical beginner confusions), never joke or
  filler options.
- `true_false` choices are exactly `To'g'ri` (order 1) and `Noto'g'ri` (order 2)
  — this pair is conventional, do NOT shuffle it; vary which one is correct.

## Schema / conventions

- Lesson: `lesson_type='quiz'`, title `"<Mavzu> — test"`, slug
  `"<module-slug>-test"`, empty `content`/`youtube_video_id`, `order` = MAX+1 in
  module (unique_together is `(module, slug)`).
- Quiz: same title, `pass_percent=70`, `max_attempts=0` (unlimited).
- Question `order` 1..5; choice `order` 1..4.

## SQL pattern

**Canonical pipeline**: `.claude/skills/course-content/seedlib.py` (in this
repo) — author questions in a `konspekt_<kurs>.py` content module (`QUIZZES`
dict, choices written **correct-first**; seedlib shuffles them with
`random.Random(f"{mid}-{qi}")`) and let `seedlib.emit_course_sql` produce the
SQL; see the `course-content` skill for the whole-course workflow. It emits idempotent per-module deletes first,
inserts keyed by `module_id + slug` subselects, and computed `order`
(test = `MAX(video)+2`, right after the konspekt). **Raw SQL bypasses
Django's ORM cascade** — dependents are deleted in order (quizanswer m2m →
quizanswer → quizattempt → quizchoice → quizquestion → quiz → lessonprogress /
lessonview / note / videobookmark → lesson), exactly as seedlib does.

If the course already has hand-made quizzes with real attempts, **keep them** —
only fill gaps (e.g. empty explanations, guarded by `AND explanation = ''`).

Apply + verify with the course-content skill's
`.claude/skills/course-content/pipeline.sh` (one command: generate, apply
twice, DB invariants incl. no correct-less questions, render check; `--prod`
ships it). Quiz pages logged-out should 200 with a login prompt.
