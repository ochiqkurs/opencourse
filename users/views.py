import json
import re
import requests as http_requests
from django.conf import settings
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from learning.models import (
    Course, Module, Lesson, LessonProgress, LessonView,
    Enrollment, Certificate, Category,
)
from learning.forms import CourseForm, ModuleForm, LessonForm, CategoryForm
from .forms import (
    UserProfileForm, SetUsernamePasswordForm, UsernamePasswordLoginForm,
)
from .models import TelegramAuthToken, TelegramProfile


def _client_ip(request):
    return (
        request.META.get('HTTP_X_FORWARDED_FOR', '') or
        request.META.get('REMOTE_ADDR', '')
    ).split(',')[0].strip()


def _check_rate_limit(ip, max_requests=60, window=60, prefix='check'):
    """Fixed-window rate limiter using Django cache. Returns True if limit exceeded."""
    key = f'rl:{prefix}:{ip}'
    cache.add(key, 0, window)
    count = cache.incr(key)
    return count > max_requests


class TelegramLoginView(View):
    """Generates a one-time token and shows the Telegram auth page."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('/users/profile/')
        auth_token = TelegramAuthToken.generate()
        bot_username = getattr(settings, 'TELEGRAM_BOT_USERNAME', 'ochiqkurs_bot')
        bot_url = f'https://t.me/{bot_username}?start={auth_token.token}'
        return render(request, 'registration/login.html', {
            'bot_url': bot_url,
            'token': auth_token.token,
            'short_code': auth_token.short_code,
            'bot_username': bot_username,
        })


# Signup is the same Telegram-based flow as login.
class SignupView(TelegramLoginView):
    pass


@method_decorator(csrf_exempt, name='dispatch')
class TelegramConfirmView(View):
    """Called by the Telegram bot after user presses Start."""

    def post(self, request):
        secret = request.headers.get('X-Bot-Secret', '')
        if secret != settings.BOT_SECRET:
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

        with transaction.atomic():
            try:
                profile = TelegramProfile.objects.select_related('user').get(telegram_id=telegram_id)
                user = profile.user
            except TelegramProfile.DoesNotExist:
                chosen_username = (
                    username
                    if username and not User.objects.filter(username=username).exists()
                    else f'tg_{telegram_id}'
                )
                user = User.objects.create(
                    username=chosen_username,
                    first_name=first_name,
                    last_name=last_name,
                )
                user.set_unusable_password()
                user.save(update_fields=['username', 'first_name', 'last_name', 'password'])
                profile = TelegramProfile(user=user, telegram_id=telegram_id)
                auth_token.is_new_user = True

            profile.first_name = first_name
            profile.last_name = last_name
            profile.username = username
            profile.photo_url = photo_url
            profile.save()

            if not auth_token.is_new_user:
                user.first_name = first_name
                user.last_name = last_name
                user.save(update_fields=['first_name', 'last_name'])

            auth_token.user = user
            auth_token.confirmed_at = timezone.now()
            auth_token.save()

        return JsonResponse({'status': 'ok'})


@method_decorator(csrf_exempt, name='dispatch')
class ResolveCodeView(View):
    """Called by the Telegram bot to exchange a 6-digit login code for the full token.
    Gated by the same X-Bot-Secret check as TelegramConfirmView."""

    def post(self, request):
        secret = request.headers.get('X-Bot-Secret', '')
        if secret != settings.BOT_SECRET:
            return JsonResponse({'error': 'Forbidden'}, status=403)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        code = re.sub(r'\D', '', data.get('short_code', ''))
        if len(code) != 6:
            return JsonResponse({'error': 'not_found'}, status=404)

        # A code may be reused by a new token after the old one expires, so pick the latest.
        auth_token = (
            TelegramAuthToken.objects.filter(short_code=code).order_by('-created_at').first()
        )
        if auth_token is None:
            return JsonResponse({'error': 'not_found'}, status=404)

        if not auth_token.is_valid():
            return JsonResponse({'error': 'expired'}, status=410)

        return JsonResponse({'token': auth_token.token})


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
            login(request, auth_token.user)
            redirect_url = '/users/profile/' if auth_token.is_new_user else '/'
            return JsonResponse({'status': 'confirmed', 'redirect': redirect_url})

        return JsonResponse({'status': 'pending'})


class ProfileView(LoginRequiredMixin, View):
    template_name = 'users/profile.html'

    def _base_context(self, request):
        from datetime import timedelta, date
        from django.db.models import Count
        from users.models import UserProfile

        user = request.user

        user_lesson_views = LessonView.objects.filter(user=user).count()

        # Activity graph — last 365 days, counting distinct lessons watched per day.
        since = date.today() - timedelta(days=364)
        raw_activity = (
            LessonView.objects
            .filter(user=user, viewed_on__gte=since)
            .values('viewed_on')
            .annotate(lessons=Count('lesson', distinct=True))
        )
        activity_map = {
            str(row['viewed_on']): row['lessons']
            for row in raw_activity
        }

        today = date.today()
        # 364 kun oldindan boshlab bugunga qadar
        days = [today - timedelta(days=i) for i in range(364, -1, -1)]

        # Boshini dushanbaga to'ldirish — None emas, balki alohida flag
        start_weekday = days[0].weekday()  # 0=Dushanba, 6=Yakshanba
        padded = [None] * start_weekday + days

        # Haftalar ro'yxatiga bo'lish
        weeks = [padded[i:i+7] for i in range(0, len(padded), 7)]

        profile, _ = UserProfile.objects.get_or_create(user=user)

        # In-progress courses
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

        in_progress_courses = []
        for cid, data in course_data.items():
            course = data['course']
            lessons = list(
                Lesson.objects
                .filter(module__course=course)
                .select_related('module')
                .order_by('module__order', 'order')
            )
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

        certificates = list(
            Certificate.objects.filter(user=user)
            .select_related('course')
            .order_by('-issued_at')
        )

        return {
            'form': UserProfileForm(instance=user),
            'is_admin': user.is_staff or user.is_superuser,
            'user': user,
            'user_lesson_views': user_lesson_views,
            'user_completed_lessons': LessonProgress.objects.filter(user=user, is_completed=True).count(),
            'has_usable_password': user.has_usable_password(),
            'password_form': PasswordChangeForm(user) if user.has_usable_password() else SetPasswordForm(user),
            'activity_map': activity_map,
            'weeks': weeks,
            'current_streak': profile.current_streak,
            'longest_streak': profile.longest_streak,
            'in_progress_courses': in_progress_courses,
            'certificates': certificates,
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
                messages.success(request, 'Profile updated successfully.')
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
        return render(request, self.template_name, {'form': UsernamePasswordLoginForm()})

    def post(self, request):
        form = UsernamePasswordLoginForm(request.POST)
        if _check_rate_limit(_client_ip(request), max_requests=10, window=60, prefix='login'):
            form.add_error(None, "Juda ko'p urinish. Bir necha daqiqadan keyin qayta urinib ko'ring.")
            return render(request, self.template_name, {'form': form})
        if form.is_valid():
            login(request, form.cleaned_data['user'])
            return redirect(settings.LOGIN_REDIRECT_URL)
        return render(request, self.template_name, {'form': form})


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
        except Exception as exc:
            return JsonResponse({'success': False, 'error': f'Database error: {exc}'}, status=500)

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
