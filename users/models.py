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
        """6-digit numeric code, unique among currently valid (unexpired, unconfirmed) tokens."""
        cutoff = timezone.now() - timedelta(minutes=10)
        code = ''.join(secrets.choice('0123456789') for _ in range(6))
        for _ in range(10):
            clash = cls.objects.filter(
                short_code=code,
                confirmed_at__isnull=True,
                created_at__gt=cutoff,
            ).exists()
            if not clash:
                break
            code = ''.join(secrets.choice('0123456789') for _ in range(6))
        return code

    @classmethod
    def generate(cls):
        token = secrets.token_hex(32)  # 64 hex chars
        return cls.objects.create(token=token, short_code=cls._generate_short_code())


class TelegramProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='telegram_profile')
    telegram_id = models.BigIntegerField(unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    username = models.CharField(max_length=100, blank=True)
    photo_url = models.URLField(blank=True)

    def __str__(self):
        return f'TelegramProfile({self.telegram_id})'
