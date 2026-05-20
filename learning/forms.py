from django import forms
from django.utils.text import slugify
from .models import (
    Course, Module, Lesson, CourseReview, Category,
    LessonQuestion, LessonAnswer,
)


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = [
            'title', 'slug', 'subtitle', 'description', 'thumbnail',
            'category', 'level', 'language', 'instructor_name',
            'instructor_bio', 'what_you_learn', 'requirements',
            'is_featured', 'order',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'instructor_bio': forms.Textarea(attrs={'rows': 2}),
            'what_you_learn': forms.Textarea(attrs={'rows': 4, 'placeholder': "Bir qatorga bitta band"}),
            'requirements': forms.Textarea(attrs={'rows': 3, 'placeholder': "Bir qatorga bitta talab"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('slug') and cleaned_data.get('title'):
            cleaned_data['slug'] = slugify(cleaned_data['title'])
        return cleaned_data


class ModuleForm(forms.ModelForm):
    class Meta:
        model = Module
        fields = ['title', 'slug', 'description', 'course', 'order']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('slug') and cleaned_data.get('title'):
            cleaned_data['slug'] = slugify(cleaned_data['title'])
        return cleaned_data


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ['title', 'slug', 'description', 'module', 'lesson_type', 'content',
                  'youtube_video_id', 'is_preview', 'order']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'content': forms.Textarea(attrs={'rows': 15, 'placeholder': 'Markdown formatida yozing...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('slug') and cleaned_data.get('title'):
            cleaned_data['slug'] = slugify(cleaned_data['title'])
        return cleaned_data


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'slug', 'description', 'icon', 'color', 'order']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('slug') and cleaned_data.get('name'):
            cleaned_data['slug'] = slugify(cleaned_data['name'])
        return cleaned_data


class LessonQuestionForm(forms.ModelForm):
    class Meta:
        model = LessonQuestion
        fields = ['title', 'body']
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': "Savolingiz nima haqida?", 'maxlength': 200}),
            'body': forms.Textarea(attrs={'rows': 3, 'placeholder': "Batafsil tushuntiring (ixtiyoriy)..."}),
        }


class LessonAnswerForm(forms.ModelForm):
    class Meta:
        model = LessonAnswer
        fields = ['body']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 3, 'placeholder': "Javobingizni yozing..."}),
        }


class CourseReviewForm(forms.ModelForm):
    rating = forms.IntegerField(
        min_value=1, max_value=5,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = CourseReview
        fields = ['rating', 'comment']
        widgets = {
            'comment': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': "Kurs haqida fikringizni yozing...",
                'class': 'review-textarea',
            }),
        }
