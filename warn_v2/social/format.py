"""Post text for one notice. Plain text: neither Bluesky nor the webhooks
render Markdown consistently, and Bluesky caps a post at 300 graphemes."""
from __future__ import annotations

from warn_v2.api.seo import site_base_url
from warn_v2.closure import closure_label
from warn_v2.db.models import Notice
from warn_v2.notifications.templates import fmt_date
from warn_v2.states import state_name

# Bluesky's limit is 300 graphemes. len() counts code points, which is never
# fewer than graphemes, so staying under 300 code points is always safe.
MAX_POST_CHARS = 300


def notice_url(notice: Notice) -> str:
    return f"{site_base_url()}/notices/{notice.notice_id}"


def place(notice: Notice) -> str:
    loc = notice.location
    local = (loc.city or loc.county) if loc else None
    return f"{local}, {notice.state}" if local else (state_name(notice.state) or notice.state)


def render_post(notice: Notice) -> str:
    """The alert text; the notice URL is always the last line. The employer
    name is truncated with an ellipsis when the post would run over the limit."""
    count = f"{notice.layoff_count:,}" if notice.layoff_count is not None else "Not published"
    effective = fmt_date(notice.effective_date) or "Pending"

    def build(employer: str) -> str:
        return (
            f"🚨 WARN notice: {employer} ({notice.state})\n\n"
            f"• Workers affected: {count}\n"
            f"• Action: {closure_label(notice.closure_category)}\n"
            f"• Location: {place(notice)}\n"
            f"• Effective: {effective}\n\n"
            f"{notice_url(notice)}"
        )

    employer = " ".join(notice.employer.split())
    text = build(employer)
    over = len(text) - MAX_POST_CHARS
    if over > 0:
        text = build(employer[: max(len(employer) - over - 1, 1)].rstrip() + "…")
    return text
