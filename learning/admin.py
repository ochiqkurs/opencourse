from django.contrib import admin
from django.utils import timezone
from .models import (
    Lesson, LessonProgress, LessonView, Note, Course, Module,
    Category, Enrollment, CourseReview, Certificate,
    Wishlist, LessonResource, LessonQuestion, LessonAnswer, Announcement,
    Quiz, QuizQuestion, QuizChoice, QuizAttempt, QuizAnswer,
    LearningPath, LearningPathCourse, LearningPathEnrollment,
    LearningPathCertificate, VideoBookmark,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'order']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['order']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'level', 'status', 'is_featured', 'avg_rating', 'rating_count', 'order']
    list_filter = ['status', 'category', 'level', 'is_featured']
    search_fields = ['title', 'subtitle']
    prepopulated_fields = {'slug': ('title',)}
    ordering = ['order']
    actions = ['make_published', 'make_draft', 'make_archived']

    def make_published(self, request, queryset):
        queryset.update(status='published', published_at=timezone.now())
    make_published.short_description = "Tanlangan kurslarni nashr qilish"

    def make_draft(self, request, queryset):
        queryset.update(status='draft')
    make_draft.short_description = "Tanlangan kurslarni qoralama holatiga o'tkazish"

    def make_archived(self, request, queryset):
        queryset.update(status='archived')
    make_archived.short_description = "Tanlangan kurslarni arxivlash"


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ['title', 'course', 'order']
    list_filter = ['course']
    search_fields = ['title']
    prepopulated_fields = {'slug': ('title',)}
    ordering = ['course', 'order']


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ['title', 'module', 'lesson_type', 'is_preview', 'order']
    list_filter = ['module', 'lesson_type', 'is_preview']
    search_fields = ['title']
    prepopulated_fields = {'slug': ('title',)}
    ordering = ['module', 'order']


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ['user', 'lesson', 'is_completed', 'last_watched_at']
    list_filter = ['is_completed']
    search_fields = ['user__username', 'lesson__title']
    readonly_fields = ['last_watched_at']


@admin.register(LessonView)
class LessonViewAdmin(admin.ModelAdmin):
    list_display = ['user', 'lesson', 'viewed_on', 'first_seen_at']
    list_filter = ['viewed_on']
    search_fields = ['user__username', 'lesson__title']
    date_hierarchy = 'viewed_on'
    readonly_fields = ['first_seen_at']


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ['user', 'lesson', 'updated_at']
    list_filter = ['lesson__module__course']
    search_fields = ['user__username', 'lesson__title']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ['user', 'course', 'enrolled_at']
    list_filter = ['course']
    search_fields = ['user__username', 'course__title']


@admin.register(CourseReview)
class CourseReviewAdmin(admin.ModelAdmin):
    list_display = ['user', 'course', 'rating', 'created_at']
    list_filter = ['rating', 'course']
    search_fields = ['user__username', 'course__title']


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = ['code', 'user', 'course', 'issued_at']
    search_fields = ['code', 'user__username', 'course__title']


@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ['user', 'course', 'created_at']
    search_fields = ['user__username', 'course__title']


@admin.register(LessonResource)
class LessonResourceAdmin(admin.ModelAdmin):
    list_display = ['lesson', 'title', 'kind', 'order']
    list_filter = ['kind']
    search_fields = ['title', 'lesson__title']


@admin.register(LessonQuestion)
class LessonQuestionAdmin(admin.ModelAdmin):
    list_display = ['title', 'lesson', 'user', 'is_resolved', 'created_at']
    list_filter = ['is_resolved']
    search_fields = ['title', 'body', 'user__username']


@admin.register(LessonAnswer)
class LessonAnswerAdmin(admin.ModelAdmin):
    list_display = ['question', 'user', 'is_instructor', 'created_at']
    list_filter = ['is_instructor']


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ['title', 'course', 'is_pinned', 'created_at']
    list_filter = ['is_pinned', 'course']
    search_fields = ['title', 'body']


# ── Quiz Models ──

class QuizQuestionInline(admin.TabularInline):
    model = QuizQuestion
    extra = 1
    fields = ['order', 'question_type', 'text', 'explanation']
    ordering = ['order']


class QuizChoiceInline(admin.TabularInline):
    model = QuizChoice
    extra = 2
    fields = ['order', 'text', 'is_correct']
    ordering = ['order']


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ['title', 'lesson', 'pass_percent', 'max_attempts', 'created_at']
    list_filter = ['lesson__module__course']
    search_fields = ['title', 'lesson__title']
    inlines = [QuizQuestionInline]


@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ['quiz', 'question_type', 'order', 'text_preview']
    list_filter = ['question_type']
    inlines = [QuizChoiceInline]

    def text_preview(self, obj):
        return obj.text[:80]
    text_preview.short_description = 'Savol'


@admin.register(QuizChoice)
class QuizChoiceAdmin(admin.ModelAdmin):
    list_display = ['question', 'text', 'is_correct', 'order']


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ['user', 'quiz', 'score', 'passed', 'completed_at']
    list_filter = ['passed']


@admin.register(QuizAnswer)
class QuizAnswerAdmin(admin.ModelAdmin):
    list_display = ['attempt', 'question', 'is_correct']


# ── Learning Path Models ──

@admin.register(LearningPath)
class LearningPathAdmin(admin.ModelAdmin):
    list_display = ['title', 'order', 'is_featured', 'created_at']
    prepopulated_fields = {'slug': ('title',)}


@admin.register(LearningPathCourse)
class LearningPathCourseAdmin(admin.ModelAdmin):
    list_display = ['path', 'course', 'order']


@admin.register(LearningPathEnrollment)
class LearningPathEnrollmentAdmin(admin.ModelAdmin):
    list_display = ['user', 'path', 'enrolled_at']


@admin.register(LearningPathCertificate)
class LearningPathCertificateAdmin(admin.ModelAdmin):
    list_display = ['code', 'user', 'path', 'issued_at']


# ── Video Bookmark ──

@admin.register(VideoBookmark)
class VideoBookmarkAdmin(admin.ModelAdmin):
    list_display = ['user', 'lesson', 'timestamp_seconds', 'created_at']
    list_filter = ['lesson__module__course']
