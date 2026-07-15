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
