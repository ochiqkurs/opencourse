import hashlib
import hmac
import json
import random
import re
import requests as http_requests
from datetime import timedelta
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from learning.models import (
    Course, Module, Lesson, LessonProgress, LessonView,
    Enrollment, Certificate,
)
from learning.forms import CourseForm, ModuleForm, LessonForm
from .forms import (
    UserProfileForm, SetUsernamePasswordForm, UsernamePasswordLoginForm,
)
from .models import TelegramAuthToken, TelegramContact, TelegramProfile, UserProfile


def _client_ip(request):
    """Best-effort real client IP for rate limiting.

    Production sits behind Cloudflare → nginx → gunicorn. Cloudflare sets
    `CF-Connecting-IP` to the true client address and overwrites any client-supplied
    value, so it's the one header a remote client cannot spoof. Prefer it.

    Without Cloudflare (e.g. nginx alone), nginx's `$proxy_add_x_forwarded_for`
    appends the peer it observed as the *last* XFF entry, so that's the safe one to
    trust there. (Behind Cloudflare the last entry is the Cloudflare edge IP — shared
    by many users — which would collapse everyone into one rate-limit bucket, hence
    CF-Connecting-IP takes precedence.) Fall back to REMOTE_ADDR.
    """
    cf_ip = request.META.get('HTTP_CF_CONNECTING_IP', '').strip()
    if cf_ip:
        return cf_ip
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR', '').strip()


def _check_rate_limit(ip, max_requests=60, window=60, prefix='check'):
    """Fixed-window rate limiter using Django cache. Returns True if limit exceeded."""
    key = f'rl:{prefix}:{ip}'
    cache.add(key, 0, window)
    try:
        count = cache.incr(key)
    except ValueError:
        # Key expired between add and incr; treat as a fresh window.
        cache.set(key, 1, window)
        count = 1
    return count > max_requests


def _safe_next(request):
    """Return a same-origin redirect target from ?next= / POSTed next, else ''.

    Guards against open-redirect: only same-host, same-scheme relative paths pass.
    """
    nxt = request.POST.get('next') or request.GET.get('next') or ''
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return ''


def _cleanup_expired_tokens():
    """Opportunistically delete auth tokens past their 10-minute TTL.

    Called probabilistically from the login page render so the table stays bounded
    without a cron. The `clear_expired_tokens` management command does the same job
    deterministically.
    """
    cutoff = timezone.now() - timedelta(minutes=10)
    TelegramAuthToken.objects.filter(created_at__lt=cutoff).delete()


def _localize_avatar(photo_url):
    """Download a Telegram-hosted avatar to local media so the stored URL never
    contains the bot token.

    Telegram file URLs embed the bot token (`.../file/bot<TOKEN>/<path>`); persisting
    one and rendering it in an `<img src>` (the leaderboard/instructor pages are public)
    leaks the token to anyone viewing the page source. They also expire within ~1 hour,
    so they break anyway. Fetch the image once, server-side, and store a token-free
    `/media/` URL instead.

    Best-effort: any failure returns '' (no avatar) rather than blocking sign-in.
    Non-Telegram URLs are passed through unchanged.
    """
    if not photo_url:
        return ''
    if not photo_url.startswith('https://api.telegram.org/'):
        return photo_url
    try:
        resp = http_requests.get(photo_url, timeout=10)
        resp.raise_for_status()
        content = resp.content
        # Telegram's file API serves photos as `application/octet-stream`, so don't
        # require an image/* content-type — sniff the magic bytes instead (and fall
        # back to the header). Anything that isn't a recognizable image is rejected.
        if content[:3] == b'\xff\xd8\xff':
            ext = 'jpg'
        elif content[:8] == b'\x89PNG\r\n\x1a\n':
            ext = 'png'
        elif resp.headers.get('Content-Type', '').startswith('image/'):
            ext = 'png' if 'png' in resp.headers['Content-Type'] else 'jpg'
        else:
            return ''
        # Key the filename on the file path (not the token) so the same photo maps to a
        # stable name and a rotated token doesn't orphan copies.
        digest = hashlib.sha1(photo_url.split('/file/bot', 1)[-1].encode()).hexdigest()[:16]
        path = f'avatars/{digest}.{ext}'
        if not default_storage.exists(path):
            default_storage.save(path, ContentFile(content))
        return default_storage.url(path)
    except Exception:
        return ''


def _get_or_create_telegram_user(telegram_id, first_name, last_name, username, photo_url):
    """Get or create a User + TelegramProfile from Telegram identity data.

    Returns (user, is_new_user). Caller is responsible for the surrounding transaction.
    """
    try:
        profile = TelegramProfile.objects.select_related('user').get(telegram_id=telegram_id)
        user = profile.user
        is_new_user = False
    except TelegramProfile.DoesNotExist:
        chosen_username = (
            username
            if username and not User.objects.filter(username=username).exists()
            else f'tg_{telegram_id}'
        )
        user = User(
            username=chosen_username,
            first_name=first_name,
            last_name=last_name,
        )
        user.set_unusable_password()
        user.save()
        profile = TelegramProfile(user=user, telegram_id=telegram_id)
        is_new_user = True

    profile.first_name = first_name
    profile.last_name = last_name
    profile.username = username
    profile.photo_url = photo_url
    profile.save()

    if not is_new_user:
        user.first_name = first_name
        user.last_name = last_name
        user.save(update_fields=['first_name', 'last_name'])

    return user, is_new_user


class TelegramLoginView(View):
    """Login page. Handles three sign-in methods on one page:
      - bot-link auth (browser polls CheckTokenView),
      - bot-issued 6-digit code (the code form),
      - username + password (the inline password form).
    """
    template_name = 'registration/login.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('/users/profile/')
        return render(request, self.template_name, self._context(request))

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('/users/profile/')
        # The password form carries username/password; the code form carries short_code.
        if 'username' in request.POST or 'password' in request.POST:
            return self._handle_password(request)
        return self._handle_code(request)

    def _handle_code(self, request):
        if _check_rate_limit(_client_ip(request), max_requests=10, window=60, prefix='code'):
            return render(request, self.template_name, self._context(
                request, code_error="Juda ko'p urinish. Bir necha daqiqadan keyin qayta urinib ko'ring.",
            ))

        raw = request.POST.get('short_code', '')
        code = re.sub(r'\D', '', raw)
        if len(code) != 6:
            return render(request, self.template_name, self._context(
                request, code_error="Kod 6 ta raqamdan iborat bo'lishi kerak.", code_value=raw,
            ))

        cutoff = timezone.now() - timedelta(minutes=10)
        auth_token = (
            TelegramAuthToken.objects
            .filter(
                short_code=code,
                confirmed_at__isnull=False,
                user__isnull=False,
                created_at__gt=cutoff,
            )
            .select_related('user')
            .order_by('-created_at')
            .first()
        )
        if auth_token is None:
            return render(request, self.template_name, self._context(
                request, code_error="Kod noto'g'ri yoki muddati tugagan. Botdan yangi kod oling.",
                code_value=raw,
            ))

        user = auth_token.user
        is_new_user = auth_token.is_new_user
        auth_token.delete()  # one-time use
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return redirect(self._post_login_url(request, is_new_user))

    def _handle_password(self, request):
        form = UsernamePasswordLoginForm(request.POST)
        if _check_rate_limit(_client_ip(request), max_requests=10, window=60, prefix='login'):
            return render(request, self.template_name, self._context(
                request, pwd_error="Juda ko'p urinish. Bir necha daqiqadan keyin qayta urinib ko'ring.",
                pwd_username=request.POST.get('username', ''),
            ))
        if form.is_valid():
            login(request, form.cleaned_data['user'], backend='django.contrib.auth.backends.ModelBackend')
            return redirect(self._post_login_url(request, is_new_user=False))
        # Surface the form's non-field error inline (bad credentials / passwordless account).
        errors = form.non_field_errors()
        return render(request, self.template_name, self._context(
            request,
            pwd_error=errors[0] if errors else "Username yoki parol noto'g'ri.",
            pwd_username=request.POST.get('username', ''),
        ))

    def _post_login_url(self, request, is_new_user):
        nxt = _safe_next(request)
        if nxt:
            return nxt
        return '/users/profile/' if is_new_user else settings.LOGIN_REDIRECT_URL

    def _context(self, request, code_error=None, code_value='', pwd_error=None, pwd_username=''):
        # Keep the token table bounded without a cron (≈3% of renders run the sweep).
        if random.random() < 0.03:
            _cleanup_expired_tokens()
        auth_token = TelegramAuthToken.generate()
        bot_username = getattr(settings, 'TELEGRAM_BOT_USERNAME', 'ochiqkurs_bot')
        bot_url = f'https://t.me/{bot_username}?start={auth_token.token}'
        return {
            'bot_url': bot_url,
            'token': auth_token.token,
            'bot_username': bot_username,
            'code_error': code_error,
            'code_value': code_value,
            'pwd_error': pwd_error,
            'pwd_username': pwd_username,
            'next': _safe_next(request),
        }


# Signup is the same Telegram-based flow as login.
class SignupView(TelegramLoginView):
    pass


@method_decorator(csrf_exempt, name='dispatch')
class TelegramConfirmView(View):
    """Called by the Telegram bot after user presses Start (bot-link flow)."""

    def post(self, request):
        secret = request.headers.get('X-Bot-Secret', '')
        if not hmac.compare_digest(secret, settings.BOT_SECRET):
            return JsonResponse({'error': 'Forbidden'}, status=403)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        token_str = data.get('token', '').strip()
        telegram_id = data.get('telegram_id')
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        username = data.get('username', '').strip()
        photo_url = data.get('photo_url', '').strip()

        if not token_str or not telegram_id:
            return JsonResponse({'error': 'token and telegram_id are required'}, status=400)

        try:
            auth_token = TelegramAuthToken.objects.get(token=token_str)
        except TelegramAuthToken.DoesNotExist:
            return JsonResponse({'error': 'invalid'}, status=400)

        if not auth_token.is_valid():
            return JsonResponse({'error': 'expired or already confirmed'}, status=400)

        # Localize the avatar (network I/O) outside the DB transaction so we never
        # store the token-bearing Telegram URL.
        photo_url = _localize_avatar(photo_url)

        with transaction.atomic():
            user, is_new_user = _get_or_create_telegram_user(
                telegram_id, first_name, last_name, username, photo_url,
            )
            auth_token.user = user
            auth_token.is_new_user = is_new_user
            auth_token.confirmed_at = timezone.now()
            auth_token.save()

        return JsonResponse({'status': 'ok'})


@method_decorator(csrf_exempt, name='dispatch')
class IssueCodeView(View):
    """Called by the Telegram bot when a user requests a login code.

    The bot has already authenticated the Telegram identity, so the server
    simply mints a pre-confirmed token tied to that user and returns a
    short 6-digit code. The user types this code on the website to sign in.

    Gated by the same X-Bot-Secret check as TelegramConfirmView.
    """

    def post(self, request):
        secret = request.headers.get('X-Bot-Secret', '')
        if not hmac.compare_digest(secret, settings.BOT_SECRET):
            return JsonResponse({'error': 'Forbidden'}, status=403)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        telegram_id = data.get('telegram_id')
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        username = data.get('username', '').strip()
        photo_url = data.get('photo_url', '').strip()

        if not telegram_id:
            return JsonResponse({'error': 'telegram_id is required'}, status=400)

        # Localize the avatar (network I/O) outside the DB transaction so we never
        # store the token-bearing Telegram URL.
        photo_url = _localize_avatar(photo_url)

        with transaction.atomic():
            user, is_new_user = _get_or_create_telegram_user(
                telegram_id, first_name, last_name, username, photo_url,
            )
            auth_token = TelegramAuthToken.issue_for_user(user, is_new_user)

        return JsonResponse({
            'short_code': auth_token.short_code,
            'expires_in_seconds': 600,
        })


@method_decorator(csrf_exempt, name='dispatch')
class BotStartView(View):
    """Records anyone who presses /start on the bot, even without logging in.

    Fire-and-forget telemetry from the bot (best-effort; the bot never blocks
    on it), gated by the same X-Bot-Secret check as the other bot endpoints.
    Feeds funnel metrics (start → login) and a broadcast list — the stored
    chat_id is what a future broadcast would target.
    """

    def post(self, request):
        secret = request.headers.get('X-Bot-Secret', '')
        if not hmac.compare_digest(secret, settings.BOT_SECRET):
            return JsonResponse({'error': 'Forbidden'}, status=403)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        telegram_id = data.get('telegram_id')
        if not telegram_id:
            return JsonResponse({'error': 'telegram_id is required'}, status=400)

        with transaction.atomic():
            contact, _ = TelegramContact.objects.get_or_create(telegram_id=telegram_id)
            # Only overwrite with non-empty values so a later sparse update can't
            # wipe identity we already captured.
            contact.chat_id = data.get('chat_id') or contact.chat_id
            contact.username = data.get('username', '').strip() or contact.username
            contact.first_name = data.get('first_name', '').strip() or contact.first_name
            contact.last_name = data.get('last_name', '').strip() or contact.last_name
            contact.language_code = (
                data.get('language_code', '').strip() or contact.language_code
            )
            if data.get('has_token'):
                contact.came_with_token = True  # sticky
            contact.start_count += 1
            contact.save()

        return JsonResponse({'status': 'ok'})


@method_decorator(csrf_exempt, name='dispatch')
class ContactsListView(View):
    """Returns the broadcast list (non-blocked contacts that have a chat_id).

    Consumed by the bot's broadcast script. Gated by X-Bot-Secret. Read-only.
    """

    def get(self, request):
        secret = request.headers.get('X-Bot-Secret', '')
        if not hmac.compare_digest(secret, settings.BOT_SECRET):
            return JsonResponse({'error': 'Forbidden'}, status=403)

        contacts = list(
            TelegramContact.objects
            .filter(blocked=False, chat_id__isnull=False)
            .values('telegram_id', 'chat_id')
        )
        return JsonResponse({'count': len(contacts), 'contacts': contacts})


@method_decorator(csrf_exempt, name='dispatch')
class MarkBlockedView(View):
    """Marks contacts (by telegram_id) as blocked so future broadcasts skip them.

    Called by the broadcast script for users who have blocked the bot. Gated by
    X-Bot-Secret.
    """

    def post(self, request):
        secret = request.headers.get('X-Bot-Secret', '')
        if not hmac.compare_digest(secret, settings.BOT_SECRET):
            return JsonResponse({'error': 'Forbidden'}, status=403)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        telegram_ids = data.get('telegram_ids') or []
        if not isinstance(telegram_ids, list):
            return JsonResponse({'error': 'telegram_ids must be a list'}, status=400)

        updated = (
            TelegramContact.objects
            .filter(telegram_id__in=telegram_ids)
            .update(blocked=True)
        )
        return JsonResponse({'blocked': updated})


class CheckTokenView(View):
    """Polled by the browser every 2 seconds to check Telegram confirmation status."""

    def get(self, request, token):
        ip = _client_ip(request)
        if _check_rate_limit(ip):
            return JsonResponse({'status': 'rate_limited'}, status=429)

        try:
            auth_token = TelegramAuthToken.objects.select_related('user').get(token=token)
        except TelegramAuthToken.DoesNotExist:
            return JsonResponse({'status': 'invalid'})

        if auth_token.is_expired():
            return JsonResponse({'status': 'expired'})

        if auth_token.confirmed_at and auth_token.user:
            login(request, auth_token.user, backend='django.contrib.auth.backends.ModelBackend')
            redirect_url = '/users/profile/' if auth_token.is_new_user else settings.LOGIN_REDIRECT_URL
            auth_token.delete()
            return JsonResponse({'status': 'confirmed', 'redirect': redirect_url})

        return JsonResponse({'status': 'pending'})


def _activity_heatmap(user):
    """Build the GitHub-style activity graph for the profile: a {date: count} map
    of distinct lessons watched per day over the last 365 days, plus the days
    bucketed into Monday-aligned weeks for the template grid."""
    # Use the project timezone (Asia/Tashkent) so the day buckets line up with
    # how LessonView.viewed_on is stamped; date.today() would use server time.
    since = timezone.localdate() - timedelta(days=364)
    raw_activity = (
        LessonView.objects
        .filter(user=user, viewed_on__gte=since)
        .values('viewed_on')
        .annotate(lessons=Count('lesson', distinct=True))
    )
    activity_map = {str(row['viewed_on']): row['lessons'] for row in raw_activity}

    today = timezone.localdate()
    # 364 kun oldindan boshlab bugunga qadar
    days = [today - timedelta(days=i) for i in range(364, -1, -1)]
    # Boshini dushanbaga to'ldirish — None emas, balki alohida flag
    start_weekday = days[0].weekday()  # 0=Dushanba, 6=Yakshanba
    padded = [None] * start_weekday + days
    # Haftalar ro'yxatiga bo'lish
    weeks = [padded[i:i + 7] for i in range(0, len(padded), 7)]
    return activity_map, weeks


def _in_progress_courses(user):
    """Courses the user has progress in, each annotated with completion percent
    and the next unfinished lesson, most-recently-watched first."""
    user_progress = list(
        LessonProgress.objects
        .filter(user=user)
        .select_related('lesson__module__course')
        .order_by('-last_watched_at')
    )
    # Group by course preserving most-recent-first order per course
    course_data = {}  # course_id -> {'course', 'completed_ids', 'last_watched_at'}
    for lp in user_progress:
        course = lp.lesson.module.course
        cid = course.id
        if cid not in course_data:
            course_data[cid] = {
                'course': course,
                'completed_ids': set(),
                'last_watched_at': lp.last_watched_at,
            }
        if lp.is_completed:
            course_data[cid]['completed_ids'].add(lp.lesson_id)

    # Fetch lessons for every in-progress course in one query and group them,
    # rather than issuing a per-course query inside the loop (an N+1).
    lessons_by_course = {}
    for lsn in (
        Lesson.objects
        .filter(module__course_id__in=course_data.keys())
        .select_related('module')
        .order_by('module__order', 'order')
    ):
        lessons_by_course.setdefault(lsn.module.course_id, []).append(lsn)

    in_progress_courses = []
    for cid, data in course_data.items():
        course = data['course']
        lessons = lessons_by_course.get(cid, [])
        total_lessons = len(lessons)
        completed_ids = data['completed_ids']
        completed_lessons = len(completed_ids)
        progress_percent = int(completed_lessons / total_lessons * 100) if total_lessons else 0

        next_lesson = next((l for l in lessons if l.id not in completed_ids), None)

        in_progress_courses.append({
            'course_title': course.title,
            'course_slug': course.slug,
            'total_lessons': total_lessons,
            'completed_lessons': completed_lessons,
            'progress_percent': progress_percent,
            'next_lesson_slug': next_lesson.slug if next_lesson else None,
            'next_module_slug': next_lesson.module.slug if next_lesson else None,
            'last_watched_at': data['last_watched_at'],
        })

    in_progress_courses.sort(key=lambda x: x['last_watched_at'], reverse=True)
    return in_progress_courses


class ProfileView(LoginRequiredMixin, View):
    template_name = 'users/profile.html'

    def _base_context(self, request):
        user = request.user
        profile, _ = UserProfile.objects.get_or_create(user=user)
        activity_map, weeks = _activity_heatmap(user)

        return {
            'form': UserProfileForm(instance=user),
            'is_admin': user.is_staff or user.is_superuser,
            'user': user,
            'user_lesson_views': LessonView.objects.filter(user=user).count(),
            'user_completed_lessons': LessonProgress.objects.filter(user=user, is_completed=True).count(),
            'has_usable_password': user.has_usable_password(),
            'password_form': PasswordChangeForm(user) if user.has_usable_password() else SetPasswordForm(user),
            'activity_map': activity_map,
            'weeks': weeks,
            'current_streak': profile.live_streak,
            'longest_streak': profile.longest_streak,
            'in_progress_courses': _in_progress_courses(user),
            'certificates': list(
                Certificate.objects.filter(user=user)
                .select_related('course')
                .order_by('-issued_at')
            ),
            'enrollment_count': Enrollment.objects.filter(user=user).count(),
        }

    def get(self, request):
        return render(request, self.template_name, self._base_context(request))

    def post(self, request):
        user = request.user

        if 'update_profile' in request.POST:
            form = UserProfileForm(request.POST, instance=user)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profil ma\'lumotlari saqlandi.')
                return redirect('users:profile')
            ctx = self._base_context(request)
            ctx['form'] = form
            return render(request, self.template_name, ctx)

        if 'change_password' in request.POST:
            if user.has_usable_password():
                pw_form = PasswordChangeForm(user, request.POST)
            else:
                pw_form = SetPasswordForm(user, request.POST)
            if pw_form.is_valid():
                pw_form.save()
                update_session_auth_hash(request, pw_form.user)
                messages.success(request, 'Parol muvaffaqiyatli o\'rnatildi.')
                return redirect('users:profile')
            ctx = self._base_context(request)
            ctx['password_form'] = pw_form
            return render(request, self.template_name, ctx)

        return redirect('users:profile')


class SetPasswordView(LoginRequiredMixin, View):
    """Lets a logged-in (Telegram-authenticated) user set or change a username + password
    so they can sign in without Telegram."""
    template_name = 'users/set_password.html'

    def get(self, request):
        form = SetUsernamePasswordForm(request.user, initial={'username': request.user.username})
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = SetUsernamePasswordForm(request.user, request.POST)
        if form.is_valid():
            user = request.user
            user.username = form.cleaned_data['username']
            user.set_password(form.cleaned_data['password1'])
            user.save(update_fields=['username', 'password'])
            update_session_auth_hash(request, user)  # keep the current session alive
            messages.success(request, 'Parol muvaffaqiyatli saqlandi.')
            return redirect('users:profile')
        return render(request, self.template_name, {'form': form})


class UsernamePasswordLoginView(View):
    """Username + password login, for users who have set a password in their profile."""
    template_name = 'registration/login_password.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('/users/profile/')
        return render(request, self.template_name, {'form': UsernamePasswordLoginForm(), 'next': _safe_next(request)})

    def post(self, request):
        form = UsernamePasswordLoginForm(request.POST)
        if _check_rate_limit(_client_ip(request), max_requests=10, window=60, prefix='login'):
            form.add_error(None, "Juda ko'p urinish. Bir necha daqiqadan keyin qayta urinib ko'ring.")
            return render(request, self.template_name, {'form': form, 'next': _safe_next(request)})
        if form.is_valid():
            login(request, form.cleaned_data['user'], backend='django.contrib.auth.backends.ModelBackend')
            return redirect(_safe_next(request) or settings.LOGIN_REDIRECT_URL)
        return render(request, self.template_name, {'form': form, 'next': _safe_next(request)})


@method_decorator(user_passes_test(lambda u: u.is_staff or u.is_superuser), name='dispatch')
class AdminPanelView(LoginRequiredMixin, View):
    template_name = 'users/admin_panel.html'

    def _context(self, course_form=None, module_form=None, lesson_form=None, active_tab='bulk-create'):
        return {
            'course_form': course_form or CourseForm(prefix='course'),
            'module_form': module_form or ModuleForm(prefix='module'),
            'lesson_form': lesson_form or LessonForm(prefix='lesson'),
            'courses': Course.objects.prefetch_related('modules__lessons').all(),
            'active_tab': active_tab,
        }

    def get(self, request):
        return render(request, self.template_name, self._context())

    def post(self, request):
        if 'add_course' in request.POST:
            form = CourseForm(request.POST, request.FILES, prefix='course')
            if form.is_valid():
                form.save()
                messages.success(request, 'Course added successfully.')
                return redirect('users:admin_panel')
            return render(request, self.template_name, self._context(course_form=form, active_tab='course'))
        elif 'add_module' in request.POST:
            form = ModuleForm(request.POST, prefix='module')
            if form.is_valid():
                form.save()
                messages.success(request, 'Module added successfully.')
                return redirect('users:admin_panel')
            return render(request, self.template_name, self._context(module_form=form, active_tab='module'))
        elif 'add_lesson' in request.POST:
            form = LessonForm(request.POST, prefix='lesson')
            if form.is_valid():
                form.save()
                messages.success(request, 'Lesson added successfully.')
                return redirect('users:admin_panel')
            return render(request, self.template_name, self._context(lesson_form=form, active_tab='lesson'))
        return render(request, self.template_name, self._context())


@method_decorator(user_passes_test(lambda u: u.is_staff or u.is_superuser), name='dispatch')
class BulkCreateView(LoginRequiredMixin, View):

    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid JSON body.'}, status=400)

        course_title = data.get('title', '').strip()
        if not course_title:
            return JsonResponse({'success': False, 'error': 'Course title is required.'}, status=400)

        course_slug = data.get('slug', '').strip() or slugify(course_title)

        try:
            with transaction.atomic():
                course = Course.objects.create(
                    title=course_title,
                    slug=course_slug,
                    description=data.get('description', '').strip(),
                    order=int(data.get('order', 0)),
                )
                for m_data in data.get('modules', []):
                    m_title = m_data.get('title', '').strip()
                    if not m_title:
                        raise ValueError('Module title is required.')
                    module = Module.objects.create(
                        title=m_title,
                        slug=m_data.get('slug', '').strip() or slugify(m_title),
                        description=m_data.get('description', '').strip(),
                        course=course,
                        order=int(m_data.get('order', 0)),
                    )
                    for l_data in m_data.get('lessons', []):
                        l_title = l_data.get('title', '').strip()
                        if not l_title:
                            raise ValueError('Lesson title is required.')
                        Lesson.objects.create(
                            title=l_title,
                            slug=l_data.get('slug', '').strip() or slugify(l_title),
                            description=l_data.get('description', '').strip(),
                            module=module,
                            youtube_video_id=l_data.get('youtube_video_id', '').strip(),
                            order=int(l_data.get('order', 0)),
                        )
        except ValueError as exc:
            return JsonResponse({'success': False, 'error': str(exc)}, status=400)
        except Exception:
            return JsonResponse({'success': False, 'error': 'Ichki xatolik yuz berdi.'}, status=500)

        return JsonResponse({'success': True, 'course_id': course.pk})


@method_decorator(user_passes_test(lambda u: u.is_staff or u.is_superuser), name='dispatch')
class FetchPlaylistView(LoginRequiredMixin, View):

    _PATTERNS = [
        re.compile(r'[?&]list=([A-Za-z0-9_\-]+)'),
        re.compile(r'/playlist/([A-Za-z0-9_\-]+)'),
    ]

    def get(self, request):
        if not settings.YOUTUBE_API_KEY:
            return JsonResponse({'error': 'YOUTUBE_API_KEY is not configured.'}, status=503)

        raw_url = request.GET.get('url', '').strip()
        if not raw_url:
            return JsonResponse({'error': 'url parameter is required.'}, status=400)

        playlist_id = None
        for pat in self._PATTERNS:
            m = pat.search(raw_url)
            if m:
                playlist_id = m.group(1)
                break
        if not playlist_id:
            return JsonResponse({'error': 'Could not extract playlist ID from URL.'}, status=400)

        try:
            resp = http_requests.get(
                'https://www.googleapis.com/youtube/v3/playlistItems',
                params={'part': 'snippet', 'maxResults': 50,
                        'playlistId': playlist_id, 'key': settings.YOUTUBE_API_KEY},
                timeout=10,
            )
            resp.raise_for_status()
            items = resp.json().get('items', [])
        except http_requests.exceptions.Timeout:
            return JsonResponse({'error': 'YouTube API request timed out.'}, status=504)
        except http_requests.exceptions.RequestException as exc:
            return JsonResponse({'error': f'YouTube API error: {exc}'}, status=502)

        results = []
        for item in items:
            snippet = item.get('snippet', {})
            thumbs = snippet.get('thumbnails', {})
            results.append({
                'title': snippet.get('title', ''),
                'video_id': snippet.get('resourceId', {}).get('videoId', ''),
                'description': snippet.get('description', ''),
                'position': snippet.get('position', 0),
                'thumbnail': (thumbs.get('medium') or thumbs.get('default') or {}).get('url', ''),
            })

        playlist_title = ''
        try:
            title_resp = http_requests.get(
                'https://www.googleapis.com/youtube/v3/playlists',
                params={'part': 'snippet', 'id': playlist_id, 'key': settings.YOUTUBE_API_KEY},
                timeout=10,
            )
            title_resp.raise_for_status()
            pl_items = title_resp.json().get('items', [])
            if pl_items:
                playlist_title = pl_items[0].get('snippet', {}).get('title', '')
        except http_requests.exceptions.RequestException:
            pass

        return JsonResponse({'playlist_title': playlist_title, 'items': results})
