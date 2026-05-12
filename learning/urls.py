from django.urls import path
from . import views

app_name = 'learning'

urlpatterns = [
    path(
        '',
        views.CourseListView.as_view(),
        name='course_list',
    ),
    # NOTE: explicit prefixed paths must come BEFORE the <course_slug> catch-all.
    path(
        'qidiruv/',
        views.SearchView.as_view(),
        name='search',
    ),
    path(
        'kategoriya/<slug:slug>/',
        views.CategoryDetailView.as_view(),
        name='category_detail',
    ),
    path(
        '<slug:course_slug>/',
        views.CourseDetailView.as_view(),
        name='course_detail',
    ),
    path(
        '<slug:course_slug>/yozilish/',
        views.enroll_course,
        name='enroll',
    ),
    path(
        '<slug:course_slug>/sharh/',
        views.submit_review,
        name='submit_review',
    ),
    path(
        '<slug:course_slug>/sertifikat/',
        views.certificate_view,
        name='certificate',
    ),
    path(
        '<slug:course_slug>/<slug:module_slug>/',
        views.ModuleDetailView.as_view(),
        name='module_detail',
    ),
    path(
        '<slug:course_slug>/<slug:module_slug>/<slug:lesson_slug>/',
        views.LessonDetailView.as_view(),
        name='lesson_detail',
    ),
    path(
        '<slug:course_slug>/<slug:module_slug>/<slug:lesson_slug>/complete/',
        views.mark_lesson_complete,
        name='mark_complete',
    ),
    path(
        '<slug:course_slug>/<slug:module_slug>/<slug:lesson_slug>/note/',
        views.save_note,
        name='save_note',
    ),
    path(
        '<slug:course_slug>/<slug:module_slug>/<slug:lesson_slug>/davom/korildi/',
        views.record_view,
        name='record_view',
    ),
]
