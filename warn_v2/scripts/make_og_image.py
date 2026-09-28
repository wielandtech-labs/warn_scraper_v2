"""Regenerate ``frontend/public/og-image.png``, the 1200x630 social card.

Run by hand when the brand, tagline, or domain changes — it is not wired into
CI or the build. It exists because the card is a binary asset with no source:
when the site was renamed to WARN Index the PNG kept advertising "WARN Tracker"
and the old domain in every unfurl, and nothing flagged it.

Needs Pillow, which is NOT a project dependency (it is only used here):

    uv pip install pillow --python .venv/Scripts/python.exe
    python -m warn_v2.scripts.make_og_image

Colours and geometry were sampled from the original card so regenerating it
changes only the words. FONT_BOLD/FONT_REGULAR default to Segoe UI on Windows;
point them at any humanist sans elsewhere.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[2] / "frontend" / "public" / "og-image.png"

WIDTH, HEIGHT = 1200, 630
GRADIENT_TOP = (3, 105, 161)
GRADIENT_BOTTOM = (12, 74, 110)
BRAND_BLUE = (3, 105, 161)   # the W inside the badge
MUTED = (212, 225, 233)      # subtitle and domain
TREND = (255, 255, 255, 46)  # decorative layoff-trend polyline

FONT_BOLD = r"C:\Windows\Fonts\segoeuib.ttf"
FONT_REGULAR = r"C:\Windows\Fonts\segoeui.ttf"

HEADLINE = "WARN Index"
SUBTITLE = "US layoff & closure notices - searchable, mapped, updated daily"
DOMAIN = "warnindex.com"

# Cap-height tops, sampled from the original card.
HEADLINE_TOP, SUBTITLE_TOP, DOMAIN_TOP = 280, 384, 444
TEXT_LEFT = 92
BADGE = (91, 111, 185, 205)


def _gradient() -> Image.Image:
    im = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(im)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        draw.line(
            [(0, y), (WIDTH, y)],
            fill=tuple(
                round(a + (b - a) * t) for a, b in zip(GRADIENT_TOP, GRADIENT_BOTTOM, strict=True)
            ),
        )
    return im


def _with_trend(im: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(overlay).line(
        [(0, 518), (200, 472), (400, 498), (475, 472), (590, 430),
         (700, 468), (950, 355), (1200, 428)],
        fill=TREND, width=5, joint="curve",
    )
    return Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")


def build() -> Image.Image:
    im = _with_trend(_gradient())
    draw = ImageDraw.Draw(im)

    draw.rectangle(BADGE, fill=(255, 255, 255))
    badge_font = ImageFont.truetype(FONT_BOLD, 64)
    box = draw.textbbox((0, 0), "W", font=badge_font)
    cx = (BADGE[0] + BADGE[2]) / 2
    cy = (BADGE[1] + BADGE[3]) / 2
    draw.text(
        (cx - (box[0] + box[2]) / 2, cy - (box[1] + box[3]) / 2),
        "W", font=badge_font, fill=BRAND_BLUE,
    )

    def capped(text: str, font_path: str, cap_top: int, size: int, fill) -> None:
        """Draw `text` with its cap height at `cap_top`, as the original is set."""
        font = ImageFont.truetype(font_path, size)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text((TEXT_LEFT - box[0], cap_top - box[1]), text, font=font, fill=fill)

    capped(HEADLINE, FONT_BOLD, HEADLINE_TOP, 90, (255, 255, 255))
    capped(SUBTITLE, FONT_REGULAR, SUBTITLE_TOP, 33, MUTED)
    capped(DOMAIN, FONT_REGULAR, DOMAIN_TOP, 33, MUTED)
    return im


if __name__ == "__main__":
    build().save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT}")
