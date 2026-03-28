from django.conf import settings
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Course(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=120)
    description = models.TextField(blank=True)
    thumbnail = models.ImageField(upload_to='course_thumbnails/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        indexes = [
            models.Index(fields=['slug']),
        ]

    def __str__(self):
        return self.title

    def get_thumbnail_url(self):
        """Return manual thumbnail if uploaded, else first lesson's YouTube thumbnail."""
        if self.thumbnail:
            return self.thumbnail.url
        first_lesson = (
            Lesson.objects
            .filter(module__course=self)
            .order_by('module__order', 'order')
            .values_list('youtube_video_id', flat=True)
            .first()
        )
        if first_lesson:
            return f'https://img.youtube.com/vi/{first_lesson}/hqdefault.jpg'
        return None


class Module(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=120)
    description = models.TextField(blank=True)
    course = models.ForeignKey(
        Course,
        related_name='modules',
        on_delete=models.CASCADE,
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        unique_together = [('course', 'slug')]
        indexes = [
            models.Index(fields=['course', 'order']),
        ]

    def __str__(self):
        return f"{self.course.title} > {self.title}"


class Lesson(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=120)
    description = models.TextField(blank=True)
    module = models.ForeignKey(
        Module,
        related_name='lessons',
        on_delete=models.CASCADE,
    )
    youtube_video_id = models.CharField(max_length=20)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        unique_together = [('module', 'slug')]
        indexes = [
            models.Index(fields=['module', 'order']),
        ]

    def __str__(self):
        return f"{self.module.title} – {self.title}"


class LessonProgress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE)
    is_completed = models.BooleanField(default=False)
    watched_seconds = models.PositiveIntegerField(default=0)
    last_watched_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'lesson')]

    def __str__(self):
        status = "done" if self.is_completed else "in progress"
        return f"{self.user.username} – {self.lesson.title} ({status})"


class VideoSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='video_sessions')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='video_sessions')
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    last_position_seconds = models.PositiveIntegerField(default=0)
    actual_watched_seconds = models.PositiveIntegerField(default=0)
    max_reached_seconds = models.PositiveIntegerField(default=0)
    last_play_position = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'lesson', 'ended_at'])]

    def __str__(self):
        return f"{self.user.username} – {self.lesson.title} (session {self.id})"


class VideoEvent(models.Model):
    EVENT_TYPES = [
        ('play', 'play'),
        ('pause', 'pause'),
        ('seek', 'seek'),
        ('ended', 'ended'),
        ('speed_change', 'speed_change'),
        ('page_hidden', 'page_hidden'),
        ('heartbeat', 'heartbeat'),
    ]
    session = models.ForeignKey(VideoSession, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    position_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.event_type} at {self.position_seconds}s (session {self.session_id})"


class Note(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notes',
    )
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name='notes',
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'lesson')]
        indexes = [
            models.Index(fields=['user', 'lesson']),
        ]

    def __str__(self):
        return f"{self.user.username} – note for {self.lesson.title}"
