import secrets
from django.conf import settings
from django.db import models
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count

User = get_user_model()


class Category(models.Model):
    name = models.CharField(max_length=80)
    slug = models.SlugField(unique=True, max_length=80)
    description = models.CharField(max_length=255, blank=True)
    icon = models.CharField(
        max_length=40,
        blank=True,
        help_text="Lucide icon name (e.g. 'code', 'book-open', 'palette')",
    )
    color = models.CharField(
        max_length=20,
        blank=True,
        help_text="Tailwind-ish accent color name (emerald, amber, sky, rose, violet, slate)",
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Course(models.Model):
    LEVEL_CHOICES = [
        ('beginner', "Boshlang'ich"),
        ('intermediate', "O'rta"),
        ('advanced', "Yuqori"),
        ('all', 'Hamma uchun'),
    ]

    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=120)
    subtitle = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    thumbnail = models.ImageField(upload_to='course_thumbnails/', blank=True, null=True)
    order = models.PositiveIntegerField(default=0)

    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='courses',
    )
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='all')
    language = models.CharField(max_length=40, default="O'zbek")
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='taught_courses',
    )
    instructor_name = models.CharField(max_length=120, blank=True)
    instructor_bio = models.TextField(blank=True)
    what_you_learn = models.TextField(
        blank=True,
        help_text="Bir qatorga bitta bandni yozing.",
    )
    requirements = models.TextField(
        blank=True,
        help_text="Bir qatorga bitta talabni yozing.",
    )
    is_featured = models.BooleanField(default=False)
    avg_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['category', 'order']),
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

    @property
    def what_you_learn_list(self):
        return [line.strip() for line in (self.what_you_learn or '').splitlines() if line.strip()]

    @property
    def requirements_list(self):
        return [line.strip() for line in (self.requirements or '').splitlines() if line.strip()]

    def instructor_display(self):
        if self.instructor_name:
            return self.instructor_name
        if self.instructor:
            full = (self.instructor.first_name + ' ' + self.instructor.last_name).strip()
            return full or self.instructor.username
        return "Ochiq kurs jamoasi"

    def update_rating(self):
        agg = self.reviews.aggregate(avg=Avg('rating'), c=Count('id'))
        self.avg_rating = round(agg['avg'] or 0, 2)
        self.rating_count = agg['c'] or 0
        self.save(update_fields=['avg_rating', 'rating_count'])


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
    is_preview = models.BooleanField(default=False)

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
    last_watched_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'lesson')]

    def __str__(self):
        status = "done" if self.is_completed else "in progress"
        return f"{self.user.username} – {self.lesson.title} ({status})"


class LessonView(models.Model):
    """One row per (user, lesson, day) — driven by 'video started playing' on the lesson page.

    This is the single source of truth for the activity graph and streak.
    Multiple plays of the same lesson on the same day collapse into one row.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lesson_views')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='views')
    viewed_on = models.DateField()
    first_seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'lesson', 'viewed_on')]
        indexes = [
            models.Index(fields=['user', 'viewed_on']),
            models.Index(fields=['user', 'lesson']),
        ]

    def __str__(self):
        return f"{self.user.username} → {self.lesson.title} on {self.viewed_on}"


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


class Enrollment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='enrollments')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'course')]
        indexes = [models.Index(fields=['user', 'course'])]

    def __str__(self):
        return f"{self.user.username} → {self.course.title}"


class CourseReview(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='course_reviews')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'course')]
        ordering = ['-created_at']
        indexes = [models.Index(fields=['course', '-created_at'])]

    def __str__(self):
        return f"{self.user.username} → {self.course.title} ({self.rating}★)"


def _generate_cert_code():
    return secrets.token_urlsafe(10)


class Certificate(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='certificates')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='certificates')
    issued_at = models.DateTimeField(auto_now_add=True)
    code = models.CharField(max_length=32, unique=True, default=_generate_cert_code)

    class Meta:
        unique_together = [('user', 'course')]
        ordering = ['-issued_at']

    def __str__(self):
        return f"Cert {self.code} – {self.user.username} / {self.course.title}"


class Wishlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlist_items')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='wishlisted_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'course')]
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', '-created_at'])]

    def __str__(self):
        return f"{self.user.username} ♥ {self.course.title}"


class LessonResource(models.Model):
    KIND_CHOICES = [
        ('link', 'Havola'),
        ('file', 'Fayl'),
        ('code', 'Kod'),
        ('doc',  'Hujjat'),
    ]
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='resources')
    title = models.CharField(max_length=180)
    url = models.URLField(max_length=500)
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, default='link')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.lesson.title} → {self.title}"


class LessonQuestion(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='questions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='lesson_questions')
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['lesson', '-created_at'])]

    def __str__(self):
        return f"Q: {self.title[:40]}"


class LessonAnswer(models.Model):
    question = models.ForeignKey(LessonQuestion, on_delete=models.CASCADE, related_name='answers')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='lesson_answers')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_instructor = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']
        indexes = [models.Index(fields=['question', 'created_at'])]

    def __str__(self):
        return f"A by {self.user.username} on {self.question_id}"


class Announcement(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField()
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name='announcements',
        null=True, blank=True,
        help_text='Bo\'sh qoldirilsa — global e\'lon (barcha kurslar uchun).',
    )
    is_pinned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_pinned', '-created_at']
        indexes = [models.Index(fields=['course', '-created_at'])]

    def __str__(self):
        scope = self.course.title if self.course else 'Global'
        return f"[{scope}] {self.title}"
