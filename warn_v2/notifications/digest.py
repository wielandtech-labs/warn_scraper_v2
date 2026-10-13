"""Build and send alert digests for confirmed subscriptions.

Separated from the HTTP routes so the CLI (``warn-v2 send-alert-digest``) and
tests can drive it directly. A digest contains the notices discovered
(``scraped_at``) since the subscription's watermark that match its filters; the
watermark is advanced to ``now`` after a successful send.
"""
from __future__ import annotations

import logging
from datetime import datetime
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.alerts import describe_scope, is_due, manage_url, notices_url, unsubscribe_url
from warn_v2.api.filters import apply_notice_filters
from warn_v2.api.seo import site_base_url
from warn_v2.db.models import Notice, Subscription
from warn_v2.notifications.email import send_email
from warn_v2.notifications.templates import (
    FONT,
    HAIRLINE,
    INK,
    MUTED,
    SERIF,
    button,
    category_badge,
    fmt_date,
    heading,
    kicker,
    render_shell,
)
from warn_v2.states import state_name

log = logging.getLogger(__name__)

_MAX_PER_DIGEST = 50


def new_notices_for(db: Session, sub: Subscription) -> list[Notice]:
    """Non-superseded notices discovered since the subscription's watermark."""
    since = sub.last_notified_at or sub.created_at
    stmt = (
        select(Notice)
        .where(Notice.is_superseded.is_(False), Notice.scraped_at > since)
        .order_by(Notice.notice_date.desc().nullslast(), Notice.scraped_at.desc())
    )
    stmt = apply_notice_filters(
        stmt,
        state=sub.state,
        employer=sub.employer_query,
        industry=sub.industry,
        subsector=sub.subsector,
        min_layoffs=sub.min_layoffs,
        closure_category=sub.closure_category,
    )
    return list(db.scalars(stmt.limit(_MAX_PER_DIGEST)))


def _notice_row(x: Notice, base: str) -> str:
    """One row per notice, laid out like the site's notice list: employer
    (linked) + badge over state · date, and the worker count on the right."""
    url = escape(f"{base}/notices/{x.notice_id}")
    badge = category_badge(x.closure_category)
    meta = " &#183; ".join(
        part
        for part in (
            escape(state_name(x.state) or x.state) if x.state else "",
            fmt_date(x.notice_date),
        )
        if part
    )
    workers = (
        f'<span style="{SERIF};font-size:18px;font-weight:bold;color:{INK};">'
        f"{x.layoff_count:,}</span><br>"
        f'<span style="{FONT};font-size:11px;color:{MUTED};">workers</span>'
        if x.layoff_count
        else ""
    )
    return (
        "<tr>"
        f'<td style="padding:14px 0 14px 32px;border-bottom:1px solid {HAIRLINE};{FONT};">'
        f'<a href="{url}" style="font-size:15px;font-weight:bold;'
        f'color:{INK};text-decoration:none;">{escape(x.employer)}</a>'
        f"{'&nbsp;' + badge if badge else ''}<br>"
        f'<span style="font-size:13px;line-height:20px;color:{MUTED};">{meta}</span></td>'
        f'<td align="right" valign="top" style="padding:14px 32px 14px 12px;'
        f'border-bottom:1px solid {HAIRLINE};line-height:18px;white-space:nowrap;">'
        f"{workers}</td></tr>"
    )


def render_digest(sub: Subscription, notices: list[Notice]) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for a digest email."""
    base = site_base_url()
    scope = describe_scope(sub)
    n = len(notices)
    plural = "s" if n != 1 else ""
    subject = f"WARN Index: {n} new {scope} layoff notice{plural}"
    unsub = unsubscribe_url(sub, base)
    manage = manage_url(sub, base)

    text_lines = [f"{n} new WARN notice{plural} ({scope}):", ""]
    for x in notices:
        loc = f" — {x.state}" if x.state else ""
        affected = f" ({x.layoff_count:,} affected)" if x.layoff_count else ""
        when = x.notice_date.isoformat() if x.notice_date else ""
        text_lines.append(f"- {x.employer}{loc}{affected} {when}\n  {base}/notices/{x.notice_id}")
    text_lines += ["", f"Manage your alerts: {manage}", f"Unsubscribe: {unsub}"]

    # employer/scope are scraped/user-supplied — escape anything dynamic that
    # lands in the HTML alternative; the text alternative above stays raw.
    total_affected = sum(x.layoff_count or 0 for x in notices)
    affected_frag = (
        f" &#183; {total_affected:,} workers affected (where reported)" if total_affected else ""
    )
    rows = "".join(_notice_row(x, base) for x in notices)
    if n == _MAX_PER_DIGEST:
        # The query is LIMITed, so the true total is unknown — don't claim one.
        rows += (
            f'<tr><td colspan="2" style="padding:14px 32px;{FONT};font-size:13px;'
            f'color:{MUTED};">'
            f"Showing the {_MAX_PER_DIGEST} most recent matches &mdash; there may be more. "
            "Use the button below to see everything.</td></tr>"
        )
    content = (
        f'<tr><td style="padding:32px 32px 8px;">'
        f"{kicker('New WARN filings')}"
        f"{heading(f'{n} new layoff notice{plural}')}"
        f'<p style="margin:8px 0 0;{FONT};font-size:14px;line-height:21px;color:{MUTED};">'
        f"{escape(scope)}{affected_frag}</p></td></tr>"
        '<tr><td style="padding:12px 0 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="border-top:1px solid {HAIRLINE};">'
        f"{rows}</table></td></tr>"
        f'<tr><td style="padding:28px 32px 32px;">'
        f"{button(notices_url(sub, base), 'View all matching notices')}</td></tr>"
    )
    footer = (
        "You're receiving this because you subscribed to WARN Index alerts "
        f"for {escape(scope)}.<br>"
        f'<a href="{manage}" style="color:{MUTED};">Manage your alerts</a> &#183; '
        f'<a href="{unsub}" style="color:{MUTED};">Unsubscribe</a> &#183; '
        f'<a href="{base}/" style="color:{MUTED};">WARN Index</a>'
    )
    preheader = f"{n} new WARN notice{plural}"
    if notices:
        preheader += f": {notices[0].employer}" + (" and more" if n > 1 else "")
    preheader = escape(preheader)
    html_body = render_shell(preheader=preheader, content=content, footer=footer, base=base)
    return subject, "\n".join(text_lines), html_body


def send_digest(db: Session, sub: Subscription, now: datetime) -> int:
    """Send one subscription's digest if it has new matches; advance watermark.

    Commits on success so each subscriber's watermark is durable independently —
    a later subscriber's send failing won't roll back or re-send earlier ones.
    Returns the number of notices sent (0 = nothing new, no email sent).
    """
    notices = new_notices_for(db, sub)
    if not notices:
        return 0
    subject, text_body, html_body = render_digest(sub, notices)
    send_email(
        sub.email,
        subject,
        text_body,
        html_body,
        unsubscribe_url=unsubscribe_url(sub, site_base_url()),
    )
    sub.last_notified_at = now
    db.commit()
    return len(notices)


def run_digest(db: Session, now: datetime) -> dict[str, int]:
    """Process every confirmed subscription, isolating per-subscription failures.

    A send error (e.g. SMTP hiccup) is logged and skipped without advancing that
    subscription's watermark, so it retries next run; other subscribers are
    unaffected. Weekly subscriptions are skipped on the runs where they aren't
    yet due (see ``is_due``).
    """
    subs = list(db.scalars(select(Subscription).where(Subscription.confirmed_at.is_not(None))))
    sent = 0
    notices_total = 0
    failed = 0
    not_due = 0
    for sub in subs:
        if not is_due(sub, now):
            not_due += 1
            continue
        try:
            count = send_digest(db, sub, now)
        except Exception:
            db.rollback()
            failed += 1
            log.warning("digest send failed for subscription %s", sub.id, exc_info=True)
            continue
        if count:
            sent += 1
            notices_total += count
    return {
        "subscriptions": len(subs),
        "emailed": sent,
        "notices": notices_total,
        "failed": failed,
        "not_due": not_due,
    }
