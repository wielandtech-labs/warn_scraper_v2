"""Shared HTML email building blocks (stdlib f-strings, no template engine).

Email-client CSS support is ~2005-era: table layout, fully inline styles, no
external images/fonts/CSS. Everything here targets that baseline — the brand
header is a text wordmark (no logo image), the CTA button is a padded table
cell with ``bgcolor``, and ``border-radius`` is progressive enhancement only.

Contract (same as the rest of the notifications package): every dynamic string
interpolated into these helpers must already be ``html.escape()``d by the
caller. URLs passed to :func:`button` are escaped here (attribute context).
"""
from __future__ import annotations

from datetime import date
from html import escape

FONT = "font-family:Arial,Helvetica,sans-serif"


def fmt_date(d: date | None) -> str:
    """Human date like ``Jun 3, 2026`` (Windows-safe: no ``%-d``)."""
    return f"{d.strftime('%b')} {d.day}, {d.year}" if d else ""


def button(url: str, label: str) -> str:
    """Bulletproof CTA button: padded table cell with bgcolor (Outlook-safe)."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td align="center" bgcolor="#0369a1" style="border-radius:6px;">'
        f'<a href="{escape(url)}" style="display:inline-block;padding:12px 28px;{FONT};'
        'font-size:15px;font-weight:bold;color:#ffffff;text-decoration:none;">'
        f"{escape(label)}</a></td></tr></table>"
    )


def category_badge(category: str | None) -> str:
    """Small colored badge for a closure category; '' when unknown.

    Outlook drops span padding/background but keeps the text color, so this
    degrades to small colored text there.
    """
    if not category:
        return ""
    color, bg = (
        ("#9a3412", "#ffedd5") if category.lower() == "closure" else ("#334155", "#e2e8f0")
    )
    return (
        f'<span style="font-size:11px;font-weight:bold;letter-spacing:0.5px;'
        f'color:{color};background-color:{bg};padding:2px 6px;">'
        f"{escape(category.upper())}</span>"
    )


def render_shell(*, preheader: str, content: str, footer: str, base: str) -> str:
    """Wrap pre-built ``content`` rows in the branded email document.

    ``content`` and ``footer`` are trusted pre-built HTML (dynamic text inside
    them already escaped by the caller); ``preheader`` must be pre-escaped too.
    ``content`` is one or more ``<tr>`` elements of the 600px card table.
    """
    return (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>WARN Tracker</title></head>"
        '<body style="margin:0;padding:0;background-color:#f8fafc;">'
        # Hidden preheader: shows as the inbox preview snippet, never in the body.
        '<div style="display:none;font-size:1px;line-height:1px;max-height:0;'
        'max-width:0;overflow:hidden;mso-hide:all;">'
        f"{preheader}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;"
        "&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;</div>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="background-color:#f8fafc;">'
        '<tr><td align="center" style="padding:24px 12px;">'
        # Fluid-hybrid card: width=100% + max-width so narrow clients shrink it
        # (a fixed width="600" acts as a table *minimum* and overflows phones);
        # Outlook's Word engine ignores max-width, so it gets a conditional
        # fixed-600 wrapper instead.
        "<!--[if mso]>"
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0">'
        "<tr><td><![endif]-->"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="max-width:600px;background-color:#ffffff;border:1px solid #e2e8f0;">'
        # Brand header: text wordmark, no logo image (images are blocked by default).
        f'<tr><td style="background-color:#0369a1;padding:16px 24px;{FONT};">'
        f'<a href="{escape(base)}/" style="color:#ffffff;text-decoration:none;'
        'font-size:18px;font-weight:bold;">WARN '
        '<span style="color:#bae6fd;font-weight:normal;">&#183;</span> '
        '<span style="font-weight:normal;">Layoff notices</span></a></td></tr>'
        f"{content}"
        f'<tr><td style="padding:16px 24px;border-top:1px solid #e2e8f0;{FONT};'
        f'font-size:12px;line-height:18px;color:#64748b;">{footer}</td></tr>'
        "</table>"
        "<!--[if mso]></td></tr></table><![endif]-->"
        "</td></tr></table></body></html>"
    )
