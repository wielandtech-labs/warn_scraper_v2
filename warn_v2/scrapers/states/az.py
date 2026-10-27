"""Arizona WARN scraper — JobLink platform.

Historical backfill (Jul 2003 - 2007): before JobLink (whose search reaches
2010), AZ DES published a monthly "Dislocated Worker Program" report as PDF,
monthly files Jul-2003 → May-2005 and one file per year for 2006 and 2007
(pinned Wayback captures, ``_ARCHIVE_PDFS``). See ``parse_az_archive_pdf``.
"""
from __future__ import annotations

import calendar
import io
import re
from datetime import date

import pdfplumber

from warn_v2.scrapers._helpers import as_date, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed
from warn_v2.scrapers.job_link import JobLinkScraper
from warn_v2.scrapers.registry import register
from warn_v2.scrapers.wayback import fetch as wayback_fetch
from warn_v2.scrapers.wayback import replay_url


class AZScraper(JobLinkScraper):
    state = "AZ"
    host = "www.azjobconnection.gov"
    # AZ averages ~22 notices/yr per the V1 sheet; widen to absorb spike years.
    expected_row_range = (1, 500)


register(AZScraper())


# ---------------------------------------------------------------------------
# Historical backfill (Jul 2003 - 2007) — DES monthly report PDFs via Wayback
# ---------------------------------------------------------------------------

_MONTHLY = "http://www.azdes.gov/wia/warn/{}"
_ANNUAL = (
    "https://www.azdes.gov/uploadedFiles/Employment_and_Rehabilitation_Services/"
    "Employment_Administration/{}"
)
# year → pinned (timestamp, url). Nothing is archived for Jun - Dec 2005, and
# 2008 survives only as undated alert/notice lists (no notice dates), so the
# archive ends at 2007; JobLink's search starts at 2010.
_ARCHIVE_PDFS: dict[int, list[tuple[str, str]]] = {
    2003: [
        ("20060925140109", _MONTHLY.format("July%202003.pdf")),
        ("20060925140230", _MONTHLY.format("August%202003.pdf")),
        ("20060925135836", _MONTHLY.format("September%202003.pdf")),
        ("20060925140300", _MONTHLY.format("October%202003.pdf")),
        ("20060925140121", _MONTHLY.format("November%202003.pdf")),
        ("20060925140013", _MONTHLY.format("December%202003.pdf")),
    ],
    2004: [
        ("20060925140239", _MONTHLY.format("jan2004.pdf")),
        ("20060925140340", _MONTHLY.format("feb2004.pdf")),
        ("20060925140140", _MONTHLY.format("mar2004.pdf")),
        ("20060925140133", _MONTHLY.format("april2004.pdf")),
        ("20060925135830", _MONTHLY.format("may2004.pdf")),
        ("20060925140125", _MONTHLY.format("june2004.pdf")),
        ("20060925140336", _MONTHLY.format("july2004.pdf")),
        ("20060925140032", _MONTHLY.format("august2004.pdf")),
        ("20060925140027", _MONTHLY.format("sept2004.pdf")),
        ("20060925140129", _MONTHLY.format("oct2004.pdf")),
        ("20060925140037", _MONTHLY.format("nov2004.pdf")),
        ("20060925140046", _MONTHLY.format("dec2004.pdf")),
    ],
    2005: [
        ("20060925140116", _MONTHLY.format("jan2005.pdf")),
        ("20060925140254", _MONTHLY.format("feb2005.pdf")),
        ("20060925140157", _MONTHLY.format("mar2005.pdf")),
        ("20060925140359", _MONTHLY.format("april2005.pdf")),
        ("20060925140018", _MONTHLY.format("may2005.pdf")),
    ],
    2006: [("20100202215218", _ANNUAL.format("warn_2006.pdf"))],
    2007: [("20100202215235", _ANNUAL.format("warn_2007.pdf"))],
}
ARCHIVE_LAST_YEAR = max(_ARCHIVE_PDFS)

_MONTHS = {calendar.month_name[i].upper(): i for i in range(1, 13)}
_MONTH_RE = re.compile(r"MONTH OF\s+([A-Z]+)\W+(\d{4})")
# Full dates, or month-only with a 4-digit year ("08/2004"); a bare "6/11"
# in a "6/11-7/9-8/6/2004" range must not parse as a date in the current year.
_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}/\d{4}")
_ADDRESS_RE = re.compile(r"^(\d|P\.?\s*O\.?\s*Box)", re.I)
_CITY_RE = re.compile(r"^(.+?),\s*(?:Arizona|AZ)\b", re.I)


def _source_url(year: int, month: int) -> str:
    """Replay URL of the file a (year, month) row came from: the year's only
    file for 2006-07, else the month's own file (listed in month order)."""
    caps = _ARCHIVE_PDFS[year]
    first_month = 7 if year == 2003 else 1
    ts, url = caps[0] if len(caps) == 1 else caps[month - first_month]
    return replay_url(ts, url)


def fetch_az_archive_year(year: int) -> list[bytes] | None:
    """The year's pinned DES report PDFs, or None outside 2003-2007."""
    caps = _ARCHIVE_PDFS.get(year)
    if not caps:
        return None
    return [raw for ts, url in caps if (raw := wayback_fetch(replay_url(ts, url)))]


def parse_az_archive_pdf(raw: bytes, year: int) -> list[NoticeRow]:
    """Parse one DES "Dislocated Worker Program" report PDF.

    Each page names its report month ("MONTH OF MAY 2004"); the DATE column is
    the layoff date, so the notice date is the report month's first day.
    Rows are typed by the source's own legend: W = "Employers WARN Notices",
    A = a local-area alert, P = a plant-closure flag. Only W rows are WARN
    notices. A/P rows are skipped rather than tagged Non-WARN, because an A row
    often repeats a W row for the same layoff (Leggett & Platt, Jan 2007) and
    would collide with it on notice_id. In the 2006-07 files a row marked
    under "Prior Layoffs" re-lists an earlier notice and is skipped too; so
    are repeats marked NEW (see ``_merge_same_key``).

    The firm cell holds the employer, then address lines, then "City,
    Arizona". A cell that starts with an address continues the previous
    employer's multi-site notice (Chevron USA, Sep 2003). Several dates and
    counts stacked in one row are one notice: first date, summed counts.
    """
    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as exc:
        raise ParseFailed(f"AZ archive PDF: not a readable PDF: {exc}") from exc
    rows: list[NoticeRow] = []
    employer: str | None = None
    with pdf:
        for page in pdf.pages:
            m = _MONTH_RE.search(page.extract_text() or "")
            if not m or m.group(1) not in _MONTHS:
                continue
            notice_date = date(int(m.group(2)), _MONTHS[m.group(1)], 1)
            if notice_date.year != year:
                continue
            for table in page.extract_tables():
                head = [" ".join((c or "").upper().split()) for c in table[0]]
                firm_i = next((i for i, h in enumerate(head) if "FIRM" in h), None)
                type_i = next((i for i, h in enumerate(head) if h == "TYPE"), None)
                if firm_i is None or type_i is None:
                    continue
                date_i = next(i for i, h in enumerate(head) if "DAT" in h)
                count_i = next(i for i, h in enumerate(head) if "WORKERS" in h)
                prior_i = next((i for i, h in enumerate(head) if h.startswith("PRIOR")), None)
                for r in table[1:]:
                    lines = [ln.strip() for ln in (r[firm_i] or "").split("\n") if ln.strip()]
                    addr_at = next(
                        (i for i, ln in enumerate(lines) if _ADDRESS_RE.match(ln)), len(lines)
                    )
                    if lines and addr_at:
                        employer = " ".join(lines[:addr_at])
                    if (r[type_i] or "").strip() != "W" or not employer:
                        continue
                    if prior_i is not None and (r[prior_i] or "").strip():
                        continue
                    city = next(
                        (c.group(1) for ln in lines if (c := _CITY_RE.match(ln))), None
                    )
                    d = _DATE_RE.search(r[date_i] or "")
                    counts = [int(n) for n in re.findall(r"\d+", r[count_i] or "")]
                    rows.append(
                        NoticeRow(
                            state="AZ",
                            employer=employer,
                            notice_date=notice_date,
                            effective_date=as_date(d.group(0)) if d else None,
                            layoff_count=sum(counts) if counts else None,
                            city=as_str(city),
                            source_url=_source_url(year, notice_date.month),
                        )
                    )
    return _merge_same_key(rows)


def _merge_same_key(rows: list[NoticeRow]) -> list[NoticeRow]:
    """Collapse rows that are one notice or would collide on notice_id.

    The 2006-07 files re-list ongoing events month after month, even marked
    NEW (Qwest Phoenix, 367 workers: Sep, Oct and Nov 2006), so a repeat of
    the same employer, layoff date, count and city keeps only its first
    (earliest) month. Rows that still share employer, report month and city
    are distinct filings that would collide on notice_id (Chevron USA's three
    Phoenix sites, Sep 2003), so they merge: summed counts, earliest layoff
    date.
    """
    first_month: dict[tuple, date] = {}
    merged: dict[tuple, NoticeRow] = {}
    for r in rows:
        emp = " ".join(r.employer.lower().split())
        relisting = (emp, r.effective_date, r.layoff_count, (r.city or "").lower())
        # Only a later month re-lists; two same-month sites can match exactly.
        if first_month.setdefault(relisting, r.notice_date) < r.notice_date:
            continue
        key = (emp, r.notice_date, (r.city or "").lower())
        prev = merged.get(key)
        if prev is None:
            merged[key] = r
            continue
        if r.layoff_count is not None:
            prev.layoff_count = (prev.layoff_count or 0) + r.layoff_count
        dates = [d for d in (prev.effective_date, r.effective_date) if d]
        prev.effective_date = min(dates) if dates else None
    return list(merged.values())
