class NoindexMiddleware:
    """Stamp ``X-Robots-Tag: noindex, nofollow`` on account/API/admin responses.

    These paths must never appear in search results (login, dashboards, JSON
    APIs, the admin). ``robots.txt`` Disallow alone can't guarantee that — it
    blocks *crawling*, not *indexing*, so a URL linked site-wide (e.g. the nav's
    ``/users/login/``) still gets indexed from those links, showing up bare in
    Google as "Indexed, though blocked by robots.txt". The fix is the opposite:
    let Google crawl these paths (``/users/`` and ``/api/`` are no longer
    Disallowed in robots.txt) and serve an explicit ``noindex`` it can honour,
    so the pages get dropped from the index. ``/admin/`` stays Disallowed and
    redirects anonymous users anyway, but is stamped here for defence in depth.
    """

    NOINDEX_PREFIXES = ('/users/', '/api/', '/admin/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(self.NOINDEX_PREFIXES):
            response['X-Robots-Tag'] = 'noindex, nofollow'
        return response


class HtmlNoCacheMiddleware:
    """Send ``Cache-Control: no-cache`` on HTML responses that don't set their own.

    Static assets are manifest-hashed and effectively immutable, but the HTML
    that references them shipped with no cache headers at all, so a browser
    could reuse a stale page after a deploy — and with it, the old hashed
    asset URLs (seen in the wild: users exercising week-old player JS).
    ``no-cache`` means "store, but revalidate before reuse": the back/forward
    cache keeps working, while every navigation picks up fresh markup.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            not response.has_header('Cache-Control')
            and response.get('Content-Type', '').startswith('text/html')
        ):
            response['Cache-Control'] = 'no-cache'
        return response
