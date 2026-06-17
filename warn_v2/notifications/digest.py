"""Build and send alert digests for confirmed subscriptions.

Separated from the HTTP routes so the CLI (``warn-v2 send-alert-digest``) and
tests can drive it directly. A digest contains the notices discovered
(``scraped_at``) since the subscription's watermark that match its filters; the
watermark is advanced to ``now`` after a successful send.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.api.filters import apply_notice_filters
from warn_v2.api.seo import site_base_url
from warn_v2.db.models import Notice, Subscription
from warn_v2.notifications.email import send_email
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


def render_digest(sub: Subscription, notices: list[Notice]) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for a digest email."""
    base = site_base_url()
    scope = _describe(sub)
    n = len(notices)
    subject = f"WARN Tracker: {n} new {scope} layoff notice{'s' if n != 1 else ''}"
    unsub = f"{base}/api/subscriptions/unsubscribe?token={sub.unsubscribe_token}"

    text_lines = [f"{n} new WARN notice{'s' if n != 1 else ''} ({scope}):", ""]
    html_items = []
    for x in notices:
        loc = f" — {x.state}" if x.state else ""
        affected = f" ({x.layoff_count:,} affected)" if x.layoff_count else ""
        when = x.notice_date.isoformat() if x.notice_date else ""
        url = f"{base}/notices/{x.notice_id}"
        text_lines.append(f"- {x.employer}{loc}{affected} {when}\n  {url}")
        html_items.append(
            f'<li><a href="{url}">{x.employer}</a>{loc}{affected} '
            f'<span style="color:#64748b">{when}</span></li>'
        )
    text_lines += ["", f"Unsubscribe: {unsub}"]
    html_body = (
        f"<p>{n} new WARN notice{'s' if n != 1 else ''} ({scope}):</p>"
        f"<ul>{''.join(html_items)}</ul>"
        f'<p style="color:#64748b;font-size:12px">'
        f'<a href="{unsub}">Unsubscribe</a></p>'
    )
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
    send_email(sub.email, subject, text_body, html_body)
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
