"""Focused tests for the progress/enrollment integrity guarantees.

These lock in the fixes that:
  * block recording progress against unpublished (draft/archived) courses,
  * keep GET requests side-effect free (no implicit enrollment / certificate),
  * enroll the user on first play instead.
"""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    Course, Module, Lesson, Enrollment, LessonProgress, Certificate,
)


# The production manifest static storage needs a collectstatic manifest, which the
# test run doesn't build; swap in the plain backend so template renders work.
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class ProgressIntegrityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='learner', password='pw-12345!x')
        self.client.force_login(self.user)

    def _make_course(self, status='published'):
        course = Course.objects.create(title='C', slug=f'c-{status}', status=status)
        module = Module.objects.create(title='M', slug='m', course=course, order=0)
        lesson = Lesson.objects.create(
            title='L', slug='l', module=module, lesson_type='video',
            youtube_video_id='abc', duration_seconds=100, order=0,
        )
        return course, module, lesson

    def _url(self, name, course, module, lesson):
        return reverse(f'learning:{name}', args=[course.slug, module.slug, lesson.slug])

    def test_cannot_complete_lesson_in_draft_course(self):
        course, module, lesson = self._make_course(status='draft')
        resp = self.client.post(self._url('mark_complete', course, module, lesson))
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(LessonProgress.objects.filter(user=self.user, lesson=lesson).exists())

    def test_cannot_record_view_in_archived_course(self):
        course, module, lesson = self._make_course(status='archived')
        resp = self.client.post(self._url('record_view', course, module, lesson))
        self.assertEqual(resp.status_code, 404)

    def test_viewing_lesson_does_not_enroll(self):
        course, module, lesson = self._make_course()
        resp = self.client.get(self._url('lesson_detail', course, module, lesson))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Enrollment.objects.filter(user=self.user, course=course).exists())

    def test_play_enrolls_and_completes(self):
        course, module, lesson = self._make_course()
        resp = self.client.post(self._url('record_view', course, module, lesson))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Enrollment.objects.filter(user=self.user, course=course).exists())
        self.assertTrue(
            LessonProgress.objects.filter(user=self.user, lesson=lesson, is_completed=True).exists()
        )

    def test_completing_only_lesson_issues_certificate(self):
        course, module, lesson = self._make_course()
        self.client.post(self._url('mark_complete', course, module, lesson))
        self.assertTrue(Certificate.objects.filter(user=self.user, course=course).exists())

    def test_course_detail_get_does_not_issue_certificate(self):
        course, module, lesson = self._make_course()
        # Mark complete via the DB directly (no completion endpoint), then GET the
        # course page — it must not mint a certificate as a side effect.
        LessonProgress.objects.create(user=self.user, lesson=lesson, is_completed=True)
        resp = self.client.get(reverse('learning:course_detail', args=[course.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Certificate.objects.filter(user=self.user, course=course).exists())
