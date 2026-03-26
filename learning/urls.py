from django.urls import path
from . import views

app_name = 'learning'

urlpatterns = [
    path(
        '',
        views.CourseListView.as_view(),
        name='course_list',
    ),
    path(
        '<slug:course_slug>/',
        views.CourseDetailView.as_view(),
        name='course_detail',
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
        '<slug:course_slug>/<slug:module_slug>/<slug:lesson_slug>/davom/boshlash/',
        views.session_start,
        name='session_start',
    ),
    path(
        '<slug:course_slug>/<slug:module_slug>/<slug:lesson_slug>/davom/holat/',
        views.session_event,
        name='session_event',
    ),
    path(
        '<slug:course_slug>/<slug:module_slug>/<slug:lesson_slug>/davom/xabar/',
        views.session_beacon,
        name='session_beacon',
    ),
]
