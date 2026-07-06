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
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.api.filters import apply_notice_filters
from warn_v2.api.seo import site_base_url
from warn_v2.db.models import Notice, Subscription
from warn_v2.notifications.email import send_email
from warn_v2.notifications.templates import FONT, button, category_badge, fmt_date, render_shell
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
        stmt, state=sub.state, employer=sub.employer_query, industry=sub.industry
    )
    return list(db.scalars(stmt.limit(_MAX_PER_DIGEST)))


def _describe(sub: Subscription) -> str:
    parts = []
    if sub.state:
        parts.append(state_name(sub.state) or sub.state)
    if sub.industry:
        parts.append(f"industry {sub.industry}")
    if sub.employer_query:
        parts.append(f'"{sub.employer_query}"')
    return ", ".join(parts) if parts else "all US"


def unsubscribe_url(sub: Subscription, base: str) -> str:
    """The GET/POST unsubscribe link for this subscription."""
    return f"{base}/api/subscriptions/unsubscribe?token={sub.unsubscribe_token}"


def _notices_url(sub: Subscription, base: str) -> str:
    """Deep link to the notices list pre-filtered to the subscription's scope."""
    params = {"state": sub.state, "employer": sub.employer_query, "industry": sub.industry}
    qs = urlencode({k: v for k, v in params.items() if v})
    return f"{base}/notices?{qs}" if qs else f"{base}/notices"


def _notice_row(x: Notice, base: str) -> str:
    """One table row per notice: employer link, badge, state · date · affected."""
    url = escape(f"{base}/notices/{x.notice_id}")
    badge = category_badge(x.closure_category)
    meta = " &#183; ".join(
        part
        for part in (
            escape(state_name(x.state) or x.state) if x.state else "",
            fmt_date(x.notice_date),
            f"{x.layoff_count:,} affected" if x.layoff_count else "",
        )
        if part
    )
    return (
        f'<tr><td style="padding:12px 24px;border-bottom:1px solid #e2e8f0;{FONT};">'
        f'<a href="{url}" style="font-size:15px;font-weight:bold;'
        f'color:#0369a1;text-decoration:none;">{escape(x.employer)}</a>'
        f"{'&nbsp;' + badge if badge else ''}<br>"
        f'<span style="font-size:13px;line-height:20px;color:#64748b;">{meta}</span></td></tr>'
    )


def render_digest(sub: Subscription, notices: list[Notice]) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for a digest email."""
    base = site_base_url()
    scope = _describe(sub)
    n = len(notices)
    plural = "s" if n != 1 else ""
    subject = f"WARN Tracker: {n} new {scope} layoff notice{plural}"
    unsub = unsubscribe_url(sub, base)

    text_lines = [f"{n} new WARN notice{plural} ({scope}):", ""]
    for x in notices:
        loc = f" — {x.state}" if x.state else ""
        affected = f" ({x.layoff_count:,} affected)" if x.layoff_count else ""
        when = x.notice_date.isoformat() if x.notice_date else ""
        text_lines.append(f"- {x.employer}{loc}{affected} {when}\n  {base}/notices/{x.notice_id}")
    text_lines += ["", f"Unsubscribe: {unsub}"]

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
            f'<tr><td style="padding:12px 24px;{FONT};font-size:13px;color:#64748b;">'
            f"Showing the {_MAX_PER_DIGEST} most recent matches &mdash; there may be more. "
            "Use the button below to see everything.</td></tr>"
        )
    content = (
        f'<tr><td style="padding:24px 24px 4px;{FONT};">'
        f'<p style="margin:0;font-size:20px;font-weight:bold;color:#0f172a;">'
        f"{n} new layoff notice{plural}</p>"
        f'<p style="margin:4px 0 0;font-size:14px;color:#64748b;">'
        f"{escape(scope)}{affected_frag}</p></td></tr>"
        '<tr><td style="padding:12px 0 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f"{rows}</table></td></tr>"
        f'<tr><td align="center" style="padding:24px;">'
        f"{button(_notices_url(sub, base), 'View all matching notices')}</td></tr>"
    )
    footer = (
        "You're receiving this because you subscribed to WARN Tracker alerts "
        f"for {escape(scope)}.<br>"
        f'<a href="{unsub}" style="color:#64748b;">Unsubscribe</a> &#183; '
        f'<a href="{base}/" style="color:#64748b;">WARN Tracker</a>'
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
    unaffected.
    """
    subs = list(db.scalars(select(Subscription).where(Subscription.confirmed_at.is_not(None))))
    sent = 0
    notices_total = 0
    failed = 0
    for sub in subs:
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
    }
