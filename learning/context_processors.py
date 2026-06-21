"""SEO context processor — exposes default meta/OG values, the canonical URL,
and verification/analytics tokens to every template. Views can override the
per-page values (meta_description, og_title, og_image, og_type) by putting the
same keys in their own context."""
from django.conf import settings
from django.templatetags.static import static

# Default site-wide description (kept in sync with the historical static tag).
DEFAULT_DESCRIPTION = (
    "O'zbek tilidagi premium onlayn kurslar. Dasturlash, dizayn, ish hayoti va "
    "boshqa ko'plab yo'nalishlar bo'yicha bepul video darslar."
)
DEFAULT_TITLE = "Ochiq Kurs — O'zbekcha onlayn ta'lim platformasi"


def absolute_url(path):
    """Turn a relative path (e.g. /media/x.jpg) into an absolute URL under
    SITE_URL. Leaves already-absolute URLs (http/https, e.g. YouTube thumbs)
    untouched."""
    if not path:
        return ''
    if path.startswith(('http://', 'https://', '//')):
        return path
    return settings.SITE_URL.rstrip('/') + '/' + path.lstrip('/')


def seo(request):
    return {
        'SITE_URL': settings.SITE_URL,
        'canonical_url': absolute_url(request.path),
        'meta_description': DEFAULT_DESCRIPTION,
        'og_title': DEFAULT_TITLE,
        'og_image': absolute_url(static('images/course-hero-placeholder.png')),
        # Fallback used by the template when a view sets an empty og_image
        # (e.g. a course/path with no thumbnail).
        'default_og_image': absolute_url(static('images/course-hero-placeholder.png')),
        'og_type': 'website',
        'GOOGLE_SITE_VERIFICATION': settings.GOOGLE_SITE_VERIFICATION,
        'CLOUDFLARE_ANALYTICS_TOKEN': settings.CLOUDFLARE_ANALYTICS_TOKEN,
    }
