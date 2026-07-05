"""Generate a branded Ochiq Kurs thumbnail (1280x720 PNG).

Style: flat emerald-charcoal background, solid category accent (no gradients),
Bricolage Grotesque title, Hanken Grotesk labels, one subtle radial glow.

Single image:
    python generate.py --title "Kurs nomi" --label "BACKEND" --color emerald \
        --out ../../media/course_thumbnails/kurs-slug.png

All courses from the local DB (also emits UPDATE statements to stdout):
    python generate.py --all-courses <media_root>

Colors: sky, emerald, violet, amber, slate, rose, indigo
(must match Category.color values used by the site).
"""
import argparse
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
W, H = 1280, 720
PAD = 84

BG = (10, 20, 17)          # matches --bg dark #0A1411
TITLE_COL = (243, 247, 245)
MUTED = (124, 143, 135)

ACCENTS = {
    'sky': (56, 189, 248),
    'emerald': (52, 211, 153),
    'violet': (167, 139, 250),
    'amber': (251, 191, 36),
    'slate': (148, 163, 184),
    'rose': (251, 113, 133),
    'indigo': (129, 140, 248),
}


def bricolage(size, wght=700):
    f = ImageFont.truetype(str(HERE / 'fonts' / 'Bricolage.ttf'), size)
    f.set_variation_by_axes([min(size, 72), 100, wght])
    return f


def hanken(size, wght=600):
    f = ImageFont.truetype(str(HERE / 'fonts' / 'Hanken.ttf'), size)
    f.set_variation_by_axes([wght])
    return f


def draw_tracked(draw, pos, text, font, fill, tracking=0):
    x, y = pos
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


def wrap_title(draw, title, font, max_width):
    words, lines, cur = title.split(), [], ''
    for w in words:
        probe = (cur + ' ' + w).strip()
        if draw.textlength(probe, font=font) <= max_width or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render(out_path, title, label, accent):
    img = Image.new('RGB', (W, H), BG)

    glow = Image.new('RGB', (W, H), BG)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W - 520, -320, W + 320, 420],
               fill=tuple(int(b + (a - b) * 0.16) for a, b in zip(accent, BG)))
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    img = Image.blend(img, glow, 0.9)

    d = ImageDraw.Draw(img)
    d.rectangle([PAD, PAD + 6, PAD + 44, PAD + 16], fill=accent)
    draw_tracked(d, (PAD + 66, PAD - 6), label.upper(), hanken(30, 650), accent, tracking=5)

    size = 96
    while size >= 54:
        tf = bricolage(size, 720)
        lines = wrap_title(d, title, tf, W - 2 * PAD - 40)
        line_h = int(size * 1.16)
        if len(lines) <= 3 and len(lines) * line_h <= 400:
            break
        size -= 8
    y = (H - len(lines) * line_h) // 2 + 10
    for line in lines:
        d.text((PAD, y), line, font=tf, fill=TITLE_COL)
        y += line_h

    draw_tracked(d, (PAD, H - PAD - 28), 'OCHIQ KURS', hanken(28, 700), MUTED, tracking=8)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, 'PNG', optimize=True)


def all_courses(media_root):
    rows = subprocess.run(
        ['psql', '-d', 'ochiqkurs', '-Atc',
         "SELECT c.slug || E'\\t' || c.title || E'\\t' || cat.name || E'\\t' || cat.color "
         "FROM learning_course c JOIN learning_category cat ON cat.id=c.category_id ORDER BY c.id;"],
        capture_output=True, text=True, check=True,
    ).stdout.strip().splitlines()
    for row in rows:
        slug, title, cat_name, color = row.split('\t')
        render(Path(media_root) / 'course_thumbnails' / f'{slug}.png',
               title, cat_name, ACCENTS.get(color, ACCENTS['emerald']))
        print(f"UPDATE learning_course SET thumbnail='course_thumbnails/{slug}.png' "
              f"WHERE slug='{slug}';")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--title')
    ap.add_argument('--label', default='')
    ap.add_argument('--color', default='emerald', choices=sorted(ACCENTS))
    ap.add_argument('--out')
    ap.add_argument('--all-courses', metavar='MEDIA_ROOT')
    args = ap.parse_args()
    if args.all_courses:
        all_courses(args.all_courses)
    elif args.title and args.out:
        render(args.out, args.title, args.label, ACCENTS[args.color])
    else:
        ap.error('need --title/--out, or --all-courses MEDIA_ROOT')
