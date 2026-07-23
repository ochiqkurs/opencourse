import json
import pytz

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum, Q, OuterRef, Subquery, IntegerField
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from django.utils.text import Truncator
from django.views import View
from django.views.decorators.cache import cache_page

from .context_processors import absolute_url
from .models import (
    Lesson, LessonProgress, LessonView, Note, Course, Module,
    Category, Enrollment, CourseReview, Certificate,
    Wishlist, LessonQuestion, Announcement,
    Quiz, QuizAttempt, QuizAnswer, QuizQuestion, QuizChoice,
    LearningPath, LearningPathEnrollment, LearningPathCertificate,
    VideoBookmark,
)
from .forms import CourseReviewForm, LessonQuestionForm, LessonAnswerForm
from .selectors import course_progress, courses_completion
from .utils import render_markdown

User = get_user_model()
UZT = pytz.timezone('Asia/Tashkent')  # UTC+5


def _today_uzt():
    return timezone.now().astimezone(UZT).date()


def _meta_desc(*candidates, limit=160):
    """First non-empty candidate, stripped of markup/whitespace and truncated to
    ~`limit` chars for a clean <meta description>/og:description."""
    for c in candidates:
        if c:
            text = ' '.join(strip_tags(str(c)).split())
            if text:
                return Truncator(text).chars(limit)
    return ''


def _iso_duration(seconds):
    """ISO-8601 duration (e.g. PT1H23M45S) from seconds, or None."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return None
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = (f'{h}H' if h else '') + (f'{m}M' if m else '') + (f'{s}S' if s else '')
    return f'PT{parts}'


def _breadcrumb_jsonld(*crumbs):
    """schema.org/BreadcrumbList from (name, path) pairs."""
    return {
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        'itemListElement': [
            {'@type': 'ListItem', 'position': i, 'name': name,
             'item': absolute_url(path)}
            for i, (name, path) in enumerate(crumbs, start=1)
        ],
    }


def _course_jsonld(course, total_duration=None):
    """schema.org/Course structured data for rich search results.

    `hasCourseInstance` (with courseMode + courseWorkload) is what makes the
    course eligible for Google's Course rich results, so pass `total_duration`
    (seconds) whenever the caller has it.
    """
    data = {
        '@context': 'https://schema.org',
        '@type': 'Course',
        'name': course.title,
        'description': _meta_desc(course.subtitle, course.description, course.title),
        'inLanguage': 'uz',
        'url': absolute_url(course.get_absolute_url()),
        'provider': {
            '@type': 'Organization',
            'name': 'Ochiq Kurs',
            'url': absolute_url('/'),
        },
        'isAccessibleForFree': True,
        'offers': {'@type': 'Offer', 'price': '0', 'priceCurrency': 'UZS',
                   'availability': 'https://schema.org/InStock'},
    }
    instance = {'@type': 'CourseInstance', 'courseMode': 'Online',
                'courseLanguage': 'uz'}
    workload = _iso_duration(total_duration)
    if workload:
        instance['courseWorkload'] = workload
    data['hasCourseInstance'] = [instance]
    if course.published_at:
        data['datePublished'] = course.published_at.date().isoformat()
    thumb = course.get_thumbnail_url()
    if thumb:
        data['image'] = absolute_url(thumb)
    if course.instructor_name:
        data['instructor'] = {'@type': 'Person', 'name': course.instructor_name}
    if course.rating_count:
        data['aggregateRating'] = {
            '@type': 'AggregateRating',
            'ratingValue': str(course.avg_rating),
            'reviewCount': course.rating_count,
            'bestRating': '5', 'worstRating': '1',
        }
    return data


def _home_jsonld():
    """WebSite (with a sitelinks search box) + Organization for the home page."""
    search = absolute_url(reverse('learning:search'))
    return [
        {
            '@context': 'https://schema.org',
            '@type': 'WebSite',
            'name': 'Ochiq Kurs',
            'url': absolute_url('/'),
            'inLanguage': 'uz',
            'potentialAction': {
                '@type': 'SearchAction',
                'target': {
                    '@type': 'EntryPoint',
                    'urlTemplate': search + '?q={search_term_string}',
                },
                'query-input': 'required name=search_term_string',
            },
        },
        {
            '@context': 'https://schema.org',
            '@type': 'Organization',
            'name': 'Ochiq Kurs',
            'url': absolute_url('/'),
            'logo': absolute_url(static('images/favicon.png')),
            'sameAs': [f'https://t.me/{settings.TELEGRAM_BOT_USERNAME}'],
        },
    ]


def _lesson_jsonld(lesson, course):
    """Structured data for a lesson page: VideoObject for video lessons
    (eligible for Google video rich results), Article for article/konspekt
    lessons. Returns None for quiz lessons."""
    part_of = {'@type': 'Course', 'name': course.title,
               'url': absolute_url(course.get_absolute_url())}

    if lesson.lesson_type == 'video' and lesson.youtube_video_id:
        vid = lesson.youtube_video_id
        data = {
            '@context': 'https://schema.org',
            '@type': 'VideoObject',
            'name': lesson.title,
            'description': _meta_desc(lesson.description, lesson.title),
            'thumbnailUrl': f'https://img.youtube.com/vi/{vid}/hqdefault.jpg',
            'embedUrl': f'https://www.youtube.com/embed/{vid}',
            'url': absolute_url(lesson.get_absolute_url()),
            'inLanguage': 'uz',
            'isPartOf': part_of,
        }
        if course.published_at:
            data['uploadDate'] = course.published_at.date().isoformat()
        duration = _iso_duration(lesson.duration_seconds)
        if duration:
            data['duration'] = duration
        return data

    if lesson.lesson_type == 'article' and lesson.content:
        data = {
            '@context': 'https://schema.org',
            '@type': 'Article',
            'headline': lesson.title,
            'description': _meta_desc(lesson.description, course.subtitle, lesson.title),
            'url': absolute_url(lesson.get_absolute_url()),
            'inLanguage': 'uz',
            'isPartOf': part_of,
            'isAccessibleForFree': True,
            'publisher': {'@type': 'Organization', 'name': 'Ochiq Kurs',
                          'url': absolute_url('/')},
        }
        if course.instructor_name:
            data['author'] = {'@type': 'Person', 'name': course.instructor_name}
        if course.published_at:
            data['datePublished'] = course.published_at.date().isoformat()
        return data

    return None


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

def _personalized_home(user, all_courses, published):
    """Authenticated-user home-page sections: in-progress courses to continue,
    recent activity, and category-based recommendations. All empty for anonymous
    users. `all_courses` is the pre-annotated published list reused to avoid
    refetching; `published` is the base queryset for recommendations."""
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

    return {
        'continue_learning': continue_learning,
        'recent_activity': recent_activity,
        'recommended': recommended,
    }


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

        personalized = _personalized_home(user, all_courses, published)

        # Hero card thumbnail: the top featured course (falls back to the newest),
        # instead of a hardcoded course slug.
        hero_course = featured[0] if featured else (newest[0] if newest else None)
        hero_course_thumbnail = hero_course.get_thumbnail_url() if hero_course else None
        hero_course_title = hero_course.title if hero_course else ''

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
            **personalized,
            'wishlist_ids': _user_wishlist_ids(request.user),
            'hero_course_thumbnail': hero_course_thumbnail,
            'hero_course_title': hero_course_title,
            'jsonld': _home_jsonld(),
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
            'meta_description': (
                f"{paginator.count} ta o'zbek tilidagi bepul onlayn kurs: dasturlash, "
                "dizayn, ma'lumotlar tahlili va boshqa yo'nalishlar. Video darslar, "
                "konspektlar va testlar bilan."
            ),
            'og_title': 'Bepul onlayn kurslar — Ochiq Kurs',
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
            'meta_description': _meta_desc(
                category.description,
                f"{category.name} yo'nalishidagi o'zbek tilidagi bepul onlayn kurslar.",
            ),
            'og_title': f"Bepul {category.name} kurslari — Ochiq Kurs",
            'jsonld': _breadcrumb_jsonld(
                ('Bosh sahifa', '/'),
                ('Kurslar', reverse('learning:course_list')),
                (category.name, category.get_absolute_url()),
            ),
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
            # Internal search results shouldn't be indexed (crawl waste /
            # thin-content risk); links on the page are still followed.
            'meta_robots': 'noindex, follow',
            'og_title': 'Qidiruv — Ochiq Kurs',
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

        progress = course_progress(course, request.user, modules=modules)

        if request.user.is_authenticated:
            is_enrolled = Enrollment.objects.filter(user=request.user, course=course).exists()
            user_review = CourseReview.objects.filter(user=request.user, course=course).first()
            has_certificate = Certificate.objects.filter(user=request.user, course=course).exists()
            is_wishlisted = Wishlist.objects.filter(user=request.user, course=course).exists()
        else:
            is_enrolled = False
            user_review = None
            has_certificate = False
            is_wishlisted = False

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
            'modules_data': progress.modules_data,
            'next_lesson': progress.next_lesson,
            'total_lessons': progress.total_lessons,
            'total_duration': progress.total_duration,
            'overall_percent': progress.overall_percent,
            'is_complete': progress.is_complete,
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
            # SEO
            'meta_description': _meta_desc(course.subtitle, course.description, course.title),
            'og_title': course.title,
            'og_image': absolute_url(course.get_thumbnail_url()),
            'og_type': 'website',
            'jsonld': [
                _course_jsonld(course, progress.total_duration),
                _breadcrumb_jsonld(
                    ('Bosh sahifa', '/'),
                    ('Kurslar', reverse('learning:course_list')),
                    (course.title, course.get_absolute_url()),
                ),
            ],
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
            # SEO
            'meta_description': _meta_desc(module.description, course.subtitle, course.title),
            'og_title': f'{module.title} — {course.title}',
            'og_image': absolute_url(course.get_thumbnail_url()),
            'jsonld': _breadcrumb_jsonld(
                ('Bosh sahifa', '/'),
                ('Kurslar', reverse('learning:course_list')),
                (course.title, course.get_absolute_url()),
                (module.title, reverse('learning:module_detail',
                                       args=[course.slug, module.slug])),
            ),
        }
        return render(request, self.template_name, ctx)


# ---------------------------------------------------------------------------
# /malaka/<course_slug>/<module_slug>/<lesson_slug>/
# ---------------------------------------------------------------------------

def _adjacent_lessons(course, module, lesson):
    """Return (prev_lesson, next_lesson) for the lesson, crossing module
    boundaries: falls through to the last lesson of the previous module / the
    first lesson of the next module when the lesson is at an edge of its own."""
    sibling_lessons = list(module.lessons.order_by('order'))
    current_index = next(
        (i for i, l in enumerate(sibling_lessons) if l.id == lesson.id), None
    )
    prev_lesson = sibling_lessons[current_index - 1] if current_index and current_index > 0 else None
    next_lesson = sibling_lessons[current_index + 1] if current_index is not None and current_index < len(sibling_lessons) - 1 else None

    if not next_lesson:
        next_module = course.modules.filter(order__gt=module.order).order_by('order').first()
        if next_module:
            next_lesson = next_module.lessons.order_by('order').first()
    if not prev_lesson:
        prev_module = course.modules.filter(order__lt=module.order).order_by('-order').first()
        if prev_module:
            prev_lesson = prev_module.lessons.order_by('-order').first()

    return prev_lesson, next_lesson


def _quiz_context(lesson, user):
    """Context for a standalone quiz-type lesson: per-quiz metadata (attempt
    history, best score, attempts remaining) plus, if the user has an unfinished
    attempt, the `active_*` fields that render it inline. Empty for non-quiz
    lessons or anonymous users."""
    quizzes_with_meta = []
    active_quiz = active_attempt = active_questions = None
    active_answered_ids_json = '[]'
    if lesson.lesson_type == 'quiz' and user.is_authenticated:
        for quiz in lesson.quizzes.all():
            user_attempts = list(
                quiz.attempts.filter(user=user).order_by('-started_at')
            )
            # History shows finished attempts only; an in-progress one isn't a result.
            past_attempts = [a for a in user_attempts if a.completed_at is not None][:10]
            best_attempt = max(past_attempts, key=lambda a: a.percentage()) if past_attempts else None
            attempts_remaining = -1
            if quiz.max_attempts > 0:
                used_attempts = sum(1 for a in user_attempts if a.completed_at is not None)
                attempts_remaining = max(quiz.max_attempts - used_attempts, 0)
            quizzes_with_meta.append({
                'quiz': quiz,
                'questions_count': quiz.questions.count(),
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

    return {
        'quizzes_with_meta': quizzes_with_meta,
        'active_quiz': active_quiz,
        'active_attempt': active_attempt,
        'active_questions': active_questions,
        'active_answered_ids_json': active_answered_ids_json,
    }


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

        prev_lesson, next_lesson = _adjacent_lessons(course, module, lesson)

        sidebar_modules = list(
            course.modules.prefetch_related('lessons').order_by('order')
        )

        progress_summary = course_progress(course, request.user, modules=sidebar_modules)
        done_ids = progress_summary.completed_lesson_ids
        total_in_course = progress_summary.total_lessons
        completed_in_course = progress_summary.total_completed
        course_percent = progress_summary.overall_percent

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

        quiz_ctx = _quiz_context(lesson, request.user)

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
            **quiz_ctx,
            # SEO
            'meta_description': _meta_desc(lesson.description, course.subtitle, course.title),
            'og_title': f'{lesson.title} — {course.title}',
            'og_image': absolute_url(course.get_thumbnail_url()),
            'og_type': 'video.other' if lesson.lesson_type == 'video' else 'article',
            'jsonld': [d for d in (
                _lesson_jsonld(lesson, course),
                _breadcrumb_jsonld(
                    ('Bosh sahifa', '/'),
                    ('Kurslar', reverse('learning:course_list')),
                    (course.title, course.get_absolute_url()),
                    (module.title, reverse('learning:module_detail',
                                           args=[course.slug, module.slug])),
                    (lesson.title, lesson.get_absolute_url()),
                ),
            ) if d],
        }
        return render(request, self.template_name, ctx)


# ---------------------------------------------------------------------------
# POST /malaka/<course_slug>/<module_slug>/<lesson_slug>/davom/korildi/
# ---------------------------------------------------------------------------

@login_required
def record_view(request, course_slug, module_slug, lesson_slug):
    """Record that the user pressed play / opened this lesson today.

    Idempotent per (user, lesson, day). This is a *view*: it enrolls the user and
    bumps the streak (watching counts as daily activity), but it does NOT mark the
    lesson complete. Completion is a separate, explicit signal — the video watched
    to ~90%/the end, or the manual button — both of which POST to
    mark_lesson_complete.
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

    # Touch progress so last_watched_at reflects this view, but leave is_completed
    # untouched — viewing is not completing.
    progress, _ = LessonProgress.objects.get_or_create(
        user=request.user, lesson=lesson
    )
    progress.save(update_fields=['last_watched_at'])

    _update_streak(request.user)

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

    # Enroll on completion too (record_view does the same on first play); otherwise a
    # user who completes via the manual button never gets an Enrollment row and the
    # course is missing from "My Learning" / the profile lists.
    Enrollment.objects.get_or_create(user=request.user, course=lesson.module.course)

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
        'meta_description': (
            "Ochiq Kurs reytingi — eng faol o'quvchilar: ko'rilgan darslar, "
            "tugatilgan darslar va kunlik streaklar bo'yicha ochiq jadval."
        ),
        'og_title': 'Reyting — Ochiq Kurs',
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
        # Only finished attempts consume a slot; an abandoned in-progress attempt is
        # reused by start_quiz, so counting it here would wrongly shrink the remaining count.
        finished_attempts = user_attempts.filter(completed_at__isnull=False)
        used_attempts = finished_attempts.count()
        # Only show finished attempts in the history — an in-progress attempt would
        # otherwise render as a blank-dated "failed" row.
        past_attempts = list(finished_attempts[:10])
        if past_attempts:
            best_attempt = max(past_attempts, key=lambda a: a.percentage())
        if quiz.max_attempts > 0:
            attempts_remaining = max(quiz.max_attempts - used_attempts, 0)
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
        past_count = QuizAttempt.objects.filter(
            user=request.user, quiz=quiz, completed_at__isnull=False
        ).count()
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

    correct_ids = set(question.choices.filter(is_correct=True).values_list('id', flat=True))
    selected_choice = None
    selected_objs = []
    is_correct = False

    if question.question_type == 'multi_select':
        raw = data.get('choice_ids')
        if raw is None:
            return JsonResponse({'error': 'Invalid choice'}, status=400)
        try:
            sel_ids = {int(x) for x in raw}
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Invalid choice'}, status=400)
        selected_objs = list(question.choices.filter(id__in=sel_ids))
        if len(selected_objs) != len(sel_ids):
            return JsonResponse({'error': 'Invalid choice'}, status=400)
        # Correct only if the selected set EXACTLY matches the correct set.
        is_correct = bool(sel_ids) and sel_ids == correct_ids
    else:
        choice_id = data.get('choice_id')
        if choice_id is not None:
            try:
                selected_choice = question.choices.get(id=int(choice_id))
                is_correct = selected_choice.is_correct
            except (QuizChoice.DoesNotExist, ValueError, TypeError):
                return JsonResponse({'error': 'Invalid choice'}, status=400)

    answer, _ = QuizAnswer.objects.update_or_create(
        attempt=attempt,
        question=question,
        defaults={'selected_choice': selected_choice, 'is_correct': is_correct},
    )
    answer.selected_choices.set(selected_objs)  # empty for single/true_false

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
        'correct_choice_ids': sorted(correct_ids),
        'explanation': question.explanation,
        'answered': answered,
        'total': total,
        'finished': finished,
        'result': result,
        'redirect_url': reverse('learning:quiz_result', args=[course_slug, module_slug, lesson_slug, quiz_id, attempt_id]),
    })


@login_required
def quiz_result(request, course_slug, module_slug, lesson_slug, quiz_id, attempt_id):
    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)
    quiz = get_object_or_404(Quiz, id=quiz_id, lesson=lesson)
    attempt = get_object_or_404(QuizAttempt, id=attempt_id, user=request.user, quiz=quiz)
    answers_detail = list(
        attempt.answers.select_related('question', 'selected_choice')
        .prefetch_related('selected_choices', 'question__choices')
    )
    # Unify single- and multi-select into one set of picked choice ids per answer
    # so the template can highlight "your answer" uniformly.
    for a in answers_detail:
        ids = {c.id for c in a.selected_choices.all()}
        if a.selected_choice_id:
            ids.add(a.selected_choice_id)
        a.selected_ids = ids
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
            'meta_description': (
                "O'quv yo'nalishlari — bir necha kursdan iborat tayyor o'quv "
                "rejalari. Frontend, Python backend, ma'lumotlar tahlili va AI "
                "yo'nalishlarini bepul o'rganing."
            ),
            'og_title': "Yo'nalishlar — Ochiq Kurs",
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

        completion = courses_completion(request.user, course_ids)

        for pc in path_courses:
            course = pc.course
            total_courses += 1
            done_lessons, total_lessons = completion[course.id]
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

        # A GET must stay side-effect free, so the certificate is NOT minted here —
        # it is claimed via the POST-only /sertifikat/ endpoint (learning_path_certificate).
        path_complete = total_courses > 0 and completed_courses >= total_courses

        ctx = {
            'path_obj': path_obj,
            'courses_data': courses_data,
            'is_enrolled': is_enrolled,
            'has_certificate': has_certificate,
            'total_courses': total_courses,
            'completed_courses': completed_courses,
            'path_complete': path_complete,
            'overall_percent': int(completed_courses / total_courses * 100) if total_courses else 0,
            'meta_description': _meta_desc(path_obj.description, path_obj.title),
            'og_title': f'{path_obj.title} — Ochiq Kurs',
            'og_image': absolute_url(path_obj.thumbnail.url) if path_obj.thumbnail else None,
            'jsonld': [
                {
                    '@context': 'https://schema.org',
                    '@type': 'ItemList',
                    'name': path_obj.title,
                    'description': _meta_desc(path_obj.description, path_obj.title),
                    'itemListElement': [
                        {'@type': 'ListItem', 'position': i,
                         'name': cd['course'].title,
                         'url': absolute_url(cd['course'].get_absolute_url())}
                        for i, cd in enumerate(courses_data, start=1)
                    ],
                },
                _breadcrumb_jsonld(
                    ('Bosh sahifa', '/'),
                    ("Yo'nalishlar", reverse('learning:learning_path_list')),
                    (path_obj.title, reverse('learning:learning_path_detail',
                                             args=[path_obj.slug])),
                ),
            ],
        }
        return render(request, self.template_name, ctx)


@login_required
def enroll_learning_path(request, path_slug):
    if request.method != 'POST':
        return redirect('learning:learning_path_detail', path_slug=path_slug)
    path_obj = get_object_or_404(LearningPath, slug=path_slug)
    LearningPathEnrollment.objects.get_or_create(user=request.user, path=path_obj)
    messages.success(request, "Yo'nalishga yozildingiz!")
    return redirect('learning:learning_path_detail', path_slug=path_slug)


def _path_is_complete(user, path_obj):
    """True if the user has completed every course in the path (all lessons done)."""
    course_ids = list(path_obj.path_courses.values_list('course_id', flat=True))
    if not course_ids:
        return False
    completion = courses_completion(user, course_ids)
    for cid in course_ids:
        done, total = completion[cid]
        if total == 0 or done < total:
            return False
    return True


@login_required
def learning_path_certificate(request, path_slug):
    path_obj = get_object_or_404(LearningPath, slug=path_slug)
    cert = LearningPathCertificate.objects.filter(user=request.user, path=path_obj).first()
    if not cert and _path_is_complete(request.user, path_obj):
        cert, _ = LearningPathCertificate.objects.get_or_create(user=request.user, path=path_obj)
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
            'meta_description': _meta_desc(
                bio, f"{display_name} — Ochiq Kursdagi o'qituvchi. {total_courses} ta kurs, {total_lessons} ta dars."
            ),
            'og_title': f'{display_name} — Ochiq Kurs',
            'og_image': profile.photo_url if profile and profile.photo_url else None,
            'jsonld': {
                '@context': 'https://schema.org',
                '@type': 'Person',
                'name': display_name,
                'url': absolute_url(reverse('learning:instructor_detail',
                                            args=[instructor.username])),
                'jobTitle': "O'qituvchi",
                'worksFor': {'@type': 'Organization', 'name': 'Ochiq Kurs',
                             'url': absolute_url('/')},
                **({'image': absolute_url(profile.photo_url)}
                   if profile and profile.photo_url else {}),
                **({'description': _meta_desc(bio)} if bio else {}),
            },
        })


# ---------------------------------------------------------------------------
# /llms.txt — GEO: a Markdown map of the site for AI assistants/crawlers
# ---------------------------------------------------------------------------

@cache_page(3600)
def llms_txt(request):
    """llms.txt (llmstxt.org): a Markdown summary of the platform with links to
    every learning path, category and published course, so AI assistants can
    discover and cite the content without crawling the whole site."""
    paths = list(LearningPath.objects.order_by('order', 'title'))
    categories = list(Category.objects.order_by('order', 'name'))
    courses = list(
        Course.objects.filter(status='published')
        .select_related('category')
        .order_by('category__order', 'category__name', 'order')
    )

    lines = [
        "# Ochiq Kurs",
        "",
        f"> O'zbek tilidagi bepul onlayn ta'lim platformasi: {len(courses)} ta "
        "video kurs, modul konspektlari (maqolalar) va testlar. Barcha kontent "
        "ochiq — darslarni o'qish va ko'rish uchun ro'yxatdan o'tish shart emas.",
        "",
        "Har bir kurs YouTube video darslar, matnli konspektlar va testlardan "
        "iborat. Sayt tili — o'zbekcha. Sertifikatlar ochiq havola orqali "
        "tekshiriladi.",
        "",
        "## Yo'nalishlar (o'quv rejalari)",
        "",
    ]
    for p in paths:
        url = absolute_url(reverse('learning:learning_path_detail', args=[p.slug]))
        desc = _meta_desc(p.description, limit=120)
        lines.append(f"- [{p.title}]({url})" + (f": {desc}" if desc else ""))

    lines += ["", "## Kategoriyalar", ""]
    for c in categories:
        lines.append(f"- [{c.name}]({absolute_url(c.get_absolute_url())})")

    lines += ["", "## Kurslar", ""]
    for course in courses:
        url = absolute_url(course.get_absolute_url())
        extra = _meta_desc(course.subtitle, limit=120)
        if course.instructor_name:
            extra = f"{course.instructor_name}. {extra}" if extra else course.instructor_name
        lines.append(f"- [{course.title}]({url})" + (f": {extra}" if extra else ""))

    lines += [
        "",
        "## Qo'shimcha",
        "",
        f"- [Barcha kurslar katalogi]({absolute_url(reverse('learning:course_list'))})",
        f"- [O'quvchilar reytingi]({absolute_url(reverse('learning:leaderboard'))})",
        f"- [Sayt xaritasi]({absolute_url('/sitemap.xml')})",
    ]
    return HttpResponse("\n".join(lines) + "\n",
                        content_type="text/plain; charset=utf-8")
