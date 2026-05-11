from django.contrib import admin
from .models import (
    Lesson, LessonProgress, Note, Course, Module,
    Category, Enrollment, CourseReview, Certificate,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'order']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['order']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'level', 'is_featured', 'avg_rating', 'rating_count', 'order']
    list_filter = ['category', 'level', 'is_featured']
    search_fields = ['title', 'subtitle']
    prepopulated_fields = {'slug': ('title',)}
    ordering = ['order']


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ['title', 'course', 'order']
    list_filter = ['course']
    search_fields = ['title']
    prepopulated_fields = {'slug': ('title',)}
    ordering = ['course', 'order']


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ['title', 'module', 'is_preview', 'order']
    list_filter = ['module', 'is_preview']
    search_fields = ['title']
    prepopulated_fields = {'slug': ('title',)}
    ordering = ['module', 'order']


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ['user', 'lesson', 'is_completed', 'watched_seconds', 'last_watched_at']
    list_filter = ['is_completed']
    search_fields = ['user__username', 'lesson__title']
    readonly_fields = ['last_watched_at']


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
