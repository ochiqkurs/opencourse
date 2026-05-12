import json
import pytz

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views import View

from .models import (
    Lesson, LessonProgress, LessonView, Note, Course, Module,
    Category, Enrollment, CourseReview, Certificate,
    Wishlist, LessonResource, LessonQuestion, LessonAnswer, Announcement,
)
from .forms import CourseReviewForm, LessonQuestionForm, LessonAnswerForm
from .utils import render_markdown

User = get_user_model()
UZT = pytz.timezone('Asia/Tashkent')  # UTC+5


def _today_uzt():
    return timezone.now().astimezone(UZT).date()


def _course_card_annotations(qs):
    return qs.annotate(
        lesson_count=Count('modules__lessons', distinct=True),
        total_duration=Sum('modules__lessons__duration_seconds'),
        student_count=Count('enrollments', distinct=True),
    )


def _user_wishlist_ids(user):
    if not user.is_authenticated:
        return set()
    return set(Wishlist.objects.filter(user=user).values_list('course_id', flat=True))


# ---------------------------------------------------------------------------
# / (home page — public)
# ---------------------------------------------------------------------------

class HomeView(View):
    template_name = 'home.html'

    def get(self, request):
        all_courses = list(
            _course_card_annotations(
                Course.objects.select_related('category')
            ).order_by('-is_featured', 'order')
        )

        featured = [c for c in all_courses if c.is_featured][:8]
        if not featured:
            featured = all_courses[:8]

        trending = sorted(all_courses, key=lambda c: (c.student_count or 0), reverse=True)[:8]
        newest = list(
            _course_card_annotations(
                Course.objects.select_related('category')
            ).order_by('-id')[:8]
        )
        top_rated = list(
            _course_card_annotations(
                Course.objects.filter(rating_count__gt=0)
                .select_related('category')
            ).order_by('-avg_rating', '-rating_count')[:8]
        )

        total_seconds = (
            LessonView.objects
            .aggregate(s=Sum('lesson__duration_seconds'))['s'] or 0
        )
        total_hours = round(total_seconds / 3600)
        total_users = User.objects.filter(is_active=True).count()
        total_lessons = Lesson.objects.count()
        total_courses = Course.objects.count()

        categories = list(
            Category.objects.annotate(c=Count('courses')).order_by('order', 'name')
        )

        latest_reviews = list(
            CourseReview.objects
            .select_related('user', 'course')
            .exclude(comment='')
            .order_by('-created_at')[:6]
        )

        global_announcements = list(
            Announcement.objects.filter(course__isnull=True).order_by('-is_pinned', '-created_at')[:2]
        )

        # category strips: one row per category (top 8 by enrollments)
        category_strips = []
        for cat in categories[:6]:
            cat_courses = [c for c in all_courses if c.category_id == cat.id][:6]
            if cat_courses:
                category_strips.append({'category': cat, 'courses': cat_courses})

        return render(request, self.template_name, {
            'featured': featured,
            'trending': trending,
            'newest': newest,
            'top_rated': top_rated,
            'categories': categories,
            'total_hours': total_hours,
            'total_users': total_users,
            'total_lessons': total_lessons,
            'total_courses': total_courses,
            'latest_reviews': latest_reviews,
            'global_announcements': global_announcements,
            'category_strips': category_strips,
            'wishlist_ids': _user_wishlist_ids(request.user),
        })


# ---------------------------------------------------------------------------
# /malaka/ (all courses — public)
# ---------------------------------------------------------------------------

class CourseListView(View):
    template_name = 'learning/course_list.html'

    def get(self, request):
        qs = _course_card_annotations(
            Course.objects.select_related('category')
        )

        category_slug = request.GET.get('kategoriya', '').strip()
        level = request.GET.get('daraja', '').strip()
        sort = request.GET.get('saralash', 'popular')
        q = request.GET.get('q', '').strip()

        if category_slug:
            qs = qs.filter(category__slug=category_slug)
        if level and level in dict(Course.LEVEL_CHOICES):
            qs = qs.filter(level=level)
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(subtitle__icontains=q))

        if sort == 'new':
            qs = qs.order_by('-id')
        elif sort == 'rating':
            qs = qs.order_by('-avg_rating', '-rating_count')
        else:  # popular
            qs = qs.order_by('-student_count', 'order')

        categories = list(Category.objects.order_by('order', 'name'))
        active_category = None
        if category_slug:
            active_category = next((c for c in categories if c.slug == category_slug), None)

        return render(request, self.template_name, {
            'courses': list(qs),
            'categories': categories,
            'active_category': active_category,
            'active_level': level,
            'active_sort': sort,
            'q': q,
            'level_choices': Course.LEVEL_CHOICES,
            'wishlist_ids': _user_wishlist_ids(request.user),
        })


# ---------------------------------------------------------------------------
# /malaka/kategoriya/<slug>/
# ---------------------------------------------------------------------------

class CategoryDetailView(View):
    template_name = 'learning/category_detail.html'

    def get(self, request, slug):
        category = get_object_or_404(Category, slug=slug)
        courses = _course_card_annotations(
            Course.objects.filter(category=category).select_related('category')
        ).order_by('order')
        categories = list(Category.objects.order_by('order', 'name'))
        return render(request, self.template_name, {
            'category': category,
            'courses': list(courses),
            'categories': categories,
            'wishlist_ids': _user_wishlist_ids(request.user),
        })


# ---------------------------------------------------------------------------
# /malaka/qidiruv/?q=...
# ---------------------------------------------------------------------------

class SearchView(View):
    template_name = 'learning/search_results.html'

    def get(self, request):
        q = request.GET.get('q', '').strip()
        courses = []
        lessons = []
        if q:
            courses = list(_course_card_annotations(
                Course.objects.filter(
                    Q(title__icontains=q) | Q(description__icontains=q) | Q(subtitle__icontains=q)
                ).select_related('category')
            )[:20])
            lessons = list(
                Lesson.objects.filter(
                    Q(title__icontains=q) | Q(description__icontains=q)
                ).select_related('module__course')[:20]
            )

        if request.GET.get('format') == 'json':
            return JsonResponse({
                'courses': [
                    {
                        'title': c.title,
                        'slug': c.slug,
                        'url': reverse('learning:course_detail', args=[c.slug]),
                        'category': c.category.name if c.category else '',
                        'thumb': c.get_thumbnail_url() or '',
                    } for c in courses[:6]
                ],
                'lessons': [
                    {
                        'title': l.title,
                        'course': l.module.course.title,
                        'url': reverse('learning:lesson_detail', args=[l.module.course.slug, l.module.slug, l.slug]),
                    } for l in lessons[:6]
                ],
            })

        return render(request, self.template_name, {
            'q': q,
            'courses': courses,
            'lessons': lessons,
            'wishlist_ids': _user_wishlist_ids(request.user),
        })


# ---------------------------------------------------------------------------
# /malaka/<course_slug>/
# ---------------------------------------------------------------------------

class CourseDetailView(View):
    template_name = 'learning/course_detail.html'

    def get(self, request, course_slug):
        course = get_object_or_404(
            Course.objects.select_related('category', 'instructor'),
            slug=course_slug,
        )
        modules = list(
            course.modules
            .prefetch_related('lessons')
            .order_by('order')
        )

        next_lesson = None
        modules_data = []

        if request.user.is_authenticated:
            all_lesson_ids = [
                lesson.id
                for module in modules
                for lesson in module.lessons.all()
            ]
            progress_map = {
                p.lesson_id: p
                for p in LessonProgress.objects.filter(
                    user=request.user,
                    lesson_id__in=all_lesson_ids,
                )
            }
            is_enrolled = Enrollment.objects.filter(user=request.user, course=course).exists()
            user_review = CourseReview.objects.filter(user=request.user, course=course).first()
            has_certificate = Certificate.objects.filter(user=request.user, course=course).exists()
            is_wishlisted = Wishlist.objects.filter(user=request.user, course=course).exists()
        else:
            progress_map = {}
            is_enrolled = False
            user_review = None
            has_certificate = False
            is_wishlisted = False

        for module in modules:
            lessons = list(module.lessons.order_by('order'))
            total = len(lessons)
            completed = 0
            total_seconds = sum(l.duration_seconds or 0 for l in lessons)

            for lesson in lessons:
                lesson.progress = progress_map.get(lesson.id)
                if lesson.progress and lesson.progress.is_completed:
                    completed += 1
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
        overall_percent = int(total_completed / total_lessons * 100) if total_lessons else 0
        is_complete = total_lessons > 0 and total_completed == total_lessons

        if is_complete and request.user.is_authenticated and not has_certificate:
            Certificate.objects.get_or_create(user=request.user, course=course)
            has_certificate = True

        reviews = list(
            course.reviews.select_related('user', 'user__telegram_profile')
            .order_by('-created_at')[:20]
        )

        student_count = Enrollment.objects.filter(course=course).count()

        rating_breakdown = []
        if course.rating_count:
            counts = {r['rating']: r['c'] for r in course.reviews.values('rating').annotate(c=Count('id'))}
            for star in range(5, 0, -1):
                c = counts.get(star, 0)
                pct = int((c / course.rating_count) * 100) if course.rating_count else 0
                rating_breakdown.append({'star': star, 'count': c, 'percent': pct})

        announcements = list(
            Announcement.objects.filter(
                Q(course=course) | Q(course__isnull=True)
            ).order_by('-is_pinned', '-created_at')[:3]
        )

        # preview lesson: first lesson marked is_preview OR very first lesson
        preview_lesson = (
            Lesson.objects.filter(module__course=course, is_preview=True)
            .order_by('module__order', 'order').first()
            or Lesson.objects.filter(module__course=course)
            .order_by('module__order', 'order').first()
        )

        ctx = {
            'course': course,
            'modules_data': modules_data,
            'next_lesson': next_lesson,
            'total_lessons': total_lessons,
            'total_duration': total_duration,
            'overall_percent': overall_percent,
            'is_complete': is_complete,
            'is_enrolled': is_enrolled,
            'has_certificate': has_certificate,
            'is_wishlisted': is_wishlisted,
            'reviews': reviews,
            'review_form': CourseReviewForm(instance=user_review),
            'user_review': user_review,
            'student_count': student_count,
            'rating_breakdown': rating_breakdown,
            'description_html': mark_safe(render_markdown(course.description)) if course.description else '',
            'announcements': announcements,
            'preview_lesson': preview_lesson,
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

        ctx = {
            'course': course,
            'module': module,
            'lessons': lessons,
            'module_description_html': mark_safe(render_markdown(module.description)) if module.description else '',
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
            Enrollment.objects.get_or_create(user=request.user, course=course)
            is_wishlisted = Wishlist.objects.filter(user=request.user, course=course).exists()
        else:
            progress = None
            note = None
            is_wishlisted = False

        resources = list(lesson.resources.all())
        questions = list(
            LessonQuestion.objects
            .filter(lesson=lesson)
            .select_related('user', 'user__telegram_profile')
            .prefetch_related('answers__user')
            .order_by('-created_at')[:30]
        )

        sibling_lessons = list(module.lessons.order_by('order'))
        current_index = next(
            (i for i, l in enumerate(sibling_lessons) if l.id == lesson.id), None
        )
        prev_lesson = sibling_lessons[current_index - 1] if current_index and current_index > 0 else None
        next_lesson = sibling_lessons[current_index + 1] if current_index is not None and current_index < len(sibling_lessons) - 1 else None

        if not next_lesson:
            next_module = course.modules.filter(order__gt=module.order).order_by('order').first()
            if next_module:
                nl = next_module.lessons.order_by('order').first()
                if nl:
                    next_lesson = nl
        if not prev_lesson:
            prev_module = course.modules.filter(order__lt=module.order).order_by('-order').first()
            if prev_module:
                pl = prev_module.lessons.order_by('-order').first()
                if pl:
                    prev_lesson = pl

        sidebar_modules = course.modules.prefetch_related('lessons').order_by('order')

        if request.user.is_authenticated:
            all_ids = list(Lesson.objects.filter(module__course=course).values_list('id', flat=True))
            done_ids = set(
                LessonProgress.objects
                .filter(user=request.user, lesson_id__in=all_ids, is_completed=True)
                .values_list('lesson_id', flat=True)
            )
        else:
            done_ids = set()

        total_in_course = Lesson.objects.filter(module__course=course).count()
        completed_in_course = len(done_ids)
        course_percent = int(completed_in_course / total_in_course * 100) if total_in_course else 0

        announcements = list(
            Announcement.objects.filter(
                Q(course=course) | Q(course__isnull=True)
            ).order_by('-is_pinned', '-created_at')[:3]
        )

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
            'completed_lesson_ids': done_ids,
            'lesson_description_html': mark_safe(render_markdown(lesson.description)),
            'note': note,
            'note_rendered': mark_safe(render_markdown(note.content)) if note and note.content else '',
            'resources': resources,
            'questions': questions,
            'question_form': LessonQuestionForm(),
            'answer_form': LessonAnswerForm(),
            'is_wishlisted': is_wishlisted,
            'course_percent': course_percent,
            'course_completed': completed_in_course,
            'course_total': total_in_course,
            'announcements': announcements,
        }
        return render(request, self.template_name, ctx)


# ---------------------------------------------------------------------------
# POST /malaka/<course_slug>/<module_slug>/<lesson_slug>/davom/koridi/
# ---------------------------------------------------------------------------

@login_required
def record_view(request, course_slug, module_slug, lesson_slug):
    """Record that the user pressed play on this lesson today.

    Idempotent per (user, lesson, day). Also marks the lesson complete and
    bumps the streak — playing the video counts as completing the lesson.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    lesson = _get_lesson(course_slug, module_slug, lesson_slug)
    today = _today_uzt()

    _, created = LessonView.objects.get_or_create(
        user=request.user, lesson=lesson, viewed_on=today,
    )

    progress, _ = LessonProgress.objects.get_or_create(
        user=request.user, lesson=lesson
    )
    newly_completed = False
    if not progress.is_completed:
        progress.is_completed = True
        progress.save(update_fields=['is_completed'])
        newly_completed = True
    else:
        progress.save(update_fields=['last_watched_at'])

    _update_streak(request.user)
    if newly_completed:
        _maybe_issue_certificate(request.user, lesson.module.course)

    return JsonResponse({
        'status': 'ok',
        'new_view': created,
        'is_completed': progress.is_completed,
    })


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
    _maybe_issue_certificate(request.user, lesson.module.course)

    return JsonResponse({
        'status': 'ok',
        'is_completed': progress.is_completed,
        'lesson_id': lesson.id,
    })


def _maybe_issue_certificate(user, course):
    total = Lesson.objects.filter(module__course=course).count()
    if not total:
        return
    completed = LessonProgress.objects.filter(
        user=user, lesson__module__course=course, is_completed=True,
    ).count()
    if completed >= total:
        Certificate.objects.get_or_create(user=user, course=course)


def _update_streak(user):
    from users.models import UserProfile
    today = _today_uzt()

    profile, _ = UserProfile.objects.get_or_create(user=user)

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
# POST /malaka/<course_slug>/yozilish/
# ---------------------------------------------------------------------------

@login_required
def enroll_course(request, course_slug):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    course = get_object_or_404(Course, slug=course_slug)
    Enrollment.objects.get_or_create(user=request.user, course=course)
    messages.success(request, "Kursga yozildingiz!")
    return redirect('learning:course_detail', course_slug=course.slug)


# ---------------------------------------------------------------------------
# POST /malaka/<course_slug>/sharh/
# ---------------------------------------------------------------------------

@login_required
def submit_review(request, course_slug):
    if request.method != 'POST':
        return redirect('learning:course_detail', course_slug=course_slug)
    course = get_object_or_404(Course, slug=course_slug)
    instance = CourseReview.objects.filter(user=request.user, course=course).first()
    form = CourseReviewForm(request.POST, instance=instance)
    if form.is_valid():
        review = form.save(commit=False)
        review.user = request.user
        review.course = course
        review.save()
        course.update_rating()
        messages.success(request, "Sharhingiz saqlandi. Rahmat!")
    else:
        messages.error(request, "Iltimos baho va sharhni to'g'ri kiriting.")
    return redirect('learning:course_detail', course_slug=course.slug)


# ---------------------------------------------------------------------------
# GET /malaka/<course_slug>/sertifikat/
# ---------------------------------------------------------------------------

@login_required
def certificate_view(request, course_slug):
    course = get_object_or_404(Course, slug=course_slug)
    _maybe_issue_certificate(request.user, course)
    cert = Certificate.objects.filter(user=request.user, course=course).first()
    if not cert:
        messages.warning(request, "Sertifikat olish uchun kursni to'liq tugating.")
        return redirect('learning:course_detail', course_slug=course.slug)
    full_name = (request.user.first_name + ' ' + request.user.last_name).strip()
    if not full_name:
        full_name = request.user.username
    return render(request, 'learning/certificate.html', {
        'course': course,
        'certificate': cert,
        'full_name': full_name,
    })


def _get_lesson(course_slug, module_slug, lesson_slug):
    course = get_object_or_404(Course, slug=course_slug)
    module = get_object_or_404(Module, slug=module_slug, course=course)
    return get_object_or_404(Lesson, slug=lesson_slug, module=module)


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------

@login_required
def toggle_wishlist(request, course_slug):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    course = get_object_or_404(Course, slug=course_slug)
    qs = Wishlist.objects.filter(user=request.user, course=course)
    if qs.exists():
        qs.delete()
        return JsonResponse({'status': 'ok', 'wishlisted': False})
    Wishlist.objects.create(user=request.user, course=course)
    return JsonResponse({'status': 'ok', 'wishlisted': True})


@login_required
def wishlist_view(request):
    items = (
        Wishlist.objects
        .filter(user=request.user)
        .select_related('course', 'course__category')
        .order_by('-created_at')
    )
    course_ids = [w.course_id for w in items]
    courses = list(
        _course_card_annotations(
            Course.objects.filter(id__in=course_ids).select_related('category')
        )
    )
    course_by_id = {c.id: c for c in courses}
    ordered_courses = [course_by_id[w.course_id] for w in items if w.course_id in course_by_id]
    return render(request, 'learning/wishlist.html', {
        'courses': ordered_courses,
        'wishlist_ids': set(course_ids),
    })


# ---------------------------------------------------------------------------
# My Learning (enrolled courses + progress)
# ---------------------------------------------------------------------------

@login_required
def my_learning(request):
    enrollments = (
        Enrollment.objects.filter(user=request.user)
        .select_related('course', 'course__category')
        .order_by('-enrolled_at')
    )

    course_ids = [e.course_id for e in enrollments]
    courses = list(
        _course_card_annotations(
            Course.objects.filter(id__in=course_ids).select_related('category')
        )
    )
    course_by_id = {c.id: c for c in courses}

    progress_qs = LessonProgress.objects.filter(
        user=request.user, lesson__module__course_id__in=course_ids,
    ).values('lesson__module__course_id', 'is_completed').annotate(c=Count('id'))

    # per-course completed lesson counts
    completed_map = {}
    for row in progress_qs:
        cid = row['lesson__module__course_id']
        if row['is_completed']:
            completed_map[cid] = completed_map.get(cid, 0) + row['c']

    cards = []
    for e in enrollments:
        c = course_by_id.get(e.course_id)
        if not c:
            continue
        total = c.lesson_count or 0
        done = completed_map.get(c.id, 0)
        percent = int(done / total * 100) if total else 0
        cards.append({
            'course': c,
            'percent': percent,
            'done': done,
            'total': total,
            'enrolled_at': e.enrolled_at,
        })

    filter_tab = request.GET.get('holat', 'all')
    if filter_tab == 'in_progress':
        cards = [x for x in cards if 0 < x['percent'] < 100]
    elif filter_tab == 'completed':
        cards = [x for x in cards if x['percent'] >= 100]
    elif filter_tab == 'not_started':
        cards = [x for x in cards if x['percent'] == 0]

    return render(request, 'learning/my_learning.html', {
        'cards': cards,
        'filter_tab': filter_tab,
        'total_enrollments': enrollments.count(),
        'wishlist_ids': _user_wishlist_ids(request.user),
    })


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def leaderboard_view(request):
    from users.models import UserProfile
    from datetime import timedelta

    period = request.GET.get('davr', 'all')
    today = _today_uzt()

    base = LessonView.objects.all()
    if period == 'week':
        since = today - timedelta(days=7)
        base = base.filter(viewed_on__gte=since)
    elif period == 'month':
        since = today - timedelta(days=30)
        base = base.filter(viewed_on__gte=since)

    rows = (
        base.values('user_id')
        .annotate(views=Count('id'))
        .order_by('-views')[:50]
    )
    user_ids = [r['user_id'] for r in rows]
    users = {u.id: u for u in User.objects.filter(id__in=user_ids).select_related('telegram_profile')}
    profiles = {p.user_id: p for p in UserProfile.objects.filter(user_id__in=user_ids)}
    completed_counts = dict(
        LessonProgress.objects.filter(user_id__in=user_ids, is_completed=True)
        .values_list('user_id').annotate(c=Count('id'))
    )

    leaders = []
    for i, r in enumerate(rows, start=1):
        u = users.get(r['user_id'])
        if not u:
            continue
        prof = profiles.get(u.id)
        leaders.append({
            'rank': i,
            'user': u,
            'views': r['views'],
            'completed': completed_counts.get(u.id, 0),
            'streak': prof.current_streak if prof else 0,
            'longest_streak': prof.longest_streak if prof else 0,
        })

    return render(request, 'learning/leaderboard.html', {
        'leaders': leaders,
        'period': period,
    })


# ---------------------------------------------------------------------------
# Q&A on lessons
# ---------------------------------------------------------------------------

@login_required
def ask_question(request, course_slug, module_slug, lesson_slug):
    if request.method != 'POST':
        return redirect('learning:lesson_detail', course_slug, module_slug, lesson_slug)
    lesson = _get_lesson(course_slug, module_slug, lesson_slug)
    form = LessonQuestionForm(request.POST)
    if form.is_valid():
        q = form.save(commit=False)
        q.user = request.user
        q.lesson = lesson
        q.save()
        messages.success(request, "Savolingiz yuborildi.")
    else:
        messages.error(request, "Savol matni bo'sh bo'lmasligi kerak.")
    return redirect(
        reverse('learning:lesson_detail', args=[course_slug, module_slug, lesson_slug]) + '#qa'
    )


@login_required
def post_answer(request, course_slug, module_slug, lesson_slug, question_id):
    if request.method != 'POST':
        return redirect('learning:lesson_detail', course_slug, module_slug, lesson_slug)
    lesson = _get_lesson(course_slug, module_slug, lesson_slug)
    question = get_object_or_404(LessonQuestion, id=question_id, lesson=lesson)
    form = LessonAnswerForm(request.POST)
    if form.is_valid():
        a = form.save(commit=False)
        a.user = request.user
        a.question = question
        a.is_instructor = (request.user.is_staff or request.user.is_superuser)
        a.save()
    return redirect(
        reverse('learning:lesson_detail', args=[course_slug, module_slug, lesson_slug]) + f'#q{question.id}'
    )
