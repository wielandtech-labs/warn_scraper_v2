"""Ingest historical WARN data for states where the regular scraper only fetches
the current year.

Each supported state has a ``BackfillSpec`` in ``_BACKFILL`` describing one of
two fetch shapes:

* **year loop** (``fetch_year``) — fetch one year at a time from ``year_start``
  to the current year. ``fetch_year(scraper, year)`` returns raw bytes, a list
  of raw chunks (paginated sources), or ``None`` when the year has no data.
* **archive-file list** (``discover_urls``) — discover historical file URLs
  from an archive page and ingest each one (CA). ``parse_for_url`` may return
  an alternate parser for a given URL (e.g. PDF-era files).

Per-state fetch/parse helpers live next to the regular scraper in
``warn_v2/scrapers/states/<st>.py`` (see ``ca._discover_archive_urls``,
``dc._fetch_dc_year``); this module holds only the registry and the loops.

Dry runs log a duplicate preview: rows already in the DB, rows that would
insert, and *near misses* — rows matching an existing notice on
(state, employer, notice_date) but hashing to a different ``notice_id``
(usually city/ZIP drift between a historical format and the live one). Near
misses become duplicates on a real run; review them and plan a
``mark-superseded --state XX`` pass before committing.

Usage::

    warn-v2 backfill-historical --state CA
    warn-v2 backfill-historical --state DC --year-start 2013
    warn-v2 backfill-historical --state VT --dry-run
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import select

from warn_v2.db.models import Notice, ScraperRun
from warn_v2.db.session import session_scope
from warn_v2.pipeline.dedup import _norm, notice_id
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states.ca import (
    _CA_DETAIL_RE,
    _discover_archive_urls,
    _discover_ca_historical_urls,
    parse_ca_detail_pdf,
    parse_ca_pdf,
)
from warn_v2.scrapers.states.co import _fetch_co_year, _parse_co_year
from warn_v2.scrapers.states.ct import _discover_ct_archive_urls, parse_ct_archive
from warn_v2.scrapers.states.dc import _fetch_dc_year
from warn_v2.scrapers.states.fl import _fetch_fl_year, parse_fl_year
from warn_v2.scrapers.states.ga import ga_archive_files, parse_ga_entry_page
from warn_v2.scrapers.states.hi import _fetch_hi_year
from warn_v2.scrapers.states.ia import ia_archive_files, parse_ia_archive_pdf
from warn_v2.scrapers.states.id import id_archive_files, parse_id_2008_pdf
from warn_v2.scrapers.states.il import _discover_archive_pdf_urls as _discover_il_pdf_urls
from warn_v2.scrapers.states.il import _discover_archive_xlsx_urls as _discover_il_xlsx_urls
from warn_v2.scrapers.states.il import parse_il_pdf
from warn_v2.scrapers.states.in_ import _discover_in_archive_urls, parse_in_archive_html
from warn_v2.scrapers.states.ky import ky_archive_files, parse_ky_workbook
from warn_v2.scrapers.states.la import _fetch_la_year, parse_la_pdf
from warn_v2.scrapers.states.la import _source_url as _la_source_url
from warn_v2.scrapers.states.ma import ma_archive_files, parse_ma_archive_member
from warn_v2.scrapers.states.md import _fetch_md_year
from warn_v2.scrapers.states.mi import (
    _discover_mi_archive_urls,
    parse_mi_archive_html,
    parse_mi_archive_pdf,
)
from warn_v2.scrapers.states.mn import (
    _discover_archive_pdf_urls as _discover_mn_pdf_urls,
)
from warn_v2.scrapers.states.mn import (
    _parse_archive_pdf as _parse_mn_archive_pdf,
)
from warn_v2.scrapers.states.mo import (
    _discover_mo_archive_urls,
    parse_mo_archive_html,
    parse_mo_log_pdf,
)
from warn_v2.scrapers.states.ms import _discover_pdf_urls as _discover_ms_pdf_urls
from warn_v2.scrapers.states.nc import _discover_nc_pdf_urls, parse_nc_pdf
from warn_v2.scrapers.states.ne import ne_archive_files, parse_ne_archive
from warn_v2.scrapers.states.nj import ARCHIVE_XLSX_URL as _NJ_ARCHIVE_XLSX_URL
from warn_v2.scrapers.states.nj import parse_nj_archive_xlsx
from warn_v2.scrapers.states.nm import _discover_archive_pdf_urls as _discover_nm_pdf_urls
from warn_v2.scrapers.states.nv import _fetch_nv_year, parse_nv_archive
from warn_v2.scrapers.states.ny import ny_history_csv
from warn_v2.scrapers.states.oh import _fetch_oh_year, parse_oh_year
from warn_v2.scrapers.states.pa import _fetch_pa_year, parse_pa_month
from warn_v2.scrapers.states.sd import parse_sd_archive_pdf, sd_archive_files
from warn_v2.scrapers.states.tx import _fetch_tx_year
from warn_v2.scrapers.states.wi import _fetch_wi_archive_year, parse_wi_archive_html
from warn_v2.scrapers.states.wv import parse_wv_archive_pdf, wv_archive_files

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillSpec:
    """How to backfill one state. Set either ``fetch_year`` or ``discover_urls``."""

    # Mode 1 — year loop:
    year_start: int | None = None
    fetch_year: Callable[..., bytes | list[bytes] | None] | None = None
    # Optional parser that needs the year for context (e.g. month-only sources).
    parse_year: Callable[[bytes, int], list[NoticeRow]] | None = None

    # Mode 2 — archive-file list:
    discover_urls: Callable[[], list[str]] | None = None
    parse_for_url: Callable[[str], Callable | None] | None = None

    # Mode 3 — bundled snapshot: a one-time historical export committed to the
    # repo (e.g. NY's full Tableau crosstab). Returns raw bytes for the
    # state's own ``scraper.parse``.
    bundled_bytes: Callable[[], bytes] | None = None

    # Mode 3b — bundled multi-file snapshot: raw source files committed as a
    # tar.gz under warn_v2/scrapers/data/ (see warn_v2.scrapers.bundled).
    # Returns (member_name, bytes) pairs; each member is parsed via
    # ``parse_for_url(member_name)`` when set, else ``scraper.parse``.
    bundled_files: Callable[[], list[tuple[str, bytes]]] | None = None


def _joblink_fetch(scraper, year: int) -> bytes:
    """JobLink platform: the base class supports fetch(year=Y) directly."""
    return scraper.fetch(year=year)


# Lambdas resolve module globals at call time so tests can patch
# `backfill_historical._fetch_dc_year` / `._discover_archive_urls` /
# `.parse_ca_pdf` exactly as before the registry rewrite.
_BACKFILL: dict[str, BackfillSpec] = {
    # CA: the live archive page (FY2014+ PDFs → parse_ca_pdf) plus the pre-FY2014
    # detailed reports recovered from the Wayback Machine (→ parse_ca_detail_pdf,
    # url-aware so rows carry the replay source_url). Detailed URLs are matched by
    # filename; everything else .pdf falls to the current-year parser.
    "CA": BackfillSpec(
        discover_urls=lambda: _discover_archive_urls() + _discover_ca_historical_urls(),
        parse_for_url=lambda u: (
            (lambda raw, _u=u: parse_ca_detail_pdf(raw, _u))
            if _CA_DETAIL_RE.search(u)
            else parse_ca_pdf
            if u.lower().endswith(".pdf")
            else None
        ),
    ),
    # CT: retired ctdol.state.ct.us HTML report pages 1998-2018 via 142 pinned
    # Wayback captures (monthly pages 1998-2009, cumulative yearly 2010-2018);
    # the live Azure document library only reaches back to 2019. Known source
    # holes (all of 2013; 2009 except Aug/Sep) need FOIA. ~150 Wayback fetches
    # at the throttled pace — budget several hours for the prod Job.
    "CT": BackfillSpec(
        discover_urls=lambda: _discover_ct_archive_urls(),
        parse_for_url=lambda u: (lambda raw, _u=u: parse_ct_archive(raw, _u)),
    ),
    "DC": BackfillSpec(year_start=2013, fetch_year=lambda s, y: _fetch_dc_year(y)),
    # CO: one Google Sheet per year, 2015+; the regular scraper reads only the
    # two newest. _parse_co_year skips the scraper's staleness guard.
    "CO": BackfillSpec(
        year_start=2015,
        fetch_year=lambda s, y: _fetch_co_year(y),
        parse_year=lambda b, y: _parse_co_year(b, y),
    ),
    # JobLink platforms verified searchable to these years (2026-06-12 probes;
    # AZ/DE floors re-probed 2026-07-09 — pre-2016 data exists after all; see
    # docs/historical-sources.md).
    "AZ": BackfillSpec(year_start=2010, fetch_year=_joblink_fetch),
    "DE": BackfillSpec(year_start=2007, fetch_year=_joblink_fetch),
    "KS": BackfillSpec(year_start=1999, fetch_year=_joblink_fetch),
    "ME": BackfillSpec(year_start=2012, fetch_year=_joblink_fetch),
    "VT": BackfillSpec(year_start=2003, fetch_year=_joblink_fetch),
    # Year-URL sources, earliest years verified by 2026-06-12 probes.
    # TX: live per-year XLSX 2020+; 2004-2018 via pinned Wayback captures of
    # the removed twc files (.xls through 2013); 2019 via Socrata (see tx.py).
    "TX": BackfillSpec(year_start=2004, fetch_year=_fetch_tx_year),
    # FL: live reactwarn pages 2020+, pinned Wayback captures for the two
    # 2019 reactwarn result pages and the warn.asp era (1998-2018, one
    # cumulative page per year); parse_fl_year dispatches per era. The 2012
    # capture is header-only — that year parses to 0 rows.
    "FL": BackfillSpec(
        year_start=1998,
        fetch_year=_fetch_fl_year,
        parse_year=parse_fl_year,
    ),
    "HI": BackfillSpec(year_start=2019, fetch_year=lambda s, y: _fetch_hi_year(y)),
    # GA: the 31 GA2022* TCSG entry detail pages still served live 2026-07-10
    # (ids 071-103; 083/097 pruned at the source), bundled with the listing
    # JSON. These notices are already in prod at listing granularity
    # (employer + submitted date + count); the entry pages add county, street
    # address, closure type, and the first separation date. The parser keys
    # notice_date to the bundled listing so notice_id matches the stored rows
    # — expect ~31 COALESCE fills, ~0 inserts.
    "GA": BackfillSpec(
        bundled_files=ga_archive_files,
        parse_for_url=lambda u: parse_ga_entry_page,
    ),
    # IA: Iowa prunes old rows from its single cumulative log, so four archived
    # snapshots (2005-07..2023-08 union, no interior gaps) are bundled as a
    # tar.gz — the PDF-era member routes to parse_ia_archive_pdf, the XLSX
    # members reuse IAScraper.parse (legacy header labels are aliased there).
    "IA": BackfillSpec(
        bundled_files=ia_archive_files,
        parse_for_url=lambda name: (
            parse_ia_archive_pdf if name.lower().endswith(".pdf") else None
        ),
    ),
    # KY: bundled Wayback capture (20161222125836) of kcc.ky.gov's
    # 'WARN Report 2016.xlsx' — one sheet per year, WARN 1998-WARN 2016
    # (~780 rows); the pre-2017 history is gone from the live SharePoint
    # library. 2017-2024 is already in prod from the old live-workbook Mode-2
    # entry (run 2026-07-02); to re-run those years, restore it:
    #   BackfillSpec(discover_urls=lambda: ky._discover_workbook_urls(),
    #                parse_for_url=lambda u: parse_ky_workbook)
    "KY": BackfillSpec(
        bundled_files=ky_archive_files,
        parse_for_url=lambda u: parse_ky_workbook,
    ),
    # LA: per-year PDFs; laworks.net prunes old files (only 2025+ resolve
    # live), so 2007-2024 come from pinned Wayback captures of the same URLs
    # (la._WAYBACK_TS; rows carry the replay source_url). 2024 capture ends
    # Aug 12; pre-2007 → records request.
    "LA": BackfillSpec(
        year_start=2007,
        fetch_year=lambda s, y: _fetch_la_year(y),
        parse_year=lambda b, y: parse_la_pdf(b, _la_source_url(y)),
    ),
    # MA: bundled Wayback captures — the FY2020 report (legacy .xls, six
    # regional sheets, Jul 2019 - Jun 2020) plus the FY2021 weekly cumulative
    # through 2020-08-21. Sep 2020 - Mar 2021 and pre-FY2020 were never
    # archived (email-request only). This replaces the FY22-FY25 Playwright
    # year-loop spec, which ALREADY RAN in prod (floor 2021-04); to re-run
    # those fiscal years restore (helpers still live in states/ma.py):
    #   BackfillSpec(year_start=2022, fetch_year=lambda s, y: _fetch_ma_fy(y),
    #                parse_year=lambda b, y: parse_ma_xlsx(b, y))
    "MA": BackfillSpec(
        bundled_files=lambda: ma_archive_files(),
        parse_for_url=lambda n: parse_ma_archive_member(n),
    ),
    # NV: per-year archive PDFs 2017+ in three layout eras; 2021 is a scanned
    # image (parsed via the tesseract OCR fallback) and 2025 coverage ends
    # June 3 — see nv._ARCHIVE_SOURCES.
    "NV": BackfillSpec(
        year_start=2017,
        fetch_year=lambda s, y: _fetch_nv_year(y),
        parse_year=lambda b, y: parse_nv_archive(b, y),
    ),
    # NJ: one cumulative workbook, one sheet per year back to 2004; the live
    # scraper reads only the current-year PDF. Field semantics match the PDF
    # parser, so overlap years dedupe by notice_id.
    "NJ": BackfillSpec(
        discover_urls=lambda: [_NJ_ARCHIVE_XLSX_URL],
        parse_for_url=lambda u: parse_nj_archive_xlsx,
    ),
    # NC: per-year archive PDFs 2014+ discovered from the hub (irregular slugs).
    # Three layout eras; parse_nc_pdf dispatches on detected content. Capture
    # the URL so each PDF's parser records its own source_url.
    "NC": BackfillSpec(
        discover_urls=lambda: _discover_nc_pdf_urls(),
        parse_for_url=lambda u: (lambda raw, _u=u: parse_nc_pdf(raw, _u)),
    ),
    # NM: yearly PDFs back to 2016 with irregular filenames — discover from hub.
    "NM": BackfillSpec(discover_urls=lambda: _discover_nm_pdf_urls()),
    # MD: archived per-year pages warn{year}.shtml — 2010+ still live on
    # dllr.state.md.us; 2000-2009 were pruned and fetch from pinned Wayback
    # captures instead (numeric Type Codes + SIC-era codes handled in parse).
    "MD": BackfillSpec(year_start=2000, fetch_year=lambda s, y: _fetch_md_year(y)),
    # MI: milmi.org history via Wayback (michigan.gov purged pre-2025 from the
    # Sitecore index mid-2025; milmi.org/warn now redirects there and the
    # files 404 live). One archived HTML page carries the 2016-2024 year
    # tables; 16 annual PDFs cover 2000-2015. Static URL list — no discovery.
    # Archive rows carry the real filing date as notice_date, unlike the live
    # cards (layoff date), so the 2024-Q4 overlap with live rows will NOT
    # hash-dedupe — review it at dry-run time.
    "MI": BackfillSpec(
        discover_urls=lambda: _discover_mi_archive_urls(),
        parse_for_url=lambda u: (
            (lambda raw, _u=u: parse_mi_archive_pdf(raw, _u))
            if u.lower().endswith(".pdf")
            else (lambda raw, _u=u: parse_mi_archive_html(raw, _u))
        ),
    ),
    # WI: static per-year pages exist only 2016-2019; the cumulative Google
    # Sheet covers 2020+ via the regular scraper.
    "WI": BackfillSpec(
        year_start=2016,
        fetch_year=lambda s, y: _fetch_wi_archive_year(y),
        parse_year=lambda b, y: parse_wi_archive_html(b, y),
    ),
    # MN: DEED PDFs discovered via Wayback CDX (monthlies 2015-16 and 2022+,
    # annual summaries 2018-2021, cumulative yearly reports). MNScraper.parse
    # expects a JSON envelope — route raw PDF bytes to the archive parser,
    # which dispatches pre-2025 files to the word-position era parser.
    "MN": BackfillSpec(
        discover_urls=lambda: _discover_mn_pdf_urls(),
        parse_for_url=lambda u: (lambda raw, _u=u: _parse_mn_archive_pdf(raw, _u)),
    ),
    # MO: jobs.mo.gov purged its pre-2019 program-year pages (MO publishes by
    # Program Year, Jul-Jun); five static pinned Wayback captures hold a
    # consolidated Jul2012-Jun2015 log PDF, the PY2015 log PDF, and the
    # PY2016-PY2018 HTML pages — no runtime CDX. The regular scraper crawls
    # 2019-present every run and that data is complete, and the PY2018 page
    # runs into early 2019, so both archive parsers drop rows dated >= 2019-01-01.
    # Mid-PY captures leave gaps (Sep 2015-Jun 2016, May-Jun 2017,
    # Jan-Jun 2018 — see mo._ARCHIVE_CAPTURES); the Hostess Nov-2012 mass
    # closing lists several worksites per city, which collapse to one row per
    # (employer, date, city) under the notice_id hash.
    "MO": BackfillSpec(
        discover_urls=lambda: _discover_mo_archive_urls(),
        parse_for_url=lambda u: (
            (lambda raw, _u=u: parse_mo_log_pdf(raw, _u))
            if u.lower().endswith(".pdf")
            else (lambda raw, _u=u: parse_mo_archive_html(raw, _u))
        ),
    ),
    # MS: the landing page lists every quarterly PDF back to PY2020; the
    # regular scraper ingests only the most recent one.
    "MS": BackfillSpec(discover_urls=lambda: _discover_ms_pdf_urls()),
    # IL: monthly Excel files 2020+ plus the monthly PDF era 1999-2019 (a
    # labeled two-column form → parse_il_pdf; XLSX re-ingest is idempotent).
    "IL": BackfillSpec(
        discover_urls=lambda: _discover_il_xlsx_urls() + _discover_il_pdf_urls(),
        parse_for_url=lambda u: (
            (lambda raw, _u=u: parse_il_pdf(raw, _u))
            if u.lower().endswith(".pdf")
            else None
        ),
    ),
    # IN: 2000-2007 from three archived generations of the DWD listing via
    # pinned Wayback replay URLs (per-year tables 2000-2003, rolling
    # notices.html 2003-2004, accumulating warn_notices.html 2005-2007 — see
    # in_._IN_ARCHIVE_CAPTURES for why some captures are excluded). Known
    # gaps: Jan-Oct 2000, Nov-Dec 2004, Oct-Dec 2007. Prod IN data starts
    # 2008, so there is no overlap with live rows.
    "IN": BackfillSpec(
        discover_urls=lambda: _discover_in_archive_urls(),
        parse_for_url=lambda u: (lambda raw, _u=u: parse_in_archive_html(raw, _u)),
    ),
    # OH: four era formats back to 1996, mostly via Wayback replay (see
    # docs/historical-sources.md); 2025 has no known source anywhere.
    "OH": BackfillSpec(
        year_start=1996,
        fetch_year=lambda s, y: _fetch_oh_year(y),
        parse_year=lambda b, y: parse_oh_year(b, y),
    ),
    # NE: the legacy per-year report endpoint (?year=2010..2020) still serves
    # frozen HTML fragments; snapshotted 2026-07-10 and bundled as a tar.gz
    # (see states/ne.py). parse_ne_archive stamps each member's per-year
    # source URL. Prod floor is 2023 — no overlap. 2021-2022 rows exist only
    # in Wayback captures of the rolling live page — follow-up, not bundled.
    "NE": BackfillSpec(
        bundled_files=ne_archive_files,
        parse_for_url=lambda u: (lambda raw, _u=u: parse_ne_archive(raw, _u)),
    ),
    # SD: the frozen "WARN Notices Received" cumulative PDF (Jul-1997 →
    # Dec-2005, 60 notices) bundled from its Wayback capture; the live scraper
    # is HTML, so members route to the archive PDF parser. The 2006 → Apr-2007
    # gap is real (the successor page starts 05/2007).
    "SD": BackfillSpec(
        bundled_files=sd_archive_files,
        parse_for_url=lambda u: parse_sd_archive_pdf,
    ),
    # ID: the 2008-era cumulative log PDF (Wayback capture, bundled) whose
    # 2008 rows were dropped from today's live log; its early-2009 rows are
    # filtered inside the parser to avoid near-duplicating live-log rows.
    "ID": BackfillSpec(
        bundled_files=id_archive_files,
        parse_for_url=lambda u: parse_id_2008_pdf,
    ),
    # NY: the dashboard's full crosstab export (2006-2026, ~9k rows) bundled
    # as a gzipped snapshot; NYScraper.parse reads it (same schema as the live
    # current-year CSV). Overlap with the live 2025-2026 rows dedupes by
    # notice_id.
    "NY": BackfillSpec(bundled_bytes=ny_history_csv),
    # WV: the workforcewv.org cumulative notice log Mar-2011 - Jun-2021 (373
    # blocks), bundled as the raw 1 MiB-truncated Wayback capture — see the
    # module comment on parse_wv_archive_pdf. The live scraper's rows carry
    # employer+date only, so the log's Jan-Jun 2021 overlap rows (2) hash
    # differently (richer city/zip) — expect near-misses at dry-run and plan
    # a mark-superseded pass instead of filtering them.
    "WV": BackfillSpec(
        bundled_files=wv_archive_files,
        parse_for_url=lambda u: parse_wv_archive_pdf,
    ),
    # PA: archived per-month pages via Wayback CDX (portal.state.pa.us
    # 2001-2015, SharePoint dli.pa.gov 2011-2022; same content template).
    # _fetch_pa_year hard-caps at 2022 — the AEM live era (2023+) stamps
    # notice_date from its publish date, so re-parsing those months would
    # mint duplicates of rows the regular scraper already stores.
    "PA": BackfillSpec(
        year_start=2001,
        fetch_year=lambda s, y: _fetch_pa_year(y),
        parse_year=lambda b, y: parse_pa_month(b, y),
    ),
}

_SUPPORTED = frozenset(_BACKFILL)


def backfill_historical(
    state: str,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """Fetch and ingest all available historical WARN data for ``state``.

    Returns ``{"years_attempted": N, "years_ok": N, "rows_seen": N, "rows_new": N}``.
    """
    state = state.upper()
    spec = _BACKFILL.get(state)
    if spec is None:
        raise ValueError(
            f"backfill-historical does not support {state!r}. "
            f"Supported: {', '.join(sorted(_SUPPORTED))}"
        )

    stats: dict[str, int] = {
        "years_attempted": 0,
        "years_ok": 0,
        "rows_seen": 0,
        "rows_new": 0,
    }

    scraper = get_scraper(state)

    if spec.bundled_bytes is not None:
        stats["years_attempted"] += 1
        _ingest_raw(
            scraper, spec.bundled_bytes(), label="bundled-snapshot",
            stats=stats, dry_run=dry_run,
        )
    elif spec.bundled_files is not None:
        members = spec.bundled_files()
        if limit is not None:
            members = members[:limit]
        for name, raw in members:
            stats["years_attempted"] += 1
            parse_fn = spec.parse_for_url(name) if spec.parse_for_url else None
            _ingest_raw(
                scraper, raw, label=f"bundled:{name}",
                stats=stats, dry_run=dry_run, parse_fn=parse_fn,
            )
    elif spec.discover_urls is not None:
        _backfill_url_list(scraper, spec, stats, dry_run=dry_run, limit=limit)
    else:
        start = year_start or spec.year_start or datetime.now().year
        end = year_end or datetime.now().year
        _backfill_year_loop(scraper, state, spec, start, end, stats, dry_run=dry_run)

    log.info(
        "%s backfill done: years_attempted=%d years_ok=%d rows_seen=%d rows_new=%d",
        state,
        stats["years_attempted"],
        stats["years_ok"],
        stats["rows_seen"],
        stats["rows_new"],
    )
    return stats


# ---------------------------------------------------------------------------
# Mode 2 — archive-file list (CA)
# ---------------------------------------------------------------------------

# Some archives (KY SharePoint) 403 httpx's default User-Agent for file
# downloads even though the discovery API accepts it — send a browser UA.
_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}


def _backfill_url_list(
    scraper,
    spec: BackfillSpec,
    stats: dict[str, int],
    *,
    dry_run: bool,
    limit: int | None = None,
) -> None:
    log.info("%s: discovering historical file URLs", scraper.state)
    try:
        urls = spec.discover_urls()
    except ScrapeFailed as e:
        log.error("%s: could not discover archive URLs: %s", scraper.state, e)
        return

    if not urls:
        log.warning("%s: no historical file links found", scraper.state)
        return

    if limit is not None and len(urls) > limit:
        log.info(
            "%s: --limit %d — processing the first %d of %d file(s)",
            scraper.state, limit, limit, len(urls),
        )
        urls = urls[:limit]

    log.info("%s: found %d historical file(s)", scraper.state, len(urls))

    for url in urls:
        stats["years_attempted"] += 1
        log.info("%s: fetching %s", scraper.state, url)
        is_wayback = "web.archive.org" in url
        raw = None
        # Wayback's throttle refuses connections in bursts; escalating
        # backoffs clear most of them (a single 30s retry still dropped 12%
        # of the NY pilot, 2026-07-07 — a lost page costs a whole extra
        # multi-hour pass, so patience here is cheap).
        backoffs = (30, 90)
        for attempt in (1, 2, 3):
            if is_wayback:
                # Wayback throttles request bursts; pace replay downloads.
                time.sleep(3)
            try:
                r = httpx.get(
                    url, headers=_FETCH_HEADERS, timeout=120, follow_redirects=True
                )
                r.raise_for_status()
                raw = r.content
                break
            except httpx.HTTPError as e:
                if is_wayback and attempt < 3:
                    log.info("%s: wayback refused %s — backing off", scraper.state, url)
                    time.sleep(backoffs[attempt - 1])
                    continue
                log.warning("%s: fetch failed for %s: %s", scraper.state, url, e)
                _record_run(
                    scraper.state, label=url, status="fetch_failed",
                    error=str(e), dry_run=dry_run,
                )
                break
        if raw is None:
            continue

        parse_fn = spec.parse_for_url(url) if spec.parse_for_url else None
        _ingest_raw(scraper, raw, label=url, stats=stats, dry_run=dry_run, parse_fn=parse_fn)


# ---------------------------------------------------------------------------
# Mode 1 — year loop
# ---------------------------------------------------------------------------

def _backfill_year_loop(
    scraper,
    state: str,
    spec: BackfillSpec,
    start: int,
    end: int,
    stats: dict[str, int],
    *,
    dry_run: bool,
) -> None:
    log.info("%s: backfilling years %d-%d", state, start, end)

    for year in range(start, end + 1):
        stats["years_attempted"] += 1
        log.info("%s: fetching year %d", state, year)

        try:
            raw = spec.fetch_year(scraper, year)
        except ScrapeFailed as e:
            log.warning("%s %d: fetch failed: %s", state, year, e)
            _record_run(
                state, label=str(year), status="fetch_failed", error=str(e), dry_run=dry_run
            )
            continue

        if raw is None:
            log.info("%s %d: no data (page missing or empty)", state, year)
            continue

        # Paginated sources return one chunk per page; each counts as an attempt.
        chunks = raw if isinstance(raw, list) else [raw]
        parse_fn = None
        if spec.parse_year is not None:
            parse_fn = lambda b, _y=year: spec.parse_year(b, _y)  # noqa: E731
        for i, chunk in enumerate(chunks):
            if i > 0:
                stats["years_attempted"] += 1
            label = str(year) if len(chunks) == 1 else f"{year} p{i + 1}"
            _ingest_raw(
                scraper, chunk, label=label, stats=stats, dry_run=dry_run, parse_fn=parse_fn
            )


# ---------------------------------------------------------------------------
# Shared ingest helpers (also used by `warn-v2 ingest-file`)
# ---------------------------------------------------------------------------

def _ingest_raw(
    scraper,
    raw: bytes,
    *,
    label: str,
    stats: dict[str, int],
    dry_run: bool,
    parse_fn=None,
) -> None:
    _parse = parse_fn if parse_fn is not None else scraper.parse
    try:
        rows = _parse(raw)
    except ParseFailed as e:
        log.warning("%s %s: parse failed: %s", scraper.state, label, e)
        _record_run(
            scraper.state, label=label, status="parse_failed", error=str(e), dry_run=dry_run
        )
        return

    if not rows:
        log.info("%s %s: parsed 0 rows — skipping", scraper.state, label)
        return

    if dry_run:
        log.info(
            "%s %s: dry run — would upsert %d rows",
            scraper.state, label, len(rows),
        )
        _report_near_misses(scraper.state, label, rows)
        stats["years_ok"] += 1
        stats["rows_seen"] += len(rows)
        return

    with session_scope() as session:
        seen, new = upsert_notices(session, rows)
        session.commit()

    log.info("%s %s: seen=%d new=%d", scraper.state, label, seen, new)
    stats["years_ok"] += 1
    stats["rows_seen"] += seen
    stats["rows_new"] += new
    _record_run(
        scraper.state, label=label, status="ok",
        rows_scraped=seen, rows_new=new, dry_run=dry_run,
    )


def _report_near_misses(state: str, label: str, rows: list[NoticeRow]) -> None:
    """Dry-run duplicate preview. Best-effort: skipped when no DB is reachable.

    A *near miss* is a parsed row whose ``notice_id`` is new but whose
    (state, normalized employer, notice_date) matches an existing notice —
    i.e. it would insert as a duplicate differing only in city/ZIP.
    """
    try:
        with session_scope() as session:
            ids = {notice_id(r) for r in rows}
            existing_ids = set(
                session.execute(
                    select(Notice.notice_id).where(Notice.notice_id.in_(ids))
                ).scalars()
            )
            dates = {r.notice_date for r in rows if r.notice_date is not None}
            candidates = session.execute(
                select(Notice.notice_id, Notice.employer, Notice.notice_date).where(
                    Notice.state == state.upper(),
                    Notice.notice_date.in_(dates),
                )
            ).all()
    except Exception as e:
        log.warning("%s %s: near-miss check skipped (no DB reachable): %s", state, label, e)
        return

    by_key: dict[tuple[str, object], list[str]] = {}
    for nid, emp, nd in candidates:
        by_key.setdefault((_norm(emp), nd), []).append(nid)

    already = 0
    near: list[NoticeRow] = []
    for r in rows:
        nid = notice_id(r)
        if nid in existing_ids:
            already += 1
            continue
        if any(m != nid for m in by_key.get((_norm(r.employer), r.notice_date), [])):
            near.append(r)

    log.info(
        "%s %s: would_insert=%d (near_miss=%d) already_exists=%d",
        state, label, len(rows) - already, len(near), already,
    )
    for r in near[:10]:
        log.info(
            "%s %s: near miss: %r %s (city=%r zip=%r) collides with an existing "
            "notice keyed differently — would duplicate",
            state, label, r.employer, r.notice_date, r.city, r.zip,
        )
    if len(near) > 10:
        log.info("%s %s: ... and %d more near misses", state, label, len(near) - 10)


def _record_run(
    state: str,
    *,
    label: str,
    status: str,
    error: str | None = None,
    rows_scraped: int | None = None,
    rows_new: int | None = None,
    dry_run: bool,
) -> None:
    """Persist one per-chunk ScraperRun, status-prefixed ``backfill_``.

    The prefix keeps these rows out of everything that reasons about the
    *live* scraper's health from a state's newest run — the audit's
    row-drift/broken flags, /api/runs/status last-success, the staleness
    metric, and cadence inference all treat a whole-source scrape's row
    count as the signal, which a one-month/one-year chunk would fake out.
    """
    if dry_run:
        return
    now = datetime.now().astimezone()
    with session_scope() as session:
        run = ScraperRun(
            state=state,
            started_at=now,
            finished_at=now,
            status=f"backfill_{status}",
            error=error,
            rows_scraped=rows_scraped,
            rows_new=rows_new,
        )
        session.add(run)
        session.commit()
