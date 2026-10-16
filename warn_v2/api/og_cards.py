"""Social-share (OpenGraph) card images, rendered server side with Pillow.

A link to /states/TX unfurls in Slack/LinkedIn/X with a card that says
something -- the state's silhouette, its all-time workers-affected figure and a
yearly trend -- instead of the one generic site image.

Pure rendering: callers pass the numbers in (see routes/og.py), so this module
needs no database and is unit-testable. The state outlines are the same path
data the frontend maps draw (warn_v2/geo/_data/us_state_paths.json, emitted by
scripts/fetch_us_state_paths.py); they use only m/l/h/v/z commands, so a
small parser turns them into polygons Pillow can fill.
"""
from __future__ import annotations

import io
import json
import re
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 630
SS = 2  # supersample: draw at 2x and downscale, since Pillow doesn't anti-alias shapes

# The site palette (frontend/tailwind.config.js, src/lib/themeColors.ts).
PAPER = (249, 249, 247)
INK = (26, 26, 25)
MUTED = (110, 108, 102)
HAIRLINE = (225, 224, 217)
SHAPE = (225, 224, 217)
BRAND = (218, 47, 37)
BRAND_SOFT = (247, 213, 210)

_ASSETS = Path(__file__).parent / "assets"
_FONT = _ASSETS / "fraunces-latin-wght-normal.woff2"
_PATHS = Path(__file__).parent.parent / "geo" / "_data" / "us_state_paths.json"

Point = tuple[float, float]
Polygon = list[Point]

_TOKEN = re.compile(r"[MmLlHhVvZz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?")


@cache
def state_paths() -> dict[str, str]:
    return json.loads(_PATHS.read_text(encoding="utf-8"))["paths"]


def parse_path(d: str) -> list[Polygon]:
    """SVG path data using only M/L/H/V/Z (either case) -> closed polygons.

    Implicit repeats follow the spec: numbers after an m/M continue as l/L.
    """
    tokens = _TOKEN.findall(d)
    polys: list[Polygon] = []
    current: Polygon = []
    x = y = 0.0
    start: Point = (0.0, 0.0)
    cmd = ""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
            if cmd in "Zz":
                if current:
                    polys.append(current)
                current = []
                x, y = start
            continue
        if cmd in "MmLl":
            dx, dy = float(tokens[i]), float(tokens[i + 1])
            i += 2
            rel = cmd.islower()
            x, y = (x + dx, y + dy) if rel else (dx, dy)
            if cmd in "Mm":
                if current:
                    polys.append(current)
                current = []
                start = (x, y)
                cmd = "l" if rel else "L"  # implicit lineto after moveto
        else:
            v = float(tok)
            i += 1
            if cmd == "h":
                x += v
            elif cmd == "H":
                x = v
            elif cmd == "v":
                y += v
            elif cmd == "V":
                y = v
            else:
                raise ValueError(f"unsupported path command {cmd!r}")
        current.append((x, y))
    if current:
        polys.append(current)
    return polys


def _font(size: int, weight: int = 600) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        font = ImageFont.truetype(str(_FONT), size * SS)
        font.set_variation_by_axes([weight])
        return font
    except OSError:
        # FreeType built without WOFF2/brotli support: still render a card.
        return ImageFont.load_default(size * SS)


def _brand_mark(draw: ImageDraw.ImageDraw, x: float, y: float, size: float) -> None:
    """The three-falling-bars mark (frontend/public/favicon.svg), at (x, y)."""
    u = size / 32
    draw.rounded_rectangle((x, y, x + size, y + size), radius=7 * u, fill=BRAND)
    for bx, by, h, a in ((7, 8, 16, 255), (13.75, 12, 12, 217), (20.5, 17, 7, 179)):
        # Pre-blend the bar opacity against the brand red (no alpha needed).
        c = tuple(round(255 * a / 255 + v * (1 - a / 255)) for v in BRAND)
        draw.rounded_rectangle(
            (x + bx * u, y + by * u, x + (bx + 4.5) * u, y + (by + h) * u),
            radius=1.5 * u,
            fill=c,
        )


def _fmt(n: int) -> str:
    return f"{n:,}"


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (WIDTH * SS, HEIGHT * SS), PAPER)
    draw = ImageDraw.Draw(img)
    # Brand rule along the top edge, as on the site's masthead.
    draw.rectangle((0, 0, WIDTH * SS, 8 * SS), fill=BRAND)
    _brand_mark(draw, 64 * SS, 56 * SS, 44 * SS)
    draw.text((124 * SS, 58 * SS), "WARN Index", font=_font(34), fill=INK)
    return img, draw


def _finish(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS).save(out, "PNG", optimize=True)
    return out.getvalue()


def _silhouette(draw: ImageDraw.ImageDraw, code: str, box: tuple[float, float, float, float]):
    """Fill `code`'s outline, scaled to fit `box` (x0, y0, x1, y1), centred."""
    polys = parse_path(state_paths()[code])
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    bx0, by0, bx1, by1 = box
    scale = min((bx1 - bx0) / w, (by1 - by0) / h)
    ox = bx0 + ((bx1 - bx0) - w * scale) / 2 - min(xs) * scale
    oy = by0 + ((by1 - by0) - h * scale) / 2 - min(ys) * scale
    for poly in polys:
        if len(poly) >= 3:
            draw.polygon([(ox + px * scale, oy + py * scale) for px, py in poly], fill=SHAPE)


def _spark(draw: ImageDraw.ImageDraw, values: list[int], box: tuple[float, float, float, float]):
    if len(values) < 2:
        return
    x0, y0, x1, y1 = box
    top = max(values) or 1
    pts = [
        (x0 + (x1 - x0) * i / (len(values) - 1), y1 - (y1 - y0) * v / top)
        for i, v in enumerate(values)
    ]
    draw.polygon([*pts, (x1, y1), (x0, y1)], fill=BRAND_SOFT)
    draw.line(pts, fill=BRAND, width=4 * SS, joint="curve")


def render_state_card(
    code: str,
    name: str,
    workers: int | None,
    notices: int,
    yearly: list[tuple[str, int]],
) -> bytes:
    """1200x630 PNG for a state page. `workers` None = the source publishes
    no employee counts (rendered as a dash, never as zero). `yearly` is
    (year, workers affected), oldest first, complete years only."""
    img, draw = _canvas()
    if code == "DC":
        # DC's real outline is a few pixels; scaled up it reads as a glitch.
        # The frontend maps draw it as a square callout -- match that.
        square = (830 * SS, 190 * SS, 1010 * SS, 370 * SS)
        draw.rounded_rectangle(square, radius=24 * SS, fill=SHAPE)
    else:
        _silhouette(draw, code, (700 * SS, 90 * SS, 1140 * SS, 470 * SS))
    # Shrink long names ("District of Columbia") to stay clear of the shape.
    size = 76
    while size > 40 and draw.textlength(name, font=_font(size)) > 600 * SS:
        size -= 4
    draw.text((64 * SS, 160 * SS + (76 - size) * SS), name, font=_font(size), fill=INK)
    kicker = "WORKERS AFFECTED BY WARN NOTICES, ALL TIME"
    draw.text((64 * SS, 268 * SS), kicker, font=_font(20, 500), fill=MUTED)
    figure = "—" if workers is None else _fmt(workers)  # em dash, never a fake zero
    draw.text((64 * SS, 300 * SS), figure, font=_font(96, 650), fill=BRAND)
    if workers is None:
        draw.text(
            (180 * SS, 340 * SS), "not published by the source", font=_font(26, 450), fill=MUTED
        )
    draw.text((64 * SS, 430 * SS), f"{_fmt(notices)} notices", font=_font(30, 450), fill=MUTED)
    if len(yearly) >= 2:
        _spark(draw, [v for _, v in yearly], (64 * SS, 500 * SS, 1136 * SS, 586 * SS))
        draw.text((64 * SS, 594 * SS), yearly[0][0], font=_font(18, 500), fill=MUTED)
        last = yearly[-1][0]
        lw = draw.textlength(last, font=_font(18, 500))
        draw.text((1136 * SS - lw, 594 * SS), last, font=_font(18, 500), fill=MUTED)
    return _finish(img)


def _fit_lines(
    draw: ImageDraw.ImageDraw, text: str, width: float, sizes: range, max_lines: int
) -> tuple[list[str], int]:
    """Word-wrap `text` into at most `max_lines` lines no wider than `width`,
    trying font sizes largest first; the last resort truncates with an ellipsis."""
    words = text.split()
    for size in sizes:
        font = _font(size)
        lines: list[str] = []
        for word in words:
            if lines and draw.textlength(f"{lines[-1]} {word}", font=font) <= width:
                lines[-1] = f"{lines[-1]} {word}"
            else:
                lines.append(word)
        if len(lines) <= max_lines and all(draw.textlength(ln, font=font) <= width for ln in lines):
            return lines, size
    size = sizes[-1]
    font = _font(size)
    lines = lines[:max_lines]
    last = lines[-1]
    while last and draw.textlength(f"{last}…", font=font) > width:
        last = last[:-1]
    lines[-1] = f"{last.rstrip()}…"
    return lines, size


def render_notice_card(
    employer: str,
    code: str,
    place: str,
    workers: int | None,
    action: str,
    dates: str,
) -> bytes:
    """1200x630 PNG for one WARN notice. `place` is "City, ST" (or just the
    state name), `action` the closure label ("Mass layoff", "Closure"),
    `dates` a preformatted line ("Filed Oct 14, 2026 · Effective Dec 13, 2026").
    `workers` None = the filing gives no count (a dash, never a zero)."""
    img, draw = _canvas()
    if code == "DC":
        square = (900 * SS, 200 * SS, 1080 * SS, 380 * SS)
        draw.rounded_rectangle(square, radius=24 * SS, fill=SHAPE)
    elif code in state_paths():
        _silhouette(draw, code, (800 * SS, 110 * SS, 1140 * SS, 420 * SS))
    kicker = f"WARN NOTICE · {place.upper()}"
    draw.text((64 * SS, 150 * SS), kicker, font=_font(22, 500), fill=MUTED)
    lines, size = _fit_lines(draw, employer, 760 * SS, range(68, 39, -4), 2)
    y = 186
    for line in lines:
        draw.text((64 * SS, y * SS), line, font=_font(size), fill=INK)
        y += round(size * 1.15)
    figure = "—" if workers is None else _fmt(workers)  # em dash, never a fake zero
    fy = max(y + 24, 340)
    draw.text((64 * SS, fy * SS), figure, font=_font(96, 650), fill=BRAND)
    fw = draw.textlength(figure, font=_font(96, 650))
    label = "workers affected" if workers is not None else "count not published"
    draw.text((64 * SS + fw + 24 * SS, (fy + 46) * SS), label, font=_font(30, 450), fill=MUTED)
    draw.line((64 * SS, 524 * SS, 1136 * SS, 524 * SS), fill=HAIRLINE, width=2 * SS)
    draw.text((64 * SS, 548 * SS), f"{action} · {dates}", font=_font(24, 450), fill=MUTED)
    return _finish(img)


def render_default_card() -> bytes:
    """The site-wide card (frontend/public/og-image.png)."""
    img, draw = _canvas()
    draw.text((64 * SS, 200 * SS), "Layoffs, as they’re", font=_font(84), fill=INK)  # noqa: RUF001 -- typographic apostrophe
    draw.text((64 * SS, 300 * SS), "announced.", font=_font(84), fill=INK)
    draw.line((64 * SS, 432 * SS, 560 * SS, 432 * SS), fill=HAIRLINE, width=2 * SS)
    draw.text(
        (64 * SS, 456 * SS),
        "Every US state WARN Act notice, gathered daily and mapped.",
        font=_font(28, 450),
        fill=MUTED,
    )
    draw.text((64 * SS, 540 * SS), "warnindex.com", font=_font(26, 600), fill=BRAND)
    return _finish(img)


def render_touch_icon(size: int = 180) -> bytes:
    """apple-touch-icon: the mark, full bleed (iOS rounds the corners itself)."""
    img = Image.new("RGB", (size * SS, size * SS), BRAND)
    _brand_mark(ImageDraw.Draw(img), 0, 0, size * SS)
    out = io.BytesIO()
    img.resize((size, size), Image.Resampling.LANCZOS).save(out, "PNG", optimize=True)
    return out.getvalue()
