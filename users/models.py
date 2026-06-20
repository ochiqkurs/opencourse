import secrets
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_activity_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} profile"

    @property
    def live_streak(self):
        """Streak that has not lapsed.

        `current_streak` is only bumped when activity happens, so a stored value
        of e.g. 5 keeps showing even after the user has been away for a week. A
        streak is still alive only if the last activity was today or yesterday
        (Asia/Tashkent); otherwise it has been broken and the live value is 0.
        """
        if not self.last_activity_date:
            return 0
        gap = (timezone.localdate() - self.last_activity_date).days
        return self.current_streak if gap <= 1 else 0


class TelegramAuthToken(models.Model):
    token = models.CharField(max_length=64, unique=True)
    short_code = models.CharField(max_length=6, db_index=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    is_new_user = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=10)

    def is_valid(self):
        return not self.is_expired() and self.confirmed_at is None

    def __str__(self):
        return self.token

    @classmethod
    def _generate_short_code(cls):
        """6-digit numeric code, unique among tokens issued within the last 10 minutes."""
        cutoff = timezone.now() - timedelta(minutes=10)
        for _ in range(20):
            code = ''.join(secrets.choice('0123456789') for _ in range(6))
            if not cls.objects.filter(short_code=code, created_at__gt=cutoff).exists():
                return code
        raise RuntimeError('Failed to generate a unique short code after 20 attempts')

    @classmethod
    def generate(cls):
        """Create a pending browser-flow token (used by the bot-link login)."""
        token = secrets.token_hex(32)  # 64 hex chars
        return cls.objects.create(token=token)

    @classmethod
    def issue_for_user(cls, user, is_new_user):
        """Create a pre-confirmed token with a short code for the bot-issued code flow.

        The token is consumed by deletion when the user enters the code on the website.
        """
        return cls.objects.create(
            token=secrets.token_hex(32),
            short_code=cls._generate_short_code(),
            user=user,
            is_new_user=is_new_user,
            confirmed_at=timezone.now(),
        )


class TelegramProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='telegram_profile')
    telegram_id = models.BigIntegerField(unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    username = models.CharField(max_length=100, blank=True)
    photo_url = models.URLField(blank=True)

    def __str__(self):
        return f'TelegramProfile({self.telegram_id})'


class TelegramContact(models.Model):
    """Anyone who has pressed /start on the bot — even without completing login.

    Populated by the bot's fire-and-forget POST to /api/telemetry/bot-start/.
    Distinct from TelegramProfile, which only exists once a user actually
    authenticates. Used for funnel metrics (start → login) and as a broadcast
    list — `chat_id` is what a broadcast would target.
    """
    telegram_id = models.BigIntegerField(unique=True)
    chat_id = models.BigIntegerField(null=True, blank=True)
    username = models.CharField(max_length=100, blank=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    language_code = models.CharField(max_length=12, blank=True)
    # Sticky: True once this contact has ever arrived via a site deep-link token.
    came_with_token = models.BooleanField(default=False)
    start_count = models.PositiveIntegerField(default=0)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'TelegramContact({self.telegram_id})'
