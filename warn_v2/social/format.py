"""Post text for one notice. Plain text: neither Bluesky nor the webhooks
render Markdown consistently, and Bluesky caps a post at 300 graphemes."""
from __future__ import annotations

from warn_v2.api.seo import site_base_url
from warn_v2.closure import closure_label
from warn_v2.companies.naics import (
    SECTOR_NAME,
    industry_trusted,
    sector_for_code,
    subsector_for_code,
    subsector_name,
)
from warn_v2.db.models import Company, Notice
from warn_v2.notifications.templates import fmt_date
from warn_v2.states import state_name

# Bluesky's limit is 300 graphemes. len() counts code points, which is never
# fewer than graphemes, so staying under 300 code points is always safe.
MAX_POST_CHARS = 300
# Most NAICS titles fit; the rare longer one is cut with an ellipsis.
MAX_INDUSTRY_CHARS = 60

# Added to Bluesky posts only, so keyword and hashtag feeds pick them up.
# Bluesky needs a tag facet for each (bluesky.tag_facets); chat webhooks
# get no hashtags.
BLUESKY_HASHTAGS = ("#layoffs", "#WARNAct")


def notice_url(notice: Notice) -> str:
    return f"{site_base_url()}/notices/{notice.notice_id}"


def place(notice: Notice) -> str:
    loc = notice.location
    local = (loc.city or loc.county) if loc else None
    return f"{local}, {notice.state}" if local else (state_name(notice.state) or notice.state)


def _trusted_label(company: Company | None) -> str | None:
    """The company's NAICS label, most specific first, if we'd stand behind it.

    Only an exact enrichment match (confidence 1.00) or a code from the filing
    itself (never enriched, so no confidence). Below 1.00 the labels are mostly
    wrong in a public post (a casino show as "Grantmaking Foundations"), and
    sector 99 is "Unclassified Establishments", which says nothing.
    """
    if company is None or not company.naics_code or company.naics_code.startswith("99"):
        return None
    if not industry_trusted(company.enrichment_confidence):
        return None
    if company.naics_desc:
        return company.naics_desc
    code = company.naics_code
    return subsector_name(subsector_for_code(code)) or SECTOR_NAME.get(
        sector_for_code(code) or ""
    )


def industry(notice: Notice) -> str | None:
    """The company's trusted NAICS industry label, or None. A merged duplicate
    without one of its own uses its canonical's."""
    company = notice.company
    return _trusted_label(company) or _trusted_label(company and company.canonical)


def render_post(notice: Notice, hashtags: tuple[str, ...] = ()) -> str:
    """The alert text; the notice URL is always the last line, with any
    `hashtags` on the line before it. The employer name is truncated with an
    ellipsis when the post would run over the limit."""
    count = f"{notice.layoff_count:,}" if notice.layoff_count is not None else "Not published"
    effective = fmt_date(notice.effective_date) or "Pending"
    tags = f"{' '.join(hashtags)}\n" if hashtags else ""
    label = industry(notice)
    if label and len(label) > MAX_INDUSTRY_CHARS:
        # Employer truncation alone can't absorb an arbitrarily long label.
        label = label[: MAX_INDUSTRY_CHARS - 1].rstrip() + "…"
    industry_line = f"• Industry: {label}\n" if label else ""

    def build(employer: str) -> str:
        return (
            f"🚨 WARN notice: {employer} ({notice.state})\n\n"
            f"• Workers affected: {count}\n"
            f"• Action: {closure_label(notice.closure_category)}\n"
            f"{industry_line}"
            f"• Location: {place(notice)}\n"
            f"• Effective: {effective}\n\n"
            f"{tags}"
            f"{notice_url(notice)}"
        )

    employer = " ".join(notice.employer.split())
    text = build(employer)
    over = len(text) - MAX_POST_CHARS
    if over > 0:
        text = build(employer[: max(len(employer) - over - 1, 1)].rstrip() + "…")
    return text
