import markdown
import bleach

_ALLOWED_TAGS = [
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'ul', 'ol', 'li', 'br', 'hr',
    'strong', 'em', 'b', 'i',
    'code', 'pre', 'blockquote', 'a',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
]

_ALLOWED_ATTRS = {
    'a':    ['href', 'title'],
    'code': ['class'],
    'pre':  ['class'],
}

_ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']


def render_markdown(text: str) -> str:
    if not text:
        return ''
    html = markdown.markdown(text, extensions=['fenced_code', 'tables', 'nl2br'])
    return bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )
