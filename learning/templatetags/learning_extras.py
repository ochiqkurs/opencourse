from django import template
from django.utils import timezone
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def duration(seconds):
    """Soniyani '1 soat 23 daqiqa' formatiga o'tkazadi."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "0 daqiqa"
    total_minutes = seconds // 60
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours and minutes:
        return f"{hours} soat {minutes} daqiqa"
    if hours:
        return f"{hours} soat"
    return f"{minutes} daqiqa"


@register.filter
def duration_short(seconds):
    """Short form: '1s 23d' or '23 daq' or '12 daq'."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "—"
    total_minutes = seconds // 60
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours and minutes:
        return f"{hours}s {minutes}d"
    if hours:
        return f"{hours}s"
    return f"{minutes} daq"


@register.filter
def lesson_time(seconds):
    """Compact lesson length: '12:34' or '1:02:34'."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "—"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


@register.filter
def get_item(dictionary, key):
    return dictionary.get(str(key))


@register.filter
def has_lesson(id_set, lesson_id):
    if id_set is None:
        return False
    try:
        return lesson_id in id_set
    except TypeError:
        return False


@register.filter
def stars(rating):
    """Render a 5-star line with filled / half / empty unicode glyphs."""
    try:
        r = float(rating or 0)
    except (TypeError, ValueError):
        r = 0
    full = int(r)
    half = 1 if (r - full) >= 0.5 else 0
    empty = 5 - full - half
    out = '★' * full + ('½' if half else '') + '☆' * empty
    return mark_safe(f'<span class="stars-glyphs" aria-label="{r:.1f} / 5">{out}</span>')


@register.filter
def percent_of(part, whole):
    try:
        if not whole:
            return 0
        return int(round(100 * float(part) / float(whole)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


@register.filter
def initials(name):
    if not name:
        return "?"
    parts = [p for p in str(name).split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


_UZ_MONTHS = [
    '', 'yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun',
    'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr',
]


def _localize(value):
    """Convert an aware datetime to the active tz (Asia/Tashkent).

    Django's built-in `date` filter localizes before formatting; do the same so
    the day/time we render match it (a UTC-stored datetime near midnight would
    otherwise show the wrong day).
    """
    if hasattr(value, 'hour') and timezone.is_aware(value):
        return timezone.localtime(value)
    return value


@register.filter
def uz_date(value):
    """Format a date/datetime in Uzbek, e.g. '6-iyun, 2026-yil'.

    Django's built-in `date` filter renders English month names because
    LANGUAGE_CODE is 'en-us' ('06 Jun 2026'), which looks wrong in an Uzbek UI.
    """
    if not value:
        return ''
    try:
        v = _localize(value)
        return f"{v.day}-{_UZ_MONTHS[v.month]}, {v.year}-yil"
    except (AttributeError, IndexError):
        return ''


@register.filter
def uz_datetime(value):
    """Like `uz_date`, but also appends the local time: '6-iyun, 2026-yil, 14:30'."""
    if not value:
        return ''
    try:
        v = _localize(value)
        out = f"{v.day}-{_UZ_MONTHS[v.month]}, {v.year}-yil"
    except (AttributeError, IndexError):
        return ''
    if hasattr(v, 'hour'):
        out += f", {v.hour:02d}:{v.minute:02d}"
    return out


# ── Inline Lucide icons ──────────────────────────────────────────
# Curated set of Lucide icon paths so templates can render an icon by name
# (e.g. a Category's `icon` field, or replacing emoji used as icons). Keeps the
# "inline SVG, no sprite/font" convention. Unknown names fall back to book-open.
_LUCIDE_ICONS = {
    'layout': '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/>',
    'server': '<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>',
    'smartphone': '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/>',
    'database': '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
    'cloud': '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
    'brain-circuit': '<path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M9 13a4.5 4.5 0 0 0 3-4"/><path d="M12 13h4"/><path d="M12 18h6a2 2 0 0 1 2 2v1"/><path d="M12 8h8"/><path d="M16 8V5a2 2 0 0 1 2-2"/><circle cx="16" cy="13" r=".5"/><circle cx="18" cy="3" r=".5"/><circle cx="20" cy="8" r=".5"/>',
    'code': '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    'gamepad-2': '<line x1="6" x2="10" y1="11" y2="11"/><line x1="8" x2="8" y1="9" y2="13"/><line x1="15" x2="15.01" y1="12" y2="12"/><line x1="18" x2="18.01" y1="10" y2="10"/><path d="M17.32 5H6.68a4 4 0 0 0-3.978 3.59c-.006.052-.01.101-.017.152C2.604 9.416 2 14.456 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.414-1.414A2 2 0 0 1 9.828 16h4.344a2 2 0 0 1 1.414.586L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.545-.604-6.584-.685-7.258-.007-.05-.011-.1-.017-.151A4 4 0 0 0 17.32 5z"/>',
    'clapperboard': '<path d="M20.2 6 3 11l-.9-2.4c-.3-1.1.3-2.2 1.3-2.5l13.5-4c1.1-.3 2.2.3 2.5 1.3Z"/><path d="m6.2 5.3 3.1 3.9"/><path d="m12.4 3.4 3.1 4"/><path d="M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    'file-spreadsheet': '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M8 13h2"/><path d="M14 13h2"/><path d="M8 17h2"/><path d="M14 17h2"/>',
    'cpu': '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
    'flame': '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
    'trophy': '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>',
    'graduation-cap': '<path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z"/><path d="M22 10v6"/><path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/>',
    'pin': '<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
    'book-open': '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
}


@register.simple_tag
def lucide(name, size=24):
    """Render an inline Lucide SVG by name. Falls back to book-open if unknown."""
    inner = _LUCIDE_ICONS.get(name) or _LUCIDE_ICONS['book-open']
    return mark_safe(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{inner}</svg>'
    )
