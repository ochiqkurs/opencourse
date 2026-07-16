"""AI tutor — per-lesson chat backed by the Claude Messages API.

A hand-written tool-use loop (no framework): the model answers from the lesson
context injected into the (cached) system prompt and may call read-only tools
for course structure, the user's progress, other lessons' content, and catalog
search. Only clean text crosses the request boundary — tool_use/thinking blocks
live and die inside one `run_tutor_turn` call.
"""

import json
import logging

import anthropic
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse

from .models import Course, Lesson, LessonProgress, TutorMessage
from .utils import render_markdown

logger = logging.getLogger(__name__)

MAX_AGENT_ITERATIONS = 5   # hard stop for the tool loop within one turn
MAX_TOKENS = 8000          # thinking + reply budget per API call
HISTORY_LIMIT = 12         # prior messages replayed to the API (6 exchanges)
MAX_QUESTION_CHARS = 2000
LESSON_CONTEXT_CHARS = 15000
TOOL_CONTENT_CHARS = 8000

FALLBACK_ERROR = (
    "Kechirasiz, hozir javob tayyorlashda muammo yuz berdi. "
    "Birozdan so'ng qayta urinib ko'ring."
)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

# Static block first (shared prefix), volatile lesson context second — the
# cache_control breakpoint on the lesson block caches tools + both blocks for
# the whole conversation on this lesson.
SYSTEM_PROMPT = """\
Sen — "Ochiq Kurs" (ochiqkurs.uz) platformasining AI-tutorisan. Platforma \
o'zbek tilidagi bepul video-kurslardan iborat.

Vazifang — foydalanuvchiga hozir ochiq turgan dars va kurs materialini \
tushunishga yordam berish.

Qoidalar:
- O'zbek tilida javob ber. Foydalanuvchi boshqa tilda yozsa, o'sha tilda javob ber.
- Javobni Markdown formatida yoz: kod uchun ``` bloklar (tilini ko'rsat), \
ro'yxatlar, **muhim** joylarni ajrat.
- Qisqa va aniq tushuntir. Uzun ma'ruza o'qima — savolga javob ber, kerak \
bo'lsa bitta kichik misol keltir.
- Topshiriq yoki testni foydalanuvchi o'rniga butunlay yechib berma: \
yo'naltir, qadamlarni tushuntir, xatosini ko'rsat.
- Dars va dasturlash/ta'lim mavzusidan tashqari savollarga muloyimlik bilan \
javob berma va darsga qaytar.
- Dars matni system promptda berilgan. Kursning boshqa darslari, foydalanuvchi \
progressi yoki platformadagi boshqa kurslar haqida so'ralsa, tegishli tooldan \
foydalan — taxmin qilma.
"""


def _lesson_context(lesson):
    course = lesson.module.course
    body = lesson.content or lesson.description or ''
    if len(body) > LESSON_CONTEXT_CHARS:
        body = body[:LESSON_CONTEXT_CHARS] + "\n\n[matn qisqartirildi]"
    parts = [
        "Hozirgi dars konteksti:",
        f"Kurs: {course.title}",
        f"Modul: {lesson.module.title}",
        f"Dars: {lesson.title} ({lesson.get_lesson_type_display()})",
    ]
    if body:
        parts.append("\nDars matni:\n" + body)
    else:
        parts.append("\nBu dars uchun matnli material yo'q (video dars).")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "get_course_outline",
        "description": (
            "Return the current course's full outline: modules and their "
            "lessons (title, slug, type). Call this when the user asks what "
            "the course covers, where a topic is taught, or what comes "
            "next/previous."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_user_progress",
        "description": (
            "Return the user's progress in the current course (completed vs "
            "total lessons, percent) and their current learning streak. Call "
            "this when the user asks about their progress, what's left, or "
            "their streak."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_lesson_content",
        "description": (
            "Return the text content (konspekt/description) of another lesson "
            "in the current course, by its slug. Get slugs from "
            "get_course_outline first. Call this when the user asks about a "
            "topic covered in a different lesson of this course."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lesson_slug": {
                    "type": "string",
                    "description": "Slug of the lesson within the current course",
                },
            },
            "required": ["lesson_slug"],
        },
    },
    {
        "name": "search_courses",
        "description": (
            "Search the platform's published course catalog by keyword. Call "
            "this when the user asks what other courses exist on a topic or "
            "what to learn next beyond the current course."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to match against course titles/subtitles",
                },
            },
            "required": ["query"],
        },
    },
]


def _tool_get_course_outline(user, lesson, tool_input):
    course = lesson.module.course
    modules = []
    for m in course.modules.prefetch_related('lessons').order_by('order'):
        modules.append({
            'module': m.title,
            'lessons': [
                {'title': l.title, 'slug': l.slug, 'type': l.lesson_type}
                for l in m.lessons.all()
            ],
        })
    return {'course': course.title, 'modules': modules}


def _tool_get_user_progress(user, lesson, tool_input):
    course = lesson.module.course
    total = Lesson.objects.filter(module__course=course).count()
    done = LessonProgress.objects.filter(
        user=user, lesson__module__course=course, is_completed=True,
    ).count()
    percent = int(done / total * 100) if total else 0
    profile = getattr(user, 'profile', None)
    return {
        'course': course.title,
        'completed_lessons': done,
        'total_lessons': total,
        'percent': percent,
        'current_streak_days': profile.live_streak if profile else 0,
    }


def _tool_get_lesson_content(user, lesson, tool_input):
    slug = (tool_input.get('lesson_slug') or '').strip()
    target = Lesson.objects.filter(
        module__course=lesson.module.course, slug=slug,
    ).first()
    if target is None:
        return {'error': f"Bu kursda '{slug}' slug'li dars topilmadi."}
    body = target.content or target.description or ''
    if len(body) > TOOL_CONTENT_CHARS:
        body = body[:TOOL_CONTENT_CHARS] + "\n\n[matn qisqartirildi]"
    return {
        'title': target.title,
        'module': target.module.title,
        'type': target.lesson_type,
        'content': body or "Bu darsda matnli material yo'q (video dars).",
    }


def _tool_search_courses(user, lesson, tool_input):
    query = (tool_input.get('query') or '').strip()
    if not query:
        return {'error': "query bo'sh bo'lmasligi kerak."}
    courses = Course.objects.filter(status='published').filter(
        Q(title__icontains=query) | Q(subtitle__icontains=query)
    ).order_by('order')[:5]
    return {
        'results': [
            {
                'title': c.title,
                'slug': c.slug,
                'subtitle': c.subtitle,
                'level': c.level,
                'instructor': c.instructor_name,
            }
            for c in courses
        ],
    }


TOOL_HANDLERS = {
    'get_course_outline': _tool_get_course_outline,
    'get_user_progress': _tool_get_user_progress,
    'get_lesson_content': _tool_get_lesson_content,
    'search_courses': _tool_search_courses,
}


def _execute_tool(user, lesson, block):
    """Run one tool_use block and wrap the outcome as a tool_result."""
    handler = TOOL_HANDLERS.get(block.name)
    try:
        if handler is None:
            raise ValueError(f"Unknown tool: {block.name}")
        result = handler(user, lesson, block.input or {})
        return {
            'type': 'tool_result',
            'tool_use_id': block.id,
            'content': json.dumps(result, ensure_ascii=False),
        }
    except Exception:
        logger.exception("AI tutor tool failed: %s", block.name)
        return {
            'type': 'tool_result',
            'tool_use_id': block.id,
            'content': "Tool bajarilmadi (ichki xatolik).",
            'is_error': True,
        }


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def run_tutor_turn(user, lesson, messages):
    """One chat turn: call the model, execute requested tools, repeat until it
    stops asking for tools (or the iteration cap). Returns (text, usage)."""
    client = _get_client()
    system = [
        {'type': 'text', 'text': SYSTEM_PROMPT},
        {
            'type': 'text',
            'text': _lesson_context(lesson),
            'cache_control': {'type': 'ephemeral'},
        },
    ]
    usage = {'input_tokens': 0, 'output_tokens': 0, 'cache_read_tokens': 0}
    response = None

    for _ in range(MAX_AGENT_ITERATIONS):
        response = client.messages.create(
            model=settings.AI_TUTOR_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOLS,
            output_config={'effort': 'medium'},
            messages=messages,
        )
        u = response.usage
        usage['input_tokens'] += (u.input_tokens or 0) + (u.cache_creation_input_tokens or 0)
        usage['output_tokens'] += u.output_tokens or 0
        usage['cache_read_tokens'] += u.cache_read_input_tokens or 0

        if response.stop_reason != 'tool_use':
            break

        # Full content back (thinking + tool_use blocks), then ALL tool results
        # in a single user message — splitting them degrades parallel tool use.
        messages.append({'role': 'assistant', 'content': response.content})
        tool_results = [
            _execute_tool(user, lesson, block)
            for block in response.content
            if block.type == 'tool_use'
        ]
        messages.append({'role': 'user', 'content': tool_results})
    else:
        logger.warning("AI tutor hit MAX_AGENT_ITERATIONS for user=%s lesson=%s",
                       user.id, lesson.id)

    if response.stop_reason == 'refusal':
        return (
            "Kechirasiz, bu savolga javob bera olmayman. "
            "Dars mavzusi bo'yicha boshqa savol bering.",
            usage,
        )

    text = ''.join(b.text for b in response.content if b.type == 'text').strip()
    return (text or FALLBACK_ERROR), usage


# ---------------------------------------------------------------------------
# POST /malaka/<course_slug>/<module_slug>/<lesson_slug>/yordamchi/
# ---------------------------------------------------------------------------

@login_required
def tutor_chat(request, course_slug, module_slug, lesson_slug):
    from users.views import _check_rate_limit
    from .views import _get_lesson

    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    if not settings.ANTHROPIC_API_KEY:
        return JsonResponse({'error': "AI tutor hozircha sozlanmagan."}, status=503)

    lesson = _get_lesson(course_slug, module_slug, lesson_slug, request.user)

    # Anti-abuse only, not a usage quota (keyed per user, not per IP).
    if _check_rate_limit(f'u{request.user.id}', max_requests=10, window=60, prefix='tutor'):
        return JsonResponse(
            {'error': "Juda ko'p so'rov yubordingiz. Bir daqiqadan so'ng qayta urining."},
            status=429,
        )

    try:
        message = (json.loads(request.body).get('message') or '').strip()
    except (json.JSONDecodeError, ValueError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    if not message:
        return JsonResponse({'error': "Xabar bo'sh bo'lmasligi kerak."}, status=400)
    if len(message) > MAX_QUESTION_CHARS:
        return JsonResponse(
            {'error': f"Xabar juda uzun (maksimum {MAX_QUESTION_CHARS} belgi)."},
            status=400,
        )

    history = list(
        TutorMessage.objects
        .filter(user=request.user, lesson=lesson)
        .order_by('-created_at')[:HISTORY_LIMIT - 1]
    )[::-1]
    api_messages = [{'role': m.role, 'content': m.content} for m in history]
    api_messages.append({'role': 'user', 'content': message})

    TutorMessage.objects.create(
        user=request.user, lesson=lesson, role='user', content=message,
    )

    try:
        text, usage = run_tutor_turn(request.user, lesson, api_messages)
    except anthropic.APIError:
        logger.exception("AI tutor API call failed (user=%s lesson=%s)",
                         request.user.id, lesson.id)
        return JsonResponse({'error': FALLBACK_ERROR}, status=502)

    TutorMessage.objects.create(
        user=request.user, lesson=lesson, role='assistant', content=text,
        input_tokens=usage['input_tokens'],
        output_tokens=usage['output_tokens'],
        cache_read_tokens=usage['cache_read_tokens'],
    )

    return JsonResponse({'status': 'ok', 'rendered': render_markdown(text)})
