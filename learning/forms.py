from django import forms
from django.utils.text import slugify
from .models import Course, Module, Lesson


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['title', 'slug', 'description', 'thumbnail', 'order']
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
        fields = ['title', 'slug', 'description', 'module', 'youtube_video_id', 'order']
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
