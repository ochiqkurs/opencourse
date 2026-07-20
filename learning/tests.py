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

    def test_quiz_detail_history_excludes_in_progress(self):
        from django.utils import timezone
        QuizAttempt.objects.create(user=self.user, quiz=self.quiz, max_score=1)  # in-progress
        done = QuizAttempt.objects.create(user=self.user, quiz=self.quiz, max_score=1,
                                          completed_at=timezone.now())
        url = reverse('learning:quiz_detail', args=[
            self.course.slug, self.module.slug, self.lesson.slug, self.quiz.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # Only the finished attempt appears in the history, not the in-progress one.
        self.assertEqual(list(resp.context['past_attempts']), [done])


# ═══════════════════════════════════════════════════════════════
# Auth flows (Telegram confirm / issue-code / code login / poll)
# ═══════════════════════════════════════════════════════════════
import json as _json
from datetime import timedelta as _td
from django.contrib.auth.models import User as _User
from django.core.cache import cache as _cache
from django.utils import timezone as _tz
from users.models import TelegramAuthToken, TelegramContact, TelegramProfile, UserProfile
from learning.views import _update_streak, _maybe_issue_certificate, _today_uzt

# Use a known bot secret, an in-memory cache (the prod DB cache table is not
# created in the test DB), and the plain static backend (no manifest in tests).
_AUTH_OVERRIDES = dict(
    BOT_SECRET='test-bot-secret',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


@override_settings(**_AUTH_OVERRIDES)
class TelegramConfirmTests(TestCase):
    URL = '/api/auth/confirm/'

    def setUp(self):
        _cache.clear()

    def _post(self, body, secret='test-bot-secret'):
        return self.client.post(self.URL, data=_json.dumps(body),
                                content_type='application/json', HTTP_X_BOT_SECRET=secret)

    def test_bad_secret_is_forbidden(self):
        self.assertEqual(self._post({'token': 'x', 'telegram_id': 1}, secret='wrong').status_code, 403)

    def test_confirm_creates_new_user_and_profile(self):
        token = TelegramAuthToken.generate()
        resp = self._post({'token': token.token, 'telegram_id': 555,
                           'first_name': 'Ali', 'last_name': 'Valiyev', 'username': 'ali'})
        self.assertEqual(resp.status_code, 200)
        token.refresh_from_db()
        self.assertIsNotNone(token.confirmed_at)
        self.assertTrue(token.is_new_user)
        self.assertEqual(token.user.username, 'ali')
        self.assertTrue(TelegramProfile.objects.filter(telegram_id=555).exists())

    def test_confirm_reuses_existing_telegram_user(self):
        u = _User.objects.create(username='existing')
        TelegramProfile.objects.create(user=u, telegram_id=777, first_name='Old')
        token = TelegramAuthToken.generate()
        self._post({'token': token.token, 'telegram_id': 777, 'first_name': 'New', 'username': 'whatever'})
        token.refresh_from_db()
        self.assertEqual(token.user_id, u.id)
        self.assertFalse(token.is_new_user)

    def test_username_collision_falls_back_to_tg_id(self):
        _User.objects.create(username='taken')
        token = TelegramAuthToken.generate()
        self._post({'token': token.token, 'telegram_id': 888, 'username': 'taken'})
        token.refresh_from_db()
        self.assertEqual(token.user.username, 'tg_888')

    def test_invalid_token_rejected(self):
        self.assertEqual(self._post({'token': 'nope', 'telegram_id': 1}).status_code, 400)


@override_settings(**_AUTH_OVERRIDES)
class IssueCodeTests(TestCase):
    URL = '/api/auth/issue-code/'

    def setUp(self):
        _cache.clear()

    def _post(self, body, secret='test-bot-secret'):
        return self.client.post(self.URL, data=_json.dumps(body),
                                content_type='application/json', HTTP_X_BOT_SECRET=secret)

    def test_bad_secret_forbidden(self):
        self.assertEqual(self._post({'telegram_id': 1}, secret='no').status_code, 403)

    def test_issues_six_digit_preconfirmed_code(self):
        resp = self._post({'telegram_id': 999, 'first_name': 'Z', 'username': 'zed'})
        self.assertEqual(resp.status_code, 200)
        code = resp.json()['short_code']
        self.assertRegex(code, r'^\d{6}$')
        tok = TelegramAuthToken.objects.get(short_code=code)
        self.assertIsNotNone(tok.confirmed_at)
        self.assertEqual(tok.user.username, 'zed')


@override_settings(**_AUTH_OVERRIDES)
class BotStartTests(TestCase):
    URL = '/api/telemetry/bot-start/'

    def setUp(self):
        _cache.clear()

    def _post(self, body, secret='test-bot-secret'):
        return self.client.post(self.URL, data=_json.dumps(body),
                                content_type='application/json', HTTP_X_BOT_SECRET=secret)

    def test_bad_secret_forbidden(self):
        self.assertEqual(self._post({'telegram_id': 1}, secret='no').status_code, 403)

    def test_missing_telegram_id_rejected(self):
        self.assertEqual(self._post({'username': 'x'}).status_code, 400)

    def test_creates_contact_on_first_start(self):
        resp = self._post({'telegram_id': 42, 'chat_id': 42, 'username': 'ali',
                           'first_name': 'Ali', 'language_code': 'uz', 'has_token': True})
        self.assertEqual(resp.status_code, 200)
        c = TelegramContact.objects.get(telegram_id=42)
        self.assertEqual(c.chat_id, 42)
        self.assertEqual(c.username, 'ali')
        self.assertTrue(c.came_with_token)
        self.assertEqual(c.start_count, 1)

    def test_repeated_start_increments_and_does_not_duplicate(self):
        self._post({'telegram_id': 42, 'first_name': 'Ali'})
        self._post({'telegram_id': 42, 'first_name': 'Ali'})
        self.assertEqual(TelegramContact.objects.filter(telegram_id=42).count(), 1)
        self.assertEqual(TelegramContact.objects.get(telegram_id=42).start_count, 2)

    def test_came_with_token_is_sticky(self):
        self._post({'telegram_id': 42, 'has_token': True})
        self._post({'telegram_id': 42})  # later organic start must not unset it
        self.assertTrue(TelegramContact.objects.get(telegram_id=42).came_with_token)

    def test_sparse_update_does_not_wipe_identity(self):
        self._post({'telegram_id': 42, 'username': 'ali', 'first_name': 'Ali'})
        self._post({'telegram_id': 42})  # no identity fields
        c = TelegramContact.objects.get(telegram_id=42)
        self.assertEqual(c.username, 'ali')
        self.assertEqual(c.first_name, 'Ali')


@override_settings(**_AUTH_OVERRIDES)
class BroadcastEndpointTests(TestCase):
    CONTACTS_URL = '/api/telemetry/contacts/'
    BLOCK_URL = '/api/telemetry/mark-blocked/'

    def setUp(self):
        _cache.clear()
        TelegramContact.objects.create(telegram_id=1, chat_id=1, username='a')
        TelegramContact.objects.create(telegram_id=2, chat_id=2, username='b')
        TelegramContact.objects.create(telegram_id=3, chat_id=3, blocked=True)
        TelegramContact.objects.create(telegram_id=4, chat_id=None)  # no chat_id

    def test_contacts_requires_secret(self):
        self.assertEqual(self.client.get(self.CONTACTS_URL).status_code, 403)

    def test_contacts_excludes_blocked_and_chatless(self):
        resp = self.client.get(self.CONTACTS_URL, HTTP_X_BOT_SECRET='test-bot-secret')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        ids = {c['telegram_id'] for c in data['contacts']}
        self.assertEqual(ids, {1, 2})
        self.assertEqual(data['count'], 2)

    def test_mark_blocked_requires_secret(self):
        resp = self.client.post(self.BLOCK_URL, data=_json.dumps({'telegram_ids': [1]}),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_mark_blocked_sets_flag(self):
        resp = self.client.post(self.BLOCK_URL, data=_json.dumps({'telegram_ids': [1, 2]}),
                                content_type='application/json', HTTP_X_BOT_SECRET='test-bot-secret')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['blocked'], 2)
        self.assertTrue(TelegramContact.objects.get(telegram_id=1).blocked)
        # Now excluded from the broadcast list.
        resp = self.client.get(self.CONTACTS_URL, HTTP_X_BOT_SECRET='test-bot-secret')
        self.assertEqual(resp.json()['count'], 0)


@override_settings(**_AUTH_OVERRIDES)
class CodeLoginTests(TestCase):
    def setUp(self):
        _cache.clear()

    def _issue(self, is_new=False):
        u = _User.objects.create(username='coder')
        return u, TelegramAuthToken.issue_for_user(u, is_new)

    def test_valid_code_logs_in_and_consumes_token(self):
        u, tok = self._issue()
        resp = self.client.post('/users/login/', {'short_code': tok.short_code})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), u.id)
        self.assertFalse(TelegramAuthToken.objects.filter(pk=tok.pk).exists())

    def test_replayed_code_fails(self):
        u, tok = self._issue()
        code = tok.short_code
        self.client.post('/users/login/', {'short_code': code})
        self.client.logout()
        resp = self.client.post('/users/login/', {'short_code': code})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_wrong_code_fails(self):
        resp = self.client.post('/users/login/', {'short_code': '000000'})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)


@override_settings(**_AUTH_OVERRIDES)
class CheckTokenTests(TestCase):
    def setUp(self):
        _cache.clear()

    def _url(self, t):
        return f'/api/auth/check/{t}/'

    def test_pending(self):
        token = TelegramAuthToken.generate()
        self.assertEqual(self.client.get(self._url(token.token)).json()['status'], 'pending')

    def test_confirmed_logs_in_and_deletes_token(self):
        u = _User.objects.create(username='checker')
        token = TelegramAuthToken.generate()
        token.user = u
        token.confirmed_at = _tz.now()
        token.save()
        data = self.client.get(self._url(token.token)).json()
        self.assertEqual(data['status'], 'confirmed')
        self.assertEqual(int(self.client.session['_auth_user_id']), u.id)
        self.assertFalse(TelegramAuthToken.objects.filter(pk=token.pk).exists())

    def test_invalid_token(self):
        self.assertEqual(self.client.get(self._url('does-not-exist')).json()['status'], 'invalid')


# ═══════════════════════════════════════════════════════════════
# Streak logic (_update_streak / UserProfile.live_streak)
# ═══════════════════════════════════════════════════════════════
class StreakTests(TestCase):
    def setUp(self):
        self.user = _User.objects.create_user(username='streaker', password='pw-12345!x')
        self.today = _today_uzt()

    def _p(self):
        return UserProfile.objects.get(user=self.user)

    def test_first_activity_starts_at_one(self):
        _update_streak(self.user)
        self.assertEqual(self._p().current_streak, 1)

    def test_consecutive_day_increments(self):
        UserProfile.objects.create(user=self.user, current_streak=3, longest_streak=3,
                                   last_activity_date=self.today - _td(days=1))
        _update_streak(self.user)
        p = self._p()
        self.assertEqual(p.current_streak, 4)
        self.assertEqual(p.longest_streak, 4)

    def test_gap_resets_to_one_but_keeps_record(self):
        UserProfile.objects.create(user=self.user, current_streak=9, longest_streak=9,
                                   last_activity_date=self.today - _td(days=3))
        _update_streak(self.user)
        p = self._p()
        self.assertEqual(p.current_streak, 1)
        self.assertEqual(p.longest_streak, 9)

    def test_same_day_is_noop(self):
        UserProfile.objects.create(user=self.user, current_streak=5, longest_streak=5,
                                   last_activity_date=self.today)
        _update_streak(self.user)
        self.assertEqual(self._p().current_streak, 5)

    def test_live_streak_zero_after_lapse(self):
        p = UserProfile.objects.create(user=self.user, current_streak=7, longest_streak=7,
                                       last_activity_date=self.today - _td(days=2))
        self.assertEqual(p.live_streak, 0)

    def test_live_streak_alive_if_yesterday(self):
        p = UserProfile.objects.create(user=self.user, current_streak=7, longest_streak=7,
                                       last_activity_date=self.today - _td(days=1))
        self.assertEqual(p.live_streak, 7)


# ═══════════════════════════════════════════════════════════════
# Certificate auto-issue (_maybe_issue_certificate)
# ═══════════════════════════════════════════════════════════════
class CertificateAutoIssueTests(TestCase):
    def setUp(self):
        self.user = _User.objects.create_user(username='grad', password='pw-12345!x')
        self.course = Course.objects.create(title='C', slug='cc', status='published')
        self.m = Module.objects.create(title='M', slug='m', course=self.course, order=0)
        self.l1 = Lesson.objects.create(title='L1', slug='l1', module=self.m, order=0)
        self.l2 = Lesson.objects.create(title='L2', slug='l2', module=self.m, order=1)

    def test_partial_completion_no_certificate(self):
        LessonProgress.objects.create(user=self.user, lesson=self.l1, is_completed=True)
        _maybe_issue_certificate(self.user, self.course)
        self.assertFalse(Certificate.objects.filter(user=self.user, course=self.course).exists())

    def test_full_completion_issues_certificate(self):
        LessonProgress.objects.create(user=self.user, lesson=self.l1, is_completed=True)
        LessonProgress.objects.create(user=self.user, lesson=self.l2, is_completed=True)
        _maybe_issue_certificate(self.user, self.course)
        self.assertTrue(Certificate.objects.filter(user=self.user, course=self.course).exists())

    def test_empty_course_never_certifies(self):
        empty = Course.objects.create(title='E', slug='ee', status='published')
        _maybe_issue_certificate(self.user, empty)
        self.assertFalse(Certificate.objects.filter(user=self.user, course=empty).exists())


# ═══════════════════════════════════════════════════════════════
# Avatar localization (_localize_avatar) — token-free, Telegram-aware
# ═══════════════════════════════════════════════════════════════
import tempfile as _tempfile
from unittest import mock as _mock
from users.views import _localize_avatar


def _fake_resp(content, ctype):
    r = _mock.Mock()
    r.status_code = 200
    r.content = content
    r.headers = {'Content-Type': ctype}
    r.raise_for_status = lambda: None
    return r


@override_settings(MEDIA_ROOT=_tempfile.mkdtemp(), STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class LocalizeAvatarTests(TestCase):
    TG = 'https://api.telegram.org/file/bot123:ABC/photos/file_1.jpg'

    def test_octet_stream_jpeg_is_saved(self):
        # Telegram serves profile photos as application/octet-stream; they must
        # still be recognized (via magic bytes) and saved, not dropped.
        resp = _fake_resp(b'\xff\xd8\xff\xe0' + b'jpeg-bytes', 'application/octet-stream')
        with _mock.patch('users.views.http_requests.get', return_value=resp):
            url = _localize_avatar(self.TG)
        self.assertTrue(url.startswith('/media/avatars/'), url)
        self.assertTrue(url.endswith('.jpg'), url)

    def test_png_octet_stream_is_saved(self):
        resp = _fake_resp(b'\x89PNG\r\n\x1a\n' + b'png-bytes', 'application/octet-stream')
        with _mock.patch('users.views.http_requests.get', return_value=resp):
            url = _localize_avatar(self.TG)
        self.assertTrue(url.endswith('.png'), url)

    def test_non_image_rejected(self):
        resp = _fake_resp(b'{"ok":false}', 'application/json')
        with _mock.patch('users.views.http_requests.get', return_value=resp):
            self.assertEqual(_localize_avatar(self.TG), '')

    def test_non_telegram_url_passthrough(self):
        self.assertEqual(_localize_avatar('/media/avatars/x.jpg'), '/media/avatars/x.jpg')

    def test_empty_returns_empty(self):
        self.assertEqual(_localize_avatar(''), '')


# --- SEO foundation -------------------------------------------------------
_SEO_OVERRIDES = dict(
    SITE_URL='https://ochiqkurs.uz',
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


@override_settings(**_SEO_OVERRIDES)
class SeoTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(
            title='Python Asoslari', slug='python-asoslari',
            subtitle='Noldan Python', status='published',
        )
        self.module = Module.objects.create(title='M', slug='m', course=self.course, order=0)
        self.lesson = Lesson.objects.create(
            title='Kirish', slug='kirish', module=self.module, lesson_type='video',
            youtube_video_id='abc123', duration_seconds=754, order=0,
        )

    def test_sitemap_lists_published_course(self):
        resp = self.client.get('/sitemap.xml')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('/malaka/python-asoslari/', body)
        self.assertIn('https://', body)

    def test_robots_txt(self):
        resp = self.client.get('/robots.txt')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/plain')
        body = resp.content.decode()
        self.assertIn('Sitemap: https://ochiqkurs.uz/sitemap.xml', body)
        self.assertIn('Disallow: /admin/', body)
        # /users/ and /api/ are left crawlable so Google can honour their
        # X-Robots-Tag: noindex (see NoindexMiddleware) instead of indexing
        # them blindly from links.
        self.assertNotIn('Disallow: /users/', body)
        self.assertNotIn('Disallow: /api/', body)

    def test_noindex_header_on_account_paths(self):
        for path in ('/users/login/', '/api/'):
            resp = self.client.get(path)
            self.assertEqual(
                resp.get('X-Robots-Tag'), 'noindex, nofollow',
                f'{path} should carry a noindex header',
            )

    def test_no_noindex_header_on_public_pages(self):
        resp = self.client.get('/')
        self.assertIsNone(resp.get('X-Robots-Tag'))

    def test_course_detail_has_og_and_jsonld(self):
        resp = self.client.get(reverse('learning:course_detail', args=[self.course.slug]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('property="og:title"', html)
        self.assertIn('property="og:image"', html)
        self.assertIn('rel="canonical"', html)
        self.assertIn('application/ld+json', html)
        self.assertIn('"@type": "Course"', html)

    def test_lesson_detail_has_videoobject_jsonld(self):
        self.client.force_login(User.objects.create_user('u', password='pw-12345!x'))
        resp = self.client.get(self.lesson.get_absolute_url())
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('"@type": "VideoObject"', html)
        self.assertIn('PT12M34S', html)

    def test_home_has_website_jsonld(self):
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('"@type": "WebSite"', html)
        self.assertIn('SearchAction', html)

    def test_canonical_uses_site_url(self):
        resp = self.client.get(reverse('home'))
        self.assertIn('https://ochiqkurs.uz/', resp.content.decode())

    def test_seo_meta_comment_not_leaked(self):
        # A multi-line {# #} comment is NOT stripped by Django and leaks as text;
        # the seo_meta include must use {% comment %} so nothing renders.
        resp = self.client.get(reverse('home'))
        self.assertNotIn('SEO meta tags', resp.content.decode())

    @override_settings(GOOGLE_VERIFICATION_FILE='googletest123.html')
    def test_google_verification_file_view(self):
        # The route is registered at import time from the env, so exercise the
        # view directly; it must echo the configured filename as the body.
        from django.test import RequestFactory
        from config.urls import google_verification_file
        resp = google_verification_file(RequestFactory().get('/googletest123.html'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content.decode().strip(),
                         'google-site-verification: googletest123.html')
