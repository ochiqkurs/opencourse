"""Read-only query/aggregation helpers ("selectors").

These functions take domain objects (never a request) and return plain data,
so they can be unit-tested without going through the HTTP layer. Anything with
a side effect (writes, streak bumps, certificate issuance) belongs in
``services.py`` instead — this module must stay free of writes.
"""

from dataclasses import dataclass, field

from .models import LessonProgress


@dataclass
class CourseProgress:
    """A user's progress across one course.

    ``modules_data`` keeps the exact dict shape the course-detail template
    expects (``module``, ``lessons``, ``total``, ``completed``, ``percent``,
    ``total_seconds``). Each lesson in it has ``.progress`` attached (a
    ``LessonProgress`` or ``None``). ``next_lesson`` is the first not-completed
    lesson in curriculum order, or ``None`` when everything is done.
    """

    modules_data: list = field(default_factory=list)
    next_lesson: object = None
    total_lessons: int = 0
    total_completed: int = 0
    total_duration: int = 0
    overall_percent: int = 0
    is_complete: bool = False
    completed_lesson_ids: set = field(default_factory=set)


def course_progress(course, user, modules=None):
    """Compute ``CourseProgress`` for ``user`` on ``course``.

    ``user`` may be anonymous (everything reads as not-started). Pass
    ``modules`` — a list of ``Module`` with their ``lessons`` prefetched — to
    reuse an already-fetched queryset and avoid a second round-trip; otherwise
    the modules are fetched here. Lessons are read from the prefetch cache in
    their default ``order`` ordering, so no per-module query is issued.
    """
    if modules is None:
        modules = list(
            course.modules.prefetch_related('lessons').order_by('order')
        )

    if user.is_authenticated:
        all_lesson_ids = [
            lesson.id for module in modules for lesson in module.lessons.all()
        ]
        progress_map = {
            p.lesson_id: p
            for p in LessonProgress.objects.filter(
                user=user, lesson_id__in=all_lesson_ids
            )
        }
    else:
        progress_map = {}

    next_lesson = None
    modules_data = []
    completed_ids = set()

    for module in modules:
        lessons = list(module.lessons.all())
        total = len(lessons)
        completed = 0
        total_seconds = sum(l.duration_seconds or 0 for l in lessons)

        for lesson in lessons:
            lesson.progress = progress_map.get(lesson.id)
            if lesson.progress and lesson.progress.is_completed:
                completed += 1
                completed_ids.add(lesson.id)
            elif next_lesson is None:
                next_lesson = lesson

        percent = int(completed / total * 100) if total else 0
        modules_data.append({
            'module': module,
            'lessons': lessons,
            'total': total,
            'completed': completed,
            'percent': percent,
            'total_seconds': total_seconds,
        })

    total_lessons = sum(m['total'] for m in modules_data)
    total_duration = sum(m['total_seconds'] for m in modules_data)
    total_completed = sum(m['completed'] for m in modules_data)
    overall_percent = (
        int(total_completed / total_lessons * 100) if total_lessons else 0
    )
    is_complete = total_lessons > 0 and total_completed == total_lessons

    return CourseProgress(
        modules_data=modules_data,
        next_lesson=next_lesson,
        total_lessons=total_lessons,
        total_completed=total_completed,
        total_duration=total_duration,
        overall_percent=overall_percent,
        is_complete=is_complete,
        completed_lesson_ids=completed_ids,
    )
