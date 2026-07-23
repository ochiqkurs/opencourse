from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from django.urls import path, include
from learning.sitemaps import SITEMAPS
from learning.views import HomeView, llms_txt
from users.views import (
    TelegramConfirmView, CheckTokenView, IssueCodeView, BotStartView,
    ContactsListView, MarkBlockedView,
)


# AI assistant/search crawlers we explicitly welcome (GEO). `User-agent: *`
# already allows them, but a named group is a durable, declarative signal that
# survives future edits to the wildcard rules.
AI_CRAWLERS = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User",
    "ClaudeBot", "Claude-User", "Claude-SearchBot",
    "PerplexityBot", "Perplexity-User",
    "Google-Extended", "Applebot-Extended",
    "meta-externalagent", "CCBot", "DuckAssistBot", "Amazonbot",
]


def robots_txt(request):
    # Only /admin/ is Disallowed. /users/ and /api/ are intentionally left
    # crawlable so Google can read the X-Robots-Tag: noindex header
    # (NoindexMiddleware) and drop them from the index — Disallowing them would
    # block crawling but not indexing, causing "Indexed, though blocked by
    # robots.txt" for site-wide-linked URLs like /users/login/.
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Allow: /",
        "",
    ]
    for bot in AI_CRAWLERS:
        lines += [f"User-agent: {bot}", "Disallow: /admin/", "Allow: /", ""]
    lines.append(f"Sitemap: {settings.SITE_URL.rstrip('/')}/sitemap.xml")
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def google_verification_file(request):
    # Google Search Console "HTML file" verification: serve the expected body at
    # the filename Google issued (configured via GOOGLE_VERIFICATION_FILE).
    name = settings.GOOGLE_VERIFICATION_FILE
    return HttpResponse(f"google-site-verification: {name}\n", content_type="text/html")


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
    path('llms.txt', llms_txt, name='llms'),
    path('', HomeView.as_view(), name='home'),
]

# Serve the Google Search Console HTML verification file at the site root when a
# filename is configured (keeps the token out of source).
if settings.GOOGLE_VERIFICATION_FILE:
    urlpatterns.insert(
        -1, path(settings.GOOGLE_VERIFICATION_FILE, google_verification_file)
    )

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
