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
    Course, Module, Lesson, Enrollment, LessonProgress, LessonView, Certificate,
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

    def test_play_records_view_and_enrolls_but_does_not_complete(self):
        # A "view" (play / article open) enrolls and logs activity, but completion
        # is now a separate signal (video ~90%/end, or the manual button).
        course, module, lesson = self._make_course()
        resp = self.client.post(self._url('record_view', course, module, lesson))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Enrollment.objects.filter(user=self.user, course=course).exists())
        self.assertTrue(LessonView.objects.filter(user=self.user, lesson=lesson).exists())
        self.assertFalse(
            LessonProgress.objects.filter(user=self.user, lesson=lesson, is_completed=True).exists()
        )

    def test_mark_complete_completes_the_lesson(self):
        course, module, lesson = self._make_course()
        self.client.post(self._url('mark_complete', course, module, lesson))
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


import json
from .models import Quiz, QuizQuestion, QuizChoice, QuizAttempt


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class MultiSelectQuizTests(TestCase):
    """Grading for multi_select questions: correct only on EXACT set match."""

    def setUp(self):
        self.user = User.objects.create_user(username='quizzer', password='pw-12345!x')
        self.client.force_login(self.user)
        self.course = Course.objects.create(title='Q', slug='q', status='published')
        self.module = Module.objects.create(title='M', slug='m', course=self.course, order=0)
        self.lesson = Lesson.objects.create(title='Test', slug='t', module=self.module,
                                            lesson_type='quiz', order=0)
        self.quiz = Quiz.objects.create(lesson=self.lesson, title='T', pass_percent=50)
        self.q = QuizQuestion.objects.create(quiz=self.quiz, question_type='multi_select',
                                             text='Qaysilar to\'g\'ri?', order=1)
        self.c1 = QuizChoice.objects.create(question=self.q, text='A', is_correct=True, order=1)
        self.c2 = QuizChoice.objects.create(question=self.q, text='B', is_correct=True, order=2)
        self.c3 = QuizChoice.objects.create(question=self.q, text='C', is_correct=False, order=3)

    def _check(self, choice_ids):
        attempt = QuizAttempt.objects.create(user=self.user, quiz=self.quiz, max_score=1)
        url = reverse('learning:check_quiz_answer', args=[
            self.course.slug, self.module.slug, self.lesson.slug, self.quiz.id, attempt.id])
        resp = self.client.post(url, data=json.dumps({'question_id': self.q.id, 'choice_ids': choice_ids}),
                                content_type='application/json')
        return resp.json()

    def test_exact_match_is_correct(self):
        self.assertTrue(self._check([self.c1.id, self.c2.id])['is_correct'])

    def test_partial_selection_is_wrong(self):
        self.assertFalse(self._check([self.c1.id])['is_correct'])

    def test_superset_selection_is_wrong(self):
        self.assertFalse(self._check([self.c1.id, self.c2.id, self.c3.id])['is_correct'])

    def test_correct_choice_ids_returned(self):
        data = self._check([self.c1.id])
        self.assertEqual(set(data['correct_choice_ids']), {self.c1.id, self.c2.id})
