"""Pure helpers describing an email-alert subscription: scope label, links, cadence.

Lives outside both ``warn_v2.api`` and ``warn_v2.notifications`` because both
need it — the digest to write its subject/footer, the subscriptions API to name
an alert in the management UI — and ``notifications.digest`` already imports
from ``warn_v2.api``, so putting them there would make the API package import
itself in a cycle. Nothing here touches the DB session or the request.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from warn_v2.companies.naics import SECTOR_NAME, subsector_name
from warn_v2.db.models import Subscription
from warn_v2.states import state_name

# How long a "weekly" subscriber waits between digests. The CronJob still runs
# daily; weekly subscriptions simply aren't due on most of those runs.
WEEKLY_INTERVAL = timedelta(days=7)


def is_due(sub: Subscription, now: datetime) -> bool:
    """Whether this subscription should be considered by a digest run now.

    Daily subscriptions are always due. A weekly one is due only once its
    watermark is a week old — so a weekly subscriber gets at most one digest a
    week no matter how often the job runs.
    """
    if sub.frequency != "weekly":
        return True
    last = sub.last_notified_at or sub.created_at
    if last is None:
        return True
    if last.tzinfo is None:  # SQLite round-trips naive datetimes
        last = last.replace(tzinfo=UTC)
    return now - last >= WEEKLY_INTERVAL


def describe_scope(sub: Subscription) -> str:
    """Short human label for a subscription's filters ("all US" when it has none).

    Used in the digest subject/footer and by the API so the manage UI names an
    alert exactly the way its emails do. Raw (unescaped) — HTML callers escape.
    """
    parts = []
    if sub.state:
        parts.append(state_name(sub.state) or sub.state)
    if sub.subsector:
        parts.append(subsector_name(sub.subsector) or f"NAICS {sub.subsector}")
    elif sub.industry:
        parts.append(SECTOR_NAME.get(sub.industry) or f"industry {sub.industry}")
    if sub.closure_category:
        parts.append(sub.closure_category.lower() + "s")
    if sub.min_layoffs:
        parts.append(f"{sub.min_layoffs:,}+ affected")
    if sub.employer_query:
        parts.append(f'"{sub.employer_query}"')
    return ", ".join(parts) if parts else "all US"


def unsubscribe_url(sub: Subscription, base: str) -> str:
    """The GET/POST unsubscribe link for this subscription."""
    return f"{base}/api/subscriptions/unsubscribe?token={sub.unsubscribe_token}"


def manage_url(sub: Subscription, base: str) -> str:
    """The alert-management link for this subscription's email address.

    Deliberately carries ``manage_token`` and not ``unsubscribe_token``: the
    latter ships in List-Unsubscribe headers that mail providers fetch on their
    own, so it must not double as an editing credential.
    """
    return f"{base}/alerts?token={sub.manage_token}"


def notices_url(sub: Subscription, base: str) -> str:
    """Deep link to the notices list pre-filtered to the subscription's scope."""
    params = {
        "state": sub.state,
        "employer": sub.employer_query,
        "industry": sub.industry,
        "subsector": sub.subsector,
        "closure_category": sub.closure_category,
        "min_layoffs": str(sub.min_layoffs) if sub.min_layoffs else None,
    }
    qs = urlencode({k: v for k, v in params.items() if v})
    return f"{base}/notices?{qs}" if qs else f"{base}/notices"
