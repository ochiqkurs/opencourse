from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from django.urls import path, include
from learning.sitemaps import SITEMAPS
from learning.views import HomeView
from users.views import (
    TelegramConfirmView, CheckTokenView, IssueCodeView, BotStartView,
    ContactsListView, MarkBlockedView,
)


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /api/",
        "Disallow: /users/",
        "Allow: /",
        "",
        f"Sitemap: {settings.SITE_URL.rstrip('/')}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


urlpatterns = [
    path('admin/', admin.site.urls),
    path('users/', include('users.urls')),
    path('malaka/', include('learning.urls')),
    path('api/auth/confirm/', TelegramConfirmView.as_view()),
    path('api/auth/issue-code/', IssueCodeView.as_view(), name='issue_code'),
    path('api/auth/check/<str:token>/', CheckTokenView.as_view()),
    path('api/telemetry/bot-start/', BotStartView.as_view(), name='bot_start'),
    path('api/telemetry/contacts/', ContactsListView.as_view(), name='bot_contacts'),
    path('api/telemetry/mark-blocked/', MarkBlockedView.as_view(), name='bot_mark_blocked'),
    path('sitemap.xml', sitemap, {'sitemaps': SITEMAPS}, name='sitemap'),
    path('robots.txt', robots_txt, name='robots'),
    path('', HomeView.as_view(), name='home'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
