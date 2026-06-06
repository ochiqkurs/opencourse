import re

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

USERNAME_RE = re.compile(r'^[a-z0-9_]{3,30}$')


class UserProfileForm(forms.ModelForm):
    """
    Safe user profile form that only allows editing of non-sensitive fields.
    Excludes: password, is_staff, is_active, is_superuser, date_joined, last_login, groups, user_permissions.
    """
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Username',
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'First name',
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Last name',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Email',
            }),
        }

    def clean_username(self):
        value = self.cleaned_data['username'].strip()
        if User.objects.filter(username=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Bu username band.")
        return value


class SetUsernamePasswordForm(forms.Form):
    """Lets a Telegram-authenticated user pick a username + password so they can
    log in without Telegram. Named to avoid a clash with Django's SetPasswordForm."""

    username = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={'class': 'form-input', 'autocapitalize': 'none'}),
    )
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-input'}))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-input'}))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_username(self):
        value = self.cleaned_data['username'].strip().lower()
        if not USERNAME_RE.match(value):
            raise forms.ValidationError(
                "Username 3–30 ta belgidan iborat bo'lib, faqat kichik harf, "
                "raqam va pastki chiziq (_) ishlatishi mumkin."
            )
        if User.objects.filter(username=value).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("Bu username band.")
        return value

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2:
            if p1 != p2:
                self.add_error('password2', "Parollar mos kelmadi.")
            else:
                try:
                    validate_password(p1, self.user)
                except forms.ValidationError as exc:
                    self.add_error('password1', exc)
        return cleaned


class UsernamePasswordLoginForm(forms.Form):
    """Username + password login for users who have set a password."""

    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-input', 'autocapitalize': 'none', 'autofocus': True}),
    )
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-input'}))

    def clean(self):
        cleaned = super().clean()
        # Passwords are only ever set via SetUsernamePasswordForm, which stores the
        # username lowercased. Lowercase here too so casing never blocks a valid login.
        username = (cleaned.get('username') or '').strip().lower()
        cleaned['username'] = username
        password = cleaned.get('password')
        if username and password:
            user = authenticate(username=username, password=password)
            if user is None:
                existing = User.objects.filter(username=username).first()
                if existing is not None and not existing.has_usable_password():
                    raise forms.ValidationError(
                        "Bu hisob hali parol bilan kirishga sozlanmagan. Telegram orqali "
                        "kiring va profilingizda parol o'rnating."
                    )
                raise forms.ValidationError("Username yoki parol noto'g'ri.")
            cleaned['user'] = user
        return cleaned
