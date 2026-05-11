from django import template
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
