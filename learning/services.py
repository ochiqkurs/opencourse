"""Write-side domain operations ("services").

Where ``selectors.py`` reads, this module *mutates*: recording a lesson view,
completing a lesson, bumping a streak, issuing a certificate. Each function
takes domain objects (never a request) so it can be unit-tested directly, and
each owns the full side-effect bundle for one user action, keeping the views
down to HTTP parsing + a single call.
"""

from django.db import transaction

from users.models import UserProfile

from .models import Certificate, Enrollment, Lesson, LessonProgress, LessonView
from .utils import today_uzt


def update_streak(user):
    """Bump ``user``'s activity streak for today (idempotent per day).

    First activity of the day extends the streak when yesterday was active,
    otherwise resets it to 1; a second call the same day is a no-op. Wrapped in
    a ``select_for_update`` transaction so concurrent activity can't double-count.
    """
    today = today_uzt()

    with transaction.atomic():
        profile, _ = UserProfile.objects.select_for_update().get_or_create(user=user)

        if profile.last_activity_date == today:
            return

        if profile.last_activity_date is not None:
            delta = today - profile.last_activity_date
            if delta.days == 1:
                profile.current_streak += 1
            else:
                profile.current_streak = 1
        else:
            profile.current_streak = 1

        profile.last_activity_date = today
        profile.longest_streak = max(profile.longest_streak, profile.current_streak)
        profile.save(update_fields=['current_streak', 'longest_streak', 'last_activity_date'])


def issue_certificate_if_complete(user, course):
    """Issue ``course``'s certificate to ``user`` once every lesson is completed.

    No-op for an empty course or one not yet fully complete. Idempotent — the
    certificate is created via ``get_or_create``.
    """
    total = Lesson.objects.filter(module__course=course).count()
    if not total:
        return
    completed = LessonProgress.objects.filter(
        user=user, lesson__module__course=course, is_completed=True,
    ).count()
    if completed >= total:
        Certificate.objects.get_or_create(user=user, course=course)


def record_lesson_view(user, lesson):
    """Record that ``user`` opened/played ``lesson`` today.

    Enrolls the user, logs a daily ``LessonView`` (idempotent per day), touches
    ``last_watched_at``, and bumps the streak — watching counts as activity. It
    does **not** complete the lesson (that's :func:`complete_lesson`). Returns
    ``(progress, view_created)``.
    """
    Enrollment.objects.get_or_create(user=user, course=lesson.module.course)

    _, view_created = LessonView.objects.get_or_create(
        user=user, lesson=lesson, viewed_on=today_uzt(),
    )

    # Touch progress so last_watched_at reflects this view, but leave
    # is_completed untouched — viewing is not completing.
    progress, _ = LessonProgress.objects.get_or_create(user=user, lesson=lesson)
    progress.save(update_fields=['last_watched_at'])

    update_streak(user)
    return progress, view_created


def complete_lesson(user, lesson):
    """Mark ``lesson`` complete for ``user``.

    Enrolls (a user completing via the manual button may have no enrollment
    yet), sets ``is_completed``, bumps the streak, and issues the course
    certificate if this was the last lesson. Returns the ``LessonProgress``.
    """
    Enrollment.objects.get_or_create(user=user, course=lesson.module.course)

    progress, _ = LessonProgress.objects.get_or_create(user=user, lesson=lesson)
    progress.is_completed = True
    progress.save(update_fields=['is_completed'])

    update_streak(user)
    issue_certificate_if_complete(user, lesson.module.course)
    return progress
