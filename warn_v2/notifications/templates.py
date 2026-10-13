"""Shared HTML email building blocks (stdlib f-strings, no template engine).

Email-client CSS support is ~2005-era: table layout, fully inline styles, no
external fonts or CSS. Everything here targets that baseline. The look mirrors
the site's WARN Index identity (frontend/tailwind.config.js): warm ink/paper
neutrals, brand red as the one accent, a serif display face for headings and
figures (Fraunces on the site; email falls back to Georgia, since clients
don't load web fonts), and pill-shaped ink buttons.

The header's brand mark is the site's apple-touch-icon PNG with the wordmark
as live text beside it, so a client that blocks images still shows the name.
CTA buttons are padded table cells with ``bgcolor`` (Outlook-safe);
``border-radius`` is progressive enhancement only.

Contract (same as the rest of the notifications package): every dynamic string
interpolated into these helpers must already be ``html.escape()``d by the
caller. URLs passed to :func:`button` are escaped here (attribute context).
"""
from __future__ import annotations

from datetime import date
from html import escape

# Palette: the site's remapped slate (warm ink/paper) + brand red.
INK = "#1a1a19"  # headings, primary text, buttons (slate-900)
TEXT = "#3d3c39"  # body copy (slate-700)
MUTED = "#6e6c66"  # secondary text, 5.3:1 on white (slate-500)
HAIRLINE = "#e1e0d9"  # rules and borders (slate-200)
PAPER = "#f9f9f7"  # page plane behind the card (slate-50)
BRAND = "#da2f25"  # the one accent: kicker, top rule, closure badge
BRAND_SOFT = "#fbe9e7"
LINK = "#1c5cab"  # interactive accent (sky-700 on the site)

FONT = "font-family:Arial,Helvetica,sans-serif"
SERIF = "font-family:Fraunces,Georgia,'Times New Roman',serif"


def fmt_date(d: date | None) -> str:
    """Human date like ``Jun 3, 2026`` (Windows-safe: no ``%-d``)."""
    return f"{d.strftime('%b')} {d.day}, {d.year}" if d else ""


def button(url: str, label: str) -> str:
    """Bulletproof CTA button: padded table cell with bgcolor (Outlook-safe)."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td align="center" bgcolor="{INK}" style="border-radius:999px;">'
        f'<a href="{escape(url)}" style="display:inline-block;padding:12px 28px;{FONT};'
        'font-size:15px;font-weight:bold;color:#ffffff;text-decoration:none;'
        f'border-radius:999px;">{escape(label)}</a></td></tr></table>'
    )


def category_badge(category: str | None) -> str:
    """Small badge for a closure category; '' for plain layoffs and unknowns.

    Matches the site: only the exceptions are badged. Closures take the brand
    red; Non-WARN events a muted outline. Outlook drops span padding and
    background but keeps the text color, so this degrades to colored text.
    """
    if not category or category.lower() not in ("closure", "non-warn"):
        return ""
    style = (
        f"color:{BRAND};background-color:{BRAND_SOFT};"
        if category.lower() == "closure"
        else f"color:{MUTED};border:1px dashed {HAIRLINE};"
    )
    return (
        f'<span style="{FONT};font-size:10px;font-weight:bold;letter-spacing:0.8px;'
        f'{style}padding:2px 7px;border-radius:999px;">'
        f"{escape(category.upper())}</span>"
    )


def kicker(text: str) -> str:
    """The small brand-red uppercase label above a heading (pre-escaped text)."""
    return (
        f'<p style="margin:0 0 6px;{FONT};font-size:11px;font-weight:bold;'
        f'letter-spacing:1.6px;text-transform:uppercase;color:{BRAND};">{text}</p>'
    )


def heading(text: str) -> str:
    """Serif page heading (pre-escaped text)."""
    return (
        f'<p style="margin:0;{SERIF};font-size:26px;line-height:32px;font-weight:bold;'
        f'color:{INK};">{text}</p>'
    )


def message_rows(*, kicker_text: str, title: str, lead: str, url: str, cta: str) -> str:
    """Content rows for a single-action email: kicker, heading, lead, button.

    ``kicker_text``, ``title`` and ``lead`` are trusted pre-escaped HTML.
    """
    return (
        f'<tr><td style="padding:32px 32px 0;">{kicker(kicker_text)}{heading(title)}'
        f'<p style="margin:12px 0 0;{FONT};font-size:15px;line-height:23px;color:{TEXT};">'
        f"{lead}</p></td></tr>"
        f'<tr><td style="padding:24px 32px 32px;">{button(url, cta)}</td></tr>'
    )


def render_shell(*, preheader: str, content: str, footer: str, base: str) -> str:
    """Wrap pre-built ``content`` rows in the branded email document.

    ``content`` and ``footer`` are trusted pre-built HTML (dynamic text inside
    them already escaped by the caller); ``preheader`` must be pre-escaped too.
    ``content`` is one or more ``<tr>`` elements of the 600px card table.
    """
    home = escape(base)
    return (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        # The design is light-only; say so, so Apple Mail and friends don't
        # half-invert it (they would leave the brand-red rule on a dark plane).
        '<meta name="color-scheme" content="light">'
        '<meta name="supported-color-schemes" content="light">'
        "<title>WARN Index</title></head>"
        f'<body style="margin:0;padding:0;background-color:{PAPER};">'
        # Hidden preheader: shows as the inbox preview snippet, never in the body.
        '<div style="display:none;font-size:1px;line-height:1px;max-height:0;'
        'max-width:0;overflow:hidden;mso-hide:all;">'
        f"{preheader}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;"
        "&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;</div>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background-color:{PAPER};">'
        '<tr><td align="center" style="padding:24px 12px;">'
        # Fluid-hybrid card: width=100% + max-width so narrow clients shrink it
        # (a fixed width="600" acts as a table *minimum* and overflows phones);
        # Outlook's Word engine ignores max-width, so it gets a conditional
        # fixed-600 wrapper instead.
        "<!--[if mso]>"
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0">'
        "<tr><td><![endif]-->"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="max-width:600px;background-color:#ffffff;border:1px solid {HAIRLINE};'
        f'border-top:4px solid {BRAND};border-radius:12px;">'
        # Brand header: the mark (an image, so it can be blocked) + the
        # wordmark as live text, the way the site's header reads.
        f'<tr><td style="padding:20px 32px;border-bottom:1px solid {HAIRLINE};">'
        f'<a href="{home}/" style="text-decoration:none;">'
        f'<img src="{home}/apple-touch-icon.png" width="28" height="28" alt="" '
        'style="display:inline-block;vertical-align:middle;border:0;border-radius:6px;">'
        f'<span style="{SERIF};font-size:20px;font-weight:bold;color:{INK};'
        'vertical-align:middle;padding-left:10px;">WARN Index</span>'
        f'<span style="{FONT};font-size:13px;color:{MUTED};vertical-align:middle;'
        'padding-left:8px;">Layoff notices</span></a></td></tr>'
        f"{content}"
        f'<tr><td style="padding:20px 32px;border-top:1px solid {HAIRLINE};{FONT};'
        f'font-size:12px;line-height:18px;color:{MUTED};">{footer}</td></tr>'
        "</table>"
        "<!--[if mso]></td></tr></table><![endif]-->"
        f'<p style="margin:16px 0 0;{FONT};font-size:11px;color:{MUTED};">'
        "Data from US state WARN Act listings &#183; collected daily</p>"
        "</td></tr></table></body></html>"
    )
