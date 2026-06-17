import json
import pytz

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum, Q, OuterRef, Subquery, IntegerField
from django.db.models.functions import Coalesce
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views import View

from .models import (
    Lesson, LessonProgress, LessonView, Note, Course, Module,
    Category, Enrollment, CourseReview, Certificate,
    Wishlist, LessonResource, LessonQuestion, LessonAnswer, Announcement,
    Quiz, QuizAttempt, QuizAnswer, QuizQuestion, QuizChoice,
    LearningPath, LearningPathCourse, LearningPathEnrollment, LearningPathCertificate,
    VideoBookmark,
)
from .forms import CourseReviewForm, LessonQuestionForm, LessonAnswerForm
from .utils import render_markdown

User = get_user_model()
UZT = pytz.timezone('Asia/Tashkent')  # UTC+5


def _today_uzt():
    return timezone.now().astimezone(UZT).date()


def _course_card_annotations(qs):
    # Aggregate lessons via correlated subqueries so that the `enrollments` JOIN
    # cannot multiply the per-lesson rows. Doing all three in one multi-join
    # query inflated `total_duration` by the number of enrollments (every lesson
    # duration was summed once per enrolled student).
    course_lessons = Lesson.objects.filter(module__course=OuterRef('pk')).order_by()
    lesson_count_sq = course_lessons.values('module__course').annotate(n=Count('id')).values('n')
    duration_sq = course_lessons.values('module__course').annotate(s=Sum('duration_seconds')).values('s')
    return qs.annotate(
        lesson_count=Coalesce(Subquery(lesson_count_sq, output_field=IntegerField()), 0),
        total_duration=Coalesce(Subquery(duration_sq, output_field=IntegerField()), 0),
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
        user = request.user
        published = Course.objects.filter(status='published')
        all_courses = list(
            _course_card_annotations(
                published.select_related('category')
            ).order_by('-is_featured', 'order')
        )

        featured = [c for c in all_courses if c.is_featured][:8]
        if not featured:
            featured = all_courses[:8]

        trending = sorted(all_courses, key=lambda c: (c.student_count or 0), reverse=True)[:8]
        newest = sorted(all_courses, key=lambda c: c.id, reverse=True)[:8]
        top_rated = sorted(
            [c for c in all_courses if c.rating_count > 0],
            key=lambda c: (float(c.avg_rating), c.rating_count),
            reverse=True,
        )[:8]

        total_seconds = (
            LessonView.objects
            .aggregate(s=Sum('lesson__duration_seconds'))['s'] or 0
        )
        total_hours = round(total_seconds / 3600)
        total_users = User.objects.filter(is_active=True).count()
        total_lessons = Lesson.objects.count()
        total_courses = published.count()

        categories = list(
            Category.objects.annotate(
                c=Count('courses', filter=Q(courses__status='published'))
            ).order_by('order', 'name')
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

        # Featured learning paths
        learning_paths = list(
            LearningPath.objects.filter(is_featured=True)
            .annotate(course_count=Count('path_courses'))
            [:4]
        )

        # ── Personalized (authenticated users) ──
        continue_learning = []
        recommended = []
        recent_activity = []

        if user.is_authenticated:
            enrolled_ids = set(
                Enrollment.objects.filter(user=user)
                .values_list('course_id', flat=True)
            )
            enrolled_courses = [c for c in all_courses if c.id in enrolled_ids]

            # Completed-lesson counts for every enrolled course in one query
            # (was a per-course COUNT inside the loop — an N+1).
            completed_map = dict(
                LessonProgress.objects
                .filter(user=user, is_completed=True, lesson__module__course_id__in=enrolled_ids)
                .values_list('lesson__module__course_id')
                .annotate(c=Count('id'))
            )

            for course in enrolled_courses:
                total = course.lesson_count or 0
                done = completed_map.get(course.id, 0)
                percent = int(done / total * 100) if total else 0
                if 0 < percent < 100:
                    continue_learning.append({
                        'course': course,
                        'percent': percent,
                        'done': done,
                        'total': total,
                    })
                if len(continue_learning) >= 3:
                    break

            # Recent activity
            recent_raw = list(
                LessonView.objects.filter(user=user)
                .select_related('lesson__module__course')
                .order_by('-first_seen_at')[:5]
            )
            recent_activity = [
                {
                    'lesson': rv.lesson,
                    'course': rv.lesson.module.course,
                    'viewed_on': rv.viewed_on,
                }
                for rv in recent_raw
            ]

            # Category-based recommendations
            enrolled_cat_ids = set(
                Course.objects.filter(id__in=enrolled_ids)
                .values_list('category_id', flat=True)
            )
            if enrolled_cat_ids:
                recommended = list(
                    _course_card_annotations(
                        published.filter(category_id__in=enrolled_cat_ids)
                        .exclude(id__in=enrolled_ids)
                        .select_related('category')
                    ).order_by('-avg_rating', '-rating_count')[:6]
                )

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
            'learning_paths': learning_paths,
            'continue_learning': continue_learning,
            'recent_activity': recent_activity,
            'recommended': recommended,
            'wishlist_ids': _user_wishlist_ids(request.user),
        })


# ---------------------------------------------------------------------------
# /malaka/ (all courses — public)
# ---------------------------------------------------------------------------

class CourseListView(View):
    template_name = 'learning/course_list.html'

    def get(self, request):
        qs = _course_card_annotations(
            Course.objects.filter(status='published').select_related('category')
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

        # Pagination — 24 per page
        paginator = Paginator(qs, 24)
        page = request.GET.get('sahifa', 1)
        try:
            page_obj = paginator.page(page)
        except (PageNotAnInteger, EmptyPage):
            page_obj = paginator.page(1)

        return render(request, self.template_name, {
            'courses': page_obj,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
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
            Course.objects.filter(category=category, status='published').select_related('category')
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
                    Q(title__icontains=q) | Q(description__icontains=q) | Q(subtitle__icontains=q),
                    status='published',
                ).select_related('category')
            )[:20])
            lessons = list(
                Lesson.objects.filter(
                    Q(title__icontains=q) | Q(description__icontains=q),
                    module__course__status='published',
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
            'result_count': len(courses) + len(lessons),
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
        if course.status != 'published' and not (request.user.is_staff or request.user.is_superuser):
            raise Http404
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

        # Certificates are issued by the completion endpoints (mark_complete /
        # record_view / quiz) and by the explicit /sertifikat/ view — not as a
        # side effect of viewing this page (a GET must stay side-effect free).

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
        if course.status != 'published' and not (request.user.is_staff or request.user.is_superuser):
            raise Http404
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
        if course.status != 'published' and not (request.user.is_staff or request.user.is_superuser):
            raise Http404
        module = get_object_or_404(Module, slug=module_slug, course=course)
        lesson = get_object_or_404(Lesson, slug=lesson_slug, module=module)

        if request.user.is_authenticated:
            progress = LessonProgress.objects.filter(
                user=request.user, lesson=lesson
            ).first()
            note = Note.objects.filter(user=request.user, lesson=lesson).first()
            # Enrollment now happens on first play (see record_view), not on a GET.
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

        # Article content
        lesson_content_html = ''
        if lesson.lesson_type == 'article' and lesson.content:
            lesson_content_html = mark_safe(render_markdown(lesson.content))

        # Bookmarks
        bookmarks = []
        if request.user.is_authenticated and lesson.lesson_type == 'video':
            bookmarks = list(
                VideoBookmark.objects.filter(user=request.user, lesson=lesson)
                .order_by('timestamp_seconds')
            )

        # Quizzes — only standalone quiz-type lessons surface a quiz now.
        # Taken inline: an in-progress attempt renders its questions in place of
        # the hero/start screen (see `active_*` below).
        quizzes_with_meta = []
        active_quiz = active_attempt = active_questions = None
        active_answered_ids_json = '[]'
        if lesson.lesson_type == 'quiz' and request.user.is_authenticated:
            for quiz in lesson.quizzes.all():
                questions_count = quiz.questions.count()
                user_attempts = list(
                    quiz.attempts.filter(user=request.user).order_by('-started_at')
                )
                past_attempts = user_attempts[:10]
                best_attempt = None
                if past_attempts:
                    best_attempt = max(past_attempts, key=lambda a: a.percentage())
                attempts_remaining = -1
                if quiz.max_attempts > 0:
                    attempts_remaining = max(quiz.max_attempts - len(user_attempts), 0)
                quizzes_with_meta.append({
                    'quiz': quiz,
                    'questions_count': questions_count,
                    'past_attempts': past_attempts,
                    'best_attempt': best_attempt,
                    'attempts_remaining': attempts_remaining,
                })
                if active_attempt is None:
                    in_progress = next((a for a in user_attempts if a.completed_at is None), None)
                    if in_progress:
                        active_quiz = quiz
                        active_attempt = in_progress
                        active_questions = list(
                            quiz.questions.prefetch_related('choices').order_by('order')
                        )
                        active_answered_ids_json = json.dumps(
                            list(in_progress.answers.values_list('question_id', flat=True))
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
            'lesson_content_html': lesson_content_html,
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
            'bookmarks': bookmarks,
            'quizzes_with_meta': quizzes_with_meta,
            'active_quiz': active_quiz,
            'active_attempt': active_attempt,
            'active_questions': active_questions,
            'active_answered_ids_json': active_answered_ids_json,
        }
        return render(request, self.template_name, ctx)


# ---------------------------------------------------------------------------
# POST /malaka/<course_slug>/<module_slug>/<lesson_slug>/davom/korildi/
# ---------------------------------------------------------------------------

@login_required
def record_view(request, course_slug, module_slug, lesson_slug):
    """Record that the user pressed play on this lesson today.

    Idempotent per (user, lesson, day). Also marks the lesson complete and
    bumps the streak — playing the video counts as completing the lesson.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)
    today = _today_uzt()

    # Enroll on first play (the previous implicit enrollment happened on a GET of
    # the lesson page, which inflated enrollments for anyone who merely opened it).
    Enrollment.objects.get_or_create(user=request.user, course=lesson.module.course)

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

    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)

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


# ---------------------------------------------------------------------------
# POST /malaka/<course_slug>/<module_slug>/<lesson_slug>/note/
# ---------------------------------------------------------------------------

@login_required
def save_note(request, course_slug, module_slug, lesson_slug):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)

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


def _get_lesson(course_slug, module_slug, lesson_slug, user=None):
    """Resolve a lesson, 404ing on draft/archived courses for non-staff.

    Mutating endpoints (complete, note, bookmark, quiz, Q&A) call this so that an
    authenticated user cannot record progress / certificates against unpublished
    content by POSTing directly to its URLs.
    """
    course = get_object_or_404(Course, slug=course_slug)
    if course.status != 'published' and not (user and (user.is_staff or user.is_superuser)):
        raise Http404
    module = get_object_or_404(Module, slug=module_slug, course=course)
    return get_object_or_404(Lesson, slug=lesson_slug, module=module)


def _next_lesson(course, module, lesson):
    """First lesson after `lesson` within its module, else first lesson of the next module."""
    siblings = list(module.lessons.order_by('order'))
    idx = next((i for i, l in enumerate(siblings) if l.id == lesson.id), None)
    if idx is not None and idx < len(siblings) - 1:
        return siblings[idx + 1]
    next_module = course.modules.filter(order__gt=module.order).order_by('order').first()
    if next_module:
        return next_module.lessons.order_by('order').first()
    return None


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------

@login_required
def toggle_wishlist(request, course_slug):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    course = get_object_or_404(Course, slug=course_slug)
    try:
        Wishlist.objects.get(user=request.user, course=course).delete()
        return JsonResponse({'status': 'ok', 'wishlisted': False})
    except Wishlist.DoesNotExist:
        pass
    try:
        Wishlist.objects.create(user=request.user, course=course)
    except IntegrityError:
        return JsonResponse({'status': 'ok', 'wishlisted': True})
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
    rank = 0
    for r in rows:
        u = users.get(r['user_id'])
        if not u:
            continue
        rank += 1
        prof = profiles.get(u.id)
        leaders.append({
            'rank': rank,
            'user': u,
            'views': r['views'],
            'completed': completed_counts.get(u.id, 0),
            'streak': prof.live_streak if prof else 0,
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
    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)
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
    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)
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


# ---------------------------------------------------------------------------
# Video Bookmarks
# ---------------------------------------------------------------------------

@login_required
def save_bookmark(request, course_slug, module_slug, lesson_slug):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    try:
        timestamp = int(data.get('timestamp', 0))
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid timestamp'}, status=400)
    note_text = data.get('note', '').strip()
    bookmark = VideoBookmark.objects.create(
        user=request.user,
        lesson=lesson,
        timestamp_seconds=timestamp,
        note=note_text,
    )
    return JsonResponse({
        'status': 'ok',
        'id': bookmark.id,
        'timestamp': bookmark.formatted_timestamp(),
    })


@login_required
def delete_bookmark(request, course_slug, module_slug, lesson_slug, bookmark_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)
    bookmark = get_object_or_404(VideoBookmark, id=bookmark_id, user=request.user, lesson=lesson)
    bookmark.delete()
    return JsonResponse({'status': 'ok'})


# ---------------------------------------------------------------------------
# Quiz System
# ---------------------------------------------------------------------------

def quiz_detail(request, course_slug, module_slug, lesson_slug, quiz_id):
    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)
    quiz = get_object_or_404(Quiz, id=quiz_id, lesson=lesson)
    questions_count = quiz.questions.count()
    past_attempts = []
    best_attempt = None
    attempts_remaining = -1
    if request.user.is_authenticated:
        user_attempts = QuizAttempt.objects.filter(user=request.user, quiz=quiz).order_by('-started_at')
        total_attempts = user_attempts.count()
        past_attempts = list(user_attempts[:10])
        if past_attempts:
            best_attempt = max(past_attempts, key=lambda a: a.percentage())
        if quiz.max_attempts > 0:
            # Clamp on the true attempt count, not the sliced (max 10) preview list,
            # so the displayed remaining count stays correct and never goes negative.
            attempts_remaining = max(quiz.max_attempts - total_attempts, 0)
    return render(request, 'learning/quiz_detail.html', {
        'course': lesson.module.course,
        'module': lesson.module,
        'lesson': lesson,
        'quiz': quiz,
        'questions_count': questions_count,
        'past_attempts': past_attempts,
        'best_attempt': best_attempt,
        'attempts_remaining': attempts_remaining,
    })


@login_required
def start_quiz(request, course_slug, module_slug, lesson_slug, quiz_id):
    if request.method != 'POST':
        return redirect('learning:quiz_detail', course_slug, module_slug, lesson_slug, quiz_id)
    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)
    quiz = get_object_or_404(Quiz, id=quiz_id, lesson=lesson)
    # Reuse an existing in-progress attempt instead of spawning a new one on every
    # POST (double-clicking "Boshlash" used to leave orphaned attempts behind).
    in_progress = QuizAttempt.objects.filter(
        user=request.user, quiz=quiz, completed_at__isnull=True
    ).first()
    if in_progress is None:
        past_count = QuizAttempt.objects.filter(user=request.user, quiz=quiz).count()
        if quiz.max_attempts > 0 and past_count >= quiz.max_attempts:
            messages.error(request, "Ushbu test uchun maksimal urinishlar soniga yetdingiz.")
            return redirect('learning:quiz_detail', course_slug, module_slug, lesson_slug, quiz_id)
        QuizAttempt.objects.create(
            user=request.user,
            quiz=quiz,
            max_score=quiz.questions.count(),
        )
    # The quiz is taken inline on the lesson page; the lesson view detects the
    # in-progress attempt and renders the questions where the video would be.
    return redirect('learning:lesson_detail', course_slug, module_slug, lesson_slug)


def _finalize_quiz_attempt(attempt, user, lesson):
    """Score a fully-answered attempt, set pass/fail, and run completion side effects."""
    quiz = attempt.quiz
    attempt.score = attempt.answers.filter(is_correct=True).count()
    attempt.max_score = quiz.questions.count()
    attempt.completed_at = timezone.now()
    attempt.passed = (attempt.percentage() >= quiz.pass_percent)
    attempt.save(update_fields=['score', 'max_score', 'completed_at', 'passed'])
    if attempt.passed:
        LessonProgress.objects.update_or_create(
            user=user, lesson=lesson, defaults={'is_completed': True},
        )
        _update_streak(user)
        _maybe_issue_certificate(user, lesson.module.course)


@login_required
@transaction.atomic
def check_quiz_answer(request, course_slug, module_slug, lesson_slug, quiz_id, attempt_id):
    """Record and grade a single question, returning correctness + explanation.

    Finalizes the attempt automatically once every question has an answer.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)
    quiz = get_object_or_404(Quiz, id=quiz_id, lesson=lesson)
    attempt = get_object_or_404(QuizAttempt, id=attempt_id, user=request.user, quiz=quiz)
    if attempt.completed_at:
        return JsonResponse({'error': 'Attempt already completed'}, status=400)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    try:
        question = quiz.questions.get(id=int(data.get('question_id')))
    except (QuizQuestion.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'error': 'Invalid question'}, status=400)

    selected_choice = None
    is_correct = False
    choice_id = data.get('choice_id')
    if choice_id is not None:
        try:
            selected_choice = question.choices.get(id=int(choice_id))
            is_correct = selected_choice.is_correct
        except (QuizChoice.DoesNotExist, ValueError, TypeError):
            return JsonResponse({'error': 'Invalid choice'}, status=400)

    QuizAnswer.objects.update_or_create(
        attempt=attempt,
        question=question,
        defaults={'selected_choice': selected_choice, 'is_correct': is_correct},
    )

    correct_choice = question.choices.filter(is_correct=True).first()
    total = quiz.questions.count()
    answered = attempt.answers.count()
    finished = answered >= total
    result = None
    if finished:
        _finalize_quiz_attempt(attempt, request.user, lesson)
        result = {
            'score': float(attempt.score),
            'max_score': attempt.max_score,
            'percentage': attempt.percentage(),
            'passed': attempt.passed,
        }

    return JsonResponse({
        'is_correct': is_correct,
        'correct_choice_id': correct_choice.id if correct_choice else None,
        'explanation': question.explanation,
        'answered': answered,
        'total': total,
        'finished': finished,
        'result': result,
        'redirect_url': reverse('learning:quiz_result', args=[course_slug, module_slug, lesson_slug, quiz_id, attempt_id]),
    })


@login_required
@transaction.atomic
def submit_quiz_answer(request, course_slug, module_slug, lesson_slug, quiz_id, attempt_id):
    """Grade a whole quiz from one JSON payload (legacy all-at-once submission)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)
    quiz = get_object_or_404(Quiz, id=quiz_id, lesson=lesson)
    attempt = get_object_or_404(QuizAttempt, id=attempt_id, user=request.user, quiz=quiz)
    if attempt.completed_at:
        return JsonResponse({'error': 'Attempt already completed'}, status=400)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    answers = data.get('answers', {})
    attempt.answers.all().delete()
    for q_data in quiz.questions.prefetch_related('choices').all():
        selected_id = answers.get(str(q_data.id))
        selected_choice = None
        is_correct = False
        if selected_id:
            try:
                selected_choice = q_data.choices.get(id=int(selected_id))
                is_correct = selected_choice.is_correct
            except (QuizChoice.DoesNotExist, ValueError):
                pass
        QuizAnswer.objects.create(
            attempt=attempt,
            question=q_data,
            selected_choice=selected_choice,
            is_correct=is_correct,
        )
    _finalize_quiz_attempt(attempt, request.user, lesson)

    return JsonResponse({
        'status': 'ok',
        'score': float(attempt.score),
        'max_score': attempt.max_score,
        'percentage': attempt.percentage(),
        'passed': attempt.passed,
        'redirect_url': reverse('learning:quiz_result', args=[course_slug, module_slug, lesson_slug, quiz_id, attempt_id]),
    })


@login_required
def quiz_result(request, course_slug, module_slug, lesson_slug, quiz_id, attempt_id):
    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)
    quiz = get_object_or_404(Quiz, id=quiz_id, lesson=lesson)
    attempt = get_object_or_404(QuizAttempt, id=attempt_id, user=request.user, quiz=quiz)
    answers_detail = list(
        attempt.answers.select_related('question', 'selected_choice')
    )
    course = lesson.module.course
    return render(request, 'learning/quiz_result.html', {
        'course': course,
        'module': lesson.module,
        'lesson': lesson,
        'quiz': quiz,
        'attempt': attempt,
        'answers_detail': answers_detail,
        'next_lesson': _next_lesson(course, lesson.module, lesson),
    })


# ---------------------------------------------------------------------------
# Learning Paths
# ---------------------------------------------------------------------------

class LearningPathListView(View):
    template_name = 'learning/learning_path_list.html'

    def get(self, request):
        paths = list(
            LearningPath.objects.annotate(
                course_count=Count('path_courses', distinct=True),
                student_count=Count('enrollments', distinct=True),
            ).order_by('order', 'title')
        )
        enrolled_ids = set()
        if request.user.is_authenticated:
            enrolled_ids = set(
                LearningPathEnrollment.objects.filter(user=request.user)
                .values_list('path_id', flat=True)
            )
        return render(request, self.template_name, {
            'paths': paths,
            'enrolled_ids': enrolled_ids,
        })


class LearningPathDetailView(View):
    template_name = 'learning/learning_path_detail.html'

    def get(self, request, path_slug):
        path_obj = get_object_or_404(LearningPath, slug=path_slug)
        courses_data = []
        total_courses = 0
        completed_courses = 0
        is_enrolled = False
        has_certificate = False

        if request.user.is_authenticated:
            is_enrolled = LearningPathEnrollment.objects.filter(
                user=request.user, path=path_obj
            ).exists()
            has_certificate = LearningPathCertificate.objects.filter(
                user=request.user, path=path_obj
            ).exists()

        path_courses = list(path_obj.path_courses.select_related('course').order_by('order'))
        course_ids = [pc.course_id for pc in path_courses]

        lesson_counts = dict(
            Lesson.objects.filter(module__course_id__in=course_ids)
            .values_list('module__course_id')
            .annotate(c=Count('id'))
        )
        done_counts = {}
        if request.user.is_authenticated:
            done_counts = dict(
                LessonProgress.objects.filter(
                    user=request.user,
                    lesson__module__course_id__in=course_ids,
                    is_completed=True,
                ).values_list('lesson__module__course_id').annotate(c=Count('id'))
            )

        for pc in path_courses:
            course = pc.course
            total_courses += 1
            total_lessons = lesson_counts.get(course.id, 0)
            done_lessons = done_counts.get(course.id, 0)
            is_course_complete = total_lessons > 0 and done_lessons >= total_lessons
            if is_course_complete:
                completed_courses += 1
            courses_data.append({
                'course': course,
                'order': pc.order,
                'total_lessons': total_lessons,
                'done_lessons': done_lessons,
                'percent': int(done_lessons / total_lessons * 100) if total_lessons else 0,
                'is_complete': is_course_complete,
            })

        path_complete = total_courses > 0 and completed_courses >= total_courses
        if path_complete and request.user.is_authenticated and not has_certificate:
            LearningPathCertificate.objects.get_or_create(user=request.user, path=path_obj)
            has_certificate = True

        return render(request, self.template_name, {
            'path_obj': path_obj,
            'courses_data': courses_data,
            'is_enrolled': is_enrolled,
            'has_certificate': has_certificate,
            'total_courses': total_courses,
            'completed_courses': completed_courses,
            'path_complete': path_complete,
            'overall_percent': int(completed_courses / total_courses * 100) if total_courses else 0,
        })


@login_required
def enroll_learning_path(request, path_slug):
    if request.method != 'POST':
        return redirect('learning:learning_path_detail', path_slug=path_slug)
    path_obj = get_object_or_404(LearningPath, slug=path_slug)
    LearningPathEnrollment.objects.get_or_create(user=request.user, path=path_obj)
    messages.success(request, "Yo'nalishga yozildingiz!")
    return redirect('learning:learning_path_detail', path_slug=path_slug)


@login_required
def learning_path_certificate(request, path_slug):
    path_obj = get_object_or_404(LearningPath, slug=path_slug)
    cert = LearningPathCertificate.objects.filter(user=request.user, path=path_obj).first()
    if not cert:
        messages.warning(request, "Sertifikat olish uchun yo'nalishdagi barcha kurslarni tugating.")
        return redirect('learning:learning_path_detail', path_slug=path_slug)
    full_name = (request.user.first_name + ' ' + request.user.last_name).strip() or request.user.username
    return render(request, 'learning/path_certificate.html', {
        'path_obj': path_obj,
        'certificate': cert,
        'full_name': full_name,
    })


# ---------------------------------------------------------------------------
# Public Certificate Verification
# ---------------------------------------------------------------------------

def public_certificate_verify(request, code):
    cert = get_object_or_404(Certificate, code=code)
    full_name = (cert.user.first_name + ' ' + cert.user.last_name).strip() or cert.user.username
    return render(request, 'learning/public_certificate.html', {
        'course': cert.course,
        'certificate': cert,
        'full_name': full_name,
    })


# ---------------------------------------------------------------------------
# Instructor Profile
# ---------------------------------------------------------------------------

class InstructorDetailView(View):
    template_name = 'learning/instructor_detail.html'

    def get(self, request, username):
        instructor = get_object_or_404(User, username=username)
        courses = list(
            _course_card_annotations(
                Course.objects.filter(instructor=instructor, status='published')
                .select_related('category')
            ).order_by('-is_featured', 'order')
        )
        total_students = Enrollment.objects.filter(course__instructor=instructor).count()
        total_ratings = sum(c.rating_count for c in courses)
        avg_rating = (
            sum(float(c.avg_rating) * c.rating_count for c in courses) / total_ratings
            if total_ratings else 0
        )
        total_courses = len(courses)
        total_lessons = sum(c.lesson_count for c in courses)
        profile = getattr(instructor, 'telegram_profile', None)
        # The bio lives on the Course model (instructor_bio); surface the first
        # non-empty one. `instructor` is a User, which has no such field.
        bio = next((c.instructor_bio for c in courses if c.instructor_bio), '')
        display_name = instructor.get_full_name() or instructor.username

        return render(request, self.template_name, {
            'instructor': instructor,
            'profile': profile,
            'courses': courses,
            'bio': bio,
            'display_name': display_name,
            'total_students': total_students,
            'total_courses': total_courses,
            'total_lessons': total_lessons,
            'avg_rating': round(avg_rating, 1),
            'wishlist_ids': _user_wishlist_ids(request.user),
        })
