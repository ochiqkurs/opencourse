import json
import pytz

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
# from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import Lesson, LessonProgress, Note, Course, Module, VideoEvent, VideoSession
from .utils import render_markdown

User = get_user_model()
UZT = pytz.timezone('Asia/Tashkent')  # UTC+5

# ---------------------------------------------------------------------------
# / (home page — public)
# ---------------------------------------------------------------------------

class HomeView(View):
    template_name = 'home.html'

    def get(self, request):
        courses = Course.objects.annotate(
            lesson_count=Count('modules__lessons'),
            total_duration=Sum('modules__lessons__duration_seconds'),
        )
        total_seconds = (
            VideoSession.objects.aggregate(Sum('actual_watched_seconds'))
            ['actual_watched_seconds__sum'] or 0
        )
        total_hours = round(total_seconds / 3600)
        total_users = User.objects.filter(is_active=True).count()
        total_lessons = Lesson.objects.count()
        return render(request, self.template_name, {
            'courses': courses,
            'total_hours': total_hours,
            'total_users': total_users,
            'total_lessons': total_lessons,
        })


# ---------------------------------------------------------------------------
# /malaka/ (all courses — public)
# ---------------------------------------------------------------------------

class CourseListView(View):
    template_name = 'learning/course_list.html'

    def get(self, request):
        courses = Course.objects.annotate(
            lesson_count=Count('modules__lessons'),
            total_duration=Sum('modules__lessons__duration_seconds'),
        )
        return render(request, self.template_name, {
            'courses': courses,
        })


# ---------------------------------------------------------------------------
# /malaka/<course_slug>/
# ---------------------------------------------------------------------------

class CourseDetailView(View):
    template_name = 'learning/course_detail.html'

    def get(self, request, course_slug):
        course = get_object_or_404(Course, slug=course_slug)
        modules = (
            course.modules
            .prefetch_related('lessons')
            .order_by('order')
        )

        course_seconds = 0
        if request.user.is_authenticated:
            course_seconds = VideoSession.objects.filter(
                user=request.user,
                lesson__module__course=course,
            ).aggregate(Sum('actual_watched_seconds'))['actual_watched_seconds__sum'] or 0

        ctx = {
            'course': course,
            'modules': modules,
            'course_seconds': course_seconds,
            'show_sidebar': True,
            'sidebar_course': course,
            'sidebar_modules': modules,
            'current_module': None,
            'current_lesson': None,
        }
        return render(request, self.template_name, ctx)


# ---------------------------------------------------------------------------
# /malaka/<course_slug>/<module_slug>/
# ---------------------------------------------------------------------------

class ModuleDetailView(View):
    template_name = 'learning/module_detail.html'

    def get(self, request, course_slug, module_slug):
        course = get_object_or_404(Course, slug=course_slug)
        module = get_object_or_404(Module, slug=module_slug, course=course)

        lessons = list(module.lessons.order_by('order'))

        if request.user.is_authenticated:
            lesson_ids = [lesson.id for lesson in lessons]
            progress_map = {
                p.lesson_id: p
                for p in LessonProgress.objects.filter(
                    user=request.user,
                    lesson_id__in=lesson_ids,
                )
            }
            for lesson in lessons:
                lesson.progress = progress_map.get(lesson.id)
        else:
            for lesson in lessons:
                lesson.progress = None

        sidebar_modules = course.modules.prefetch_related('lessons').order_by('order')

        ctx = {
            'course': course,
            'module': module,
            'lessons': lessons,
            'show_sidebar': True,
            'sidebar_course': course,
            'sidebar_modules': sidebar_modules,
            'current_module': module,
            'current_lesson': None,
        }
        return render(request, self.template_name, ctx)


# ---------------------------------------------------------------------------
# /malaka/<course_slug>/<module_slug>/<lesson_slug>/
# ---------------------------------------------------------------------------

class LessonDetailView(View):
    template_name = 'learning/lesson_detail.html'

    def get(self, request, course_slug, module_slug, lesson_slug):
        course = get_object_or_404(Course, slug=course_slug)
        module = get_object_or_404(Module, slug=module_slug, course=course)
        lesson = get_object_or_404(Lesson, slug=lesson_slug, module=module)

        if request.user.is_authenticated:
            progress = LessonProgress.objects.filter(
                user=request.user, lesson=lesson
            ).first()
            note = Note.objects.filter(user=request.user, lesson=lesson).first()
        else:
            progress = None
            note = None

        sibling_lessons = list(module.lessons.order_by('order'))
        current_index = next(
            (i for i, l in enumerate(sibling_lessons) if l.id == lesson.id), None
        )
        prev_lesson = sibling_lessons[current_index - 1] if current_index and current_index > 0 else None
        next_lesson = sibling_lessons[current_index + 1] if current_index is not None and current_index < len(sibling_lessons) - 1 else None

        sidebar_modules = course.modules.prefetch_related('lessons').order_by('order')

        ctx = {
            'course': course,
            'module': module,
            'lesson': lesson,
            'progress': progress,
            'prev_lesson': prev_lesson,
            'next_lesson': next_lesson,
            'show_sidebar': True,
            'sidebar_course': course,
            'sidebar_modules': sidebar_modules,
            'current_module': module,
            'current_lesson': lesson,
            'lesson_description_html': mark_safe(render_markdown(lesson.description)),
            'note': note,
            'note_rendered': mark_safe(render_markdown(note.content)) if note and note.content else '',
        }
        return render(request, self.template_name, ctx)


# ---------------------------------------------------------------------------
# POST /malaka/<course_slug>/<module_slug>/<lesson_slug>/complete/
# ---------------------------------------------------------------------------

@login_required
def mark_lesson_complete(request, course_slug, module_slug, lesson_slug):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    lesson = _get_lesson(course_slug, module_slug, lesson_slug)

    progress, _ = LessonProgress.objects.get_or_create(
        user=request.user, lesson=lesson
    )
    progress.is_completed = True
    progress.save(update_fields=['is_completed'])

    _update_streak(request.user)

    return JsonResponse({
        'status': 'ok',
        'is_completed': progress.is_completed,
        'lesson_id': lesson.id,
    })

def _update_streak(user):
    from users.models import UserProfile
    today = timezone.now().astimezone(UZT).date()

    profile, _ = UserProfile.objects.get_or_create(user=user)

    if profile.last_activity_date == today:
        return

    if profile.last_activity_date is not None:
        from datetime import timedelta
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

# ---------------------------------------------------------------------------
# POST /malaka/<course_slug>/<module_slug>/<lesson_slug>/note/
# ---------------------------------------------------------------------------

@login_required
def save_note(request, course_slug, module_slug, lesson_slug):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    lesson = _get_lesson(course_slug, module_slug, lesson_slug)

    try:
        content = json.loads(request.body).get('content', '')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    Note.objects.update_or_create(
        user=request.user,
        lesson=lesson,
        defaults={'content': content},
    )
    rendered = render_markdown(content)
    return JsonResponse({'status': 'ok', 'rendered': rendered})


# ---------------------------------------------------------------------------
# Session tracking helpers
# ---------------------------------------------------------------------------

def _get_lesson(course_slug, module_slug, lesson_slug):
    course = get_object_or_404(Course, slug=course_slug)
    module = get_object_or_404(Module, slug=module_slug, course=course)
    return get_object_or_404(Lesson, slug=lesson_slug, module=module)


VALID_EVENT_TYPES = {et[0] for et in VideoEvent.EVENT_TYPES}
MAX_METADATA_SIZE = 1024  # bytes
EVENT_RATE_LIMIT_SECONDS = 1  # min interval between events per session


def _clamp_position(position, lesson):
    """Clamp position to [0, duration] if duration is known."""
    position = max(0, position)
    if lesson.duration_seconds:
        position = min(position, lesson.duration_seconds)
    return position


def _update_watched_incremental(session, event_type, position):
    """Incrementally update actual_watched_seconds without re-reading all events."""
    if event_type == 'play':
        session.last_play_position = position
    elif event_type in ('pause', 'ended', 'page_hidden', 'seek') and session.last_play_position is not None:
        diff = position - session.last_play_position
        if diff > 0:
            session.actual_watched_seconds += diff
        session.last_play_position = None


def _maybe_auto_complete(session, lesson):
    """Set LessonProgress.is_completed if 80% watched. Returns True if newly completed."""
    if not lesson.duration_seconds:
        return False
    if session.actual_watched_seconds < lesson.duration_seconds * 0.8:
        return False
    progress, _ = LessonProgress.objects.get_or_create(user=session.user, lesson=lesson)
    if not progress.is_completed:
        progress.is_completed = True
        progress.save(update_fields=['is_completed'])
        _update_streak(session.user)
        return True
    return False


def _handle_session_event(request, lesson, data):
    """Shared logic for session/event/ and session/beacon/ endpoints."""
    session = get_object_or_404(
        VideoSession, id=data.get('session_id'), user=request.user, lesson=lesson
    )

    # Validate event_type
    event_type = data.get('event_type', '')
    if event_type not in VALID_EVENT_TYPES:
        return JsonResponse({'error': 'Invalid event_type'}, status=400)

    # Validate and clamp position
    try:
        position = int(data.get('position_seconds', 0))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid position_seconds'}, status=400)
    position = _clamp_position(position, lesson)

    # Validate metadata size
    metadata = data.get('metadata') or {}
    if len(json.dumps(metadata)) > MAX_METADATA_SIZE:
        metadata = {}  # silently drop oversized metadata

    # Rate limiting: only throttle heartbeat events (high-frequency).
    # State-critical events (play, pause, seek, ended, page_hidden, speed_change)
    # must always be processed to keep the incremental watch time state machine correct.
    if event_type == 'heartbeat':
        last_event = session.events.order_by('-created_at').first()
        if last_event:
            elapsed = (timezone.now() - last_event.created_at).total_seconds()
            if elapsed < EVENT_RATE_LIMIT_SECONDS:
                return JsonResponse({'status': 'ok', 'auto_completed': False, 'throttled': True})

    VideoEvent.objects.create(
        session=session,
        event_type=event_type,
        position_seconds=position,
        metadata=metadata,
    )

    # Incremental watched time update (no full event scan)
    _update_watched_incremental(session, event_type, position)

    session.last_position_seconds = position
    session.max_reached_seconds = max(position, session.max_reached_seconds)
    save_fields = [
        'actual_watched_seconds', 'last_position_seconds',
        'max_reached_seconds', 'last_play_position',
    ]
    if event_type in ('ended', 'page_hidden'):
        session.ended_at = timezone.now()
        save_fields.append('ended_at')
    session.save(update_fields=save_fields)

    progress, created = LessonProgress.objects.get_or_create(
        user=request.user, lesson=lesson
    )
    if created or session.actual_watched_seconds > progress.watched_seconds:
        progress.watched_seconds = max(progress.watched_seconds, session.actual_watched_seconds)
        progress.save(update_fields=['watched_seconds'])

    auto_completed = _maybe_auto_complete(session, lesson)
    return JsonResponse({'status': 'ok', 'auto_completed': auto_completed})


# ---------------------------------------------------------------------------
# POST /malaka/<course_slug>/<module_slug>/<lesson_slug>/session/start/
# ---------------------------------------------------------------------------

@login_required
def session_start(request, course_slug, module_slug, lesson_slug):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    lesson = _get_lesson(course_slug, module_slug, lesson_slug)

    try:
        data = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, ValueError):
        data = {}

    duration = data.get('duration_seconds')
    if duration and not lesson.duration_seconds:
        lesson.duration_seconds = int(duration)
        lesson.save(update_fields=['duration_seconds'])

    now = timezone.now()
    resume_threshold = now - timedelta(minutes=30)

    session = VideoSession.objects.filter(
        user=request.user, lesson=lesson, ended_at__isnull=True
    ).first()

    if not session:
        session = VideoSession.objects.filter(
            user=request.user, lesson=lesson, ended_at__gte=resume_threshold
        ).order_by('-ended_at').first()
        if session:
            session.ended_at = None
            session.save(update_fields=['ended_at'])
        else:
            session = VideoSession.objects.create(user=request.user, lesson=lesson)

    return JsonResponse({'session_id': session.id, 'last_position': session.last_position_seconds})


# ---------------------------------------------------------------------------
# POST /malaka/<course_slug>/<module_slug>/<lesson_slug>/session/event/
# ---------------------------------------------------------------------------

@login_required
def session_event(request, course_slug, module_slug, lesson_slug):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    lesson = _get_lesson(course_slug, module_slug, lesson_slug)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    return _handle_session_event(request, lesson, data)


# ---------------------------------------------------------------------------
# POST /malaka/<course_slug>/<module_slug>/<lesson_slug>/session/beacon/
# ---------------------------------------------------------------------------

@csrf_exempt
def session_beacon(request, course_slug, module_slug, lesson_slug):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    lesson = _get_lesson(course_slug, module_slug, lesson_slug)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid data'}, status=400)

    return _handle_session_event(request, lesson, data)
