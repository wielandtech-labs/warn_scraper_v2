"""Per-state data-quality audit.

Computes, in a single pass over the DB, a structured quality report for every
jurisdiction so we can triage which states still need work and map each gap to a
remediation command.  See ``STATE_AUDIT.md`` / the plan for the rubric.

Metrics per state (all computed over *active* — non-superseded — notices unless
noted):

  * notice counts (active / superseded) and notice_date span
  * per-year notice counts, with gap flags for empty interior years
  * field fill-rates: effective_date, layoff_count, closure_type, address,
    raw_notice_url, pdf_path, location_id, company naics_code, company enriched
  * estimated_date ratio — share of effective_dates that equal notice_date+60d
    (the WARN-Act fallback rather than a real source date)
  * PDF coverage — for direct-PDF states, share with a stored pdf_path
  * geocoding — locations with NULL coords; coords outside the state bbox;
    notices carrying a street address (``backfill-geo --rerun-address`` targets);
    per-tier accuracy breakdown from ``Location.geocode_source``
  * scraper health — latest ScraperRun status + rows_scraped vs expected_row_range
  * sanity flags — future notice_date, effective_date < notice_date,
    layoff_count <= 0 or absurdly large

Usage::

    warn-v2 audit                 # table for all jurisdictions
    warn-v2 audit --state CA      # one state, verbose
    warn-v2 audit --json          # machine-readable
    warn-v2 audit --markdown      # STATE_AUDIT.md table body
    warn-v2 audit --check-links   # also HEAD-sample raw_notice_url/pdf links
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.db.models import (
    SCRAPER_SUCCESS_STATUSES,
    Company,
    Location,
    Notice,
    ScraperRun,
)
from warn_v2.geo.bbox import STATE_BBOX as _BBOX
from warn_v2.scrapers.registry import all_states, get_scraper

log = logging.getLogger(__name__)

# The 60-day WARN-Act minimum used as effective_date fallback on insert
# (see pipeline/storage.py). Notices whose effective_date equals notice_date +
# this delta almost certainly carry the estimate, not a real source date.
_WARN_FALLBACK = timedelta(days=60)

# Flag thresholds (kept conservative so the report isn't all-red).
_GEO_OK = 0.95          # geocoded fraction below this -> low_geo
_PDF_OK = 0.90          # pdf coverage below this -> missing_pdf
_EFF_OK = 0.50          # effective_date fill below this -> no_effective_date
_ESTIMATED_HI = 0.50    # estimated-date ratio above this -> mostly_estimated_dates
_ENRICH_OK = 0.50       # company-enriched fraction below this -> low_enrichment
_COUNT_MAX = 50_000     # layoff_count above this is implausible

# Jurisdictions known to be blocked at scraper-build time (re-checked this pass).
BLOCKED = frozenset({"AR", "NH", "WY"})

@dataclass
class StateAudit:
    """Audit result for a single jurisdiction."""

    state: str
    active: int = 0
    superseded: int = 0
    first_year: int | None = None
    last_year: int | None = None
    empty_years: list[int] = field(default_factory=list)
    # Fill counts (numerator; denominator is ``active``).
    fill: dict[str, int] = field(default_factory=dict)
    estimated_dates: int = 0
    # PDF
    pdf_state: bool = True
    pdf_eligible: int = 0       # active notices with a raw_notice_url
    pdf_have: int = 0          # ...of those, with a stored pdf_path
    # Geo
    geocoded: int = 0          # active notices whose location has lat/lon
    null_coords: int = 0       # active notices linked to a location lacking coords
    addr_available: int = 0    # active notices carrying a street address
    out_of_state: int = 0      # active notices geocoded outside the state bbox
    geo_by_source: dict[str, int] = field(default_factory=dict)
    # Counts of geocoded notices by tier: 'census'|'zip'|'city'|'county'|'unknown'
    # Enrichment
    company_enriched: int = 0
    # Scraper health
    last_status: str | None = None
    last_rows: int | None = None
    expected_min: int | None = None
    expected_max: int | None = None
    # Sanity
    future_dates: int = 0
    eff_before_notice: int = 0
    count_outliers: int = 0
    # Link check (optional)
    link_sample: int = 0
    link_dead: int = 0
    flags: list[str] = field(default_factory=list)

    def _ratio(self, num: int) -> float:
        return num / self.active if self.active else 0.0

    def finalize(self) -> None:
        """Populate the flags list from the accumulated counts."""
        flags: list[str] = []
        if self.state in BLOCKED:
            flags.append("blocked")
        if self.active == 0:
            flags.append("no_data")
            self.flags = flags
            return

        if self.last_status and self.last_status not in SCRAPER_SUCCESS_STATUSES:
            flags.append(f"scraper_{self.last_status}")
        if (
            self.expected_min is not None
            and self.last_rows is not None
            and self.last_status == "ok"
            and self.last_rows < self.expected_min
        ):
            flags.append("row_drift")

        if self.empty_years:
            flags.append("year_gaps")

        if self._ratio(self.fill.get("effective_date", 0)) < _EFF_OK:
            flags.append("no_effective_date")
        eff = self.fill.get("effective_date", 0)
        if eff and self.estimated_dates / eff > _ESTIMATED_HI:
            flags.append("mostly_estimated_dates")

        if self.pdf_state and self.pdf_eligible:
            if self.pdf_have / self.pdf_eligible < _PDF_OK:
                flags.append("missing_pdf")

        if self._ratio(self.geocoded) < _GEO_OK:
            flags.append("low_geo")
        if self.out_of_state:
            flags.append("out_of_state_coords")

        if self._ratio(self.company_enriched) < _ENRICH_OK:
            flags.append("low_enrichment")

        if self.superseded:
            flags.append("has_superseded")
        if self.future_dates or self.eff_before_notice:
            flags.append("date_sanity")
        if self.count_outliers:
            flags.append("count_outliers")
        if self.link_sample and self.link_dead:
            flags.append("dead_links")

        self.flags = flags

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fill_rates"] = {
            k: round(self._ratio(v), 3) for k, v in self.fill.items()
        }
        d["pdf_coverage"] = (
            round(self.pdf_have / self.pdf_eligible, 3) if self.pdf_eligible else None
        )
        d["geo_coverage"] = round(self._ratio(self.geocoded), 3)
        d["estimated_date_ratio"] = (
            round(self.estimated_dates / self.fill["effective_date"], 3)
            if self.fill.get("effective_date")
            else None
        )
        return d


_FILL_FIELDS = (
    "effective_date",
    "layoff_count",
    "closure_type",
    "address",
    "raw_notice_url",
    "pdf_path",
    "location_id",
)


def _out_of_bbox(state: str, lat: float, lon: float) -> bool:
    box = _BBOX.get(state.upper())
    if box is None:
        return False
    lat_min, lat_max, lon_min, lon_max = box
    return not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max)


def _new_audit(code: str) -> StateAudit:
    sa = StateAudit(state=code)
    sa.fill = {f: 0 for f in _FILL_FIELDS}
    sa.fill["naics_code"] = 0
    return sa


def audit_states(
    session: Session,
    *,
    state_filter: str | None = None,
    today: date | None = None,
) -> list[StateAudit]:
    """Compute the audit for every jurisdiction (or one) in a single DB pass."""
    today = today or date.today()

    # Pre-seed results for every registered state so zero-data states still show.
    results: dict[str, StateAudit] = {}
    for code in all_states():
        if state_filter and code != state_filter.upper():
            continue
        sa = _new_audit(code)
        try:
            scraper = get_scraper(code)
            sa.pdf_state = bool(getattr(scraper, "raw_notice_url_is_pdf", True))
            rng = getattr(scraper, "expected_row_range", None)
            if rng:
                sa.expected_min, sa.expected_max = rng[0], rng[1]
        except Exception:  # missing scraper shouldn't abort the whole audit
            pass
        results[code] = sa

    def _ensure(code: str) -> StateAudit:
        sa = results.get(code)
        if sa is None:
            sa = _new_audit(code)
            results[code] = sa
        return sa

    # Per-year counters, accumulated separately then folded into empty_years.
    year_counts: dict[str, dict[int, int]] = {}

    stmt = (
        select(
            Notice.state,
            Notice.notice_date,
            Notice.effective_date,
            Notice.layoff_count,
            Notice.closure_type,
            Notice.address,
            Notice.raw_notice_url,
            Notice.pdf_path,
            Notice.location_id,
            Notice.is_superseded,
            Location.lat,
            Location.lon,
            Location.geocode_source,
            Company.enriched_at,
            Company.naics_code,
        )
        .outerjoin(Location, Notice.location_id == Location.id)
        .outerjoin(Company, Notice.company_id == Company.id)
    )
    if state_filter:
        stmt = stmt.where(Notice.state == state_filter.upper())

    for row in session.execute(stmt).all():
        (
            state, notice_date, effective_date, layoff_count, closure_type,
            address, raw_notice_url, pdf_path, location_id, is_superseded,
            lat, lon, geocode_source, enriched_at, naics_code,
        ) = row
        state = (state or "").upper()
        sa = _ensure(state)

        if is_superseded:
            sa.superseded += 1
            continue

        sa.active += 1

        if notice_date is not None:
            yc = year_counts.setdefault(state, {})
            yc[notice_date.year] = yc.get(notice_date.year, 0) + 1

        if effective_date is not None:
            sa.fill["effective_date"] += 1
            if notice_date is not None and effective_date == notice_date + _WARN_FALLBACK:
                sa.estimated_dates += 1
            if notice_date is not None and effective_date < notice_date:
                sa.eff_before_notice += 1
        if layoff_count is not None:
            sa.fill["layoff_count"] += 1
            if layoff_count <= 0 or layoff_count > _COUNT_MAX:
                sa.count_outliers += 1
        if closure_type:
            sa.fill["closure_type"] += 1
        if address:
            sa.fill["address"] += 1
            sa.addr_available += 1
        if raw_notice_url:
            sa.fill["raw_notice_url"] += 1
            sa.pdf_eligible += 1
            if pdf_path:
                sa.pdf_have += 1
        if pdf_path:
            sa.fill["pdf_path"] += 1
        if location_id is not None:
            sa.fill["location_id"] += 1
        if naics_code:
            sa.fill["naics_code"] += 1
        if enriched_at is not None:
            sa.company_enriched += 1

        if location_id is not None:
            if lat is not None and lon is not None:
                sa.geocoded += 1
                if _out_of_bbox(state, float(lat), float(lon)):
                    sa.out_of_state += 1
                src = geocode_source or "unknown"
                sa.geo_by_source[src] = sa.geo_by_source.get(src, 0) + 1
            else:
                sa.null_coords += 1

        if notice_date is not None and notice_date > today:
            sa.future_dates += 1

    # Fold per-year counts into first/last year + interior gaps.
    for state, yc in year_counts.items():
        sa = _ensure(state)
        years = sorted(yc)
        if years:
            sa.first_year, sa.last_year = years[0], years[-1]
            sa.empty_years = [
                y for y in range(sa.first_year, sa.last_year + 1) if y not in yc
            ]

    # Latest scraper run status per state (single ordered pass). Backfill /
    # ingest-file chunk runs (status backfill_*) are per-month/per-year slices
    # whose small rows_scraped would fake out row_drift and whose failures
    # aren't live-scraper breakage — health reads live runs only.
    run_stmt = select(
        ScraperRun.state, ScraperRun.status, ScraperRun.rows_scraped,
    ).where(
        ScraperRun.status.notlike("backfill\\_%", escape="\\")
    ).order_by(ScraperRun.started_at.desc())
    seen: set[str] = set()
    for state, status, rows_scraped in session.execute(run_stmt).all():
        state = (state or "").upper()
        if state in seen:
            continue
        seen.add(state)
        sa = results.get(state)
        if sa is not None:
            sa.last_status = status
            sa.last_rows = rows_scraped

    for sa in results.values():
        sa.finalize()

    return [results[k] for k in sorted(results)]


# ---------------------------------------------------------------------------
# Link checking (optional, network) — separate from the DB pass
# ---------------------------------------------------------------------------

def check_links(
    session: Session, state: str, *, sample: int = 8
) -> tuple[int, int]:
    """HEAD-sample a state's PDF source URLs; return ``(checked, dead)``.

    Catches the AK class of bug where ``raw_notice_url`` values 404 wholesale.
    """
    import httpx

    stmt = (
        select(Notice.raw_notice_url)
        .where(
            Notice.state == state.upper(),
            Notice.raw_notice_url.isnot(None),
            Notice.is_superseded.is_(False),
        )
        .order_by(Notice.notice_date.desc().nullslast())
        .limit(sample)
    )
    urls = [u for (u,) in session.execute(stmt).all() if u]
    dead = 0
    headers = {"User-Agent": "Mozilla/5.0 warn-v2-audit/0.1"}
    for url in urls:
        try:
            r = httpx.head(url, headers=headers, timeout=15, follow_redirects=True)
            if r.status_code >= 400:
                # Some servers reject HEAD; retry with a ranged GET before failing.
                r = httpx.get(
                    url, headers={**headers, "Range": "bytes=0-0"},
                    timeout=15, follow_redirects=True,
                )
            if r.status_code >= 400:
                dead += 1
        except httpx.HTTPError:
            dead += 1
    return len(urls), dead


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_json(audits: list[StateAudit]) -> str:
    return json.dumps([a.to_dict() for a in audits], indent=2, default=str)


def _pct(num: int, den: int) -> str:
    return f"{100 * num / den:.0f}%" if den else "-"


def render_table(audits: list[StateAudit]) -> str:
    """Compact human-readable table to stdout."""
    header = (
        f"{'ST':<3} {'ACTIVE':>7} {'SUP':>5} {'YEARS':>11} "
        f"{'EFF':>4} {'CNT':>4} {'PDF':>4} {'GEO':>4} {'ENR':>4}  FLAGS"
    )
    lines = [header, "-" * len(header)]
    for a in audits:
        years = (
            f"{a.first_year}-{a.last_year}"
            if a.first_year and a.last_year
            else "-"
        )
        eff = _pct(a.fill.get("effective_date", 0), a.active)
        cnt = _pct(a.fill.get("layoff_count", 0), a.active)
        pdf = _pct(a.pdf_have, a.pdf_eligible) if a.pdf_state else "n/a"
        geo = _pct(a.geocoded, a.active)
        enr = _pct(a.company_enriched, a.active)
        lines.append(
            f"{a.state:<3} {a.active:>7} {a.superseded:>5} {years:>11} "
            f"{eff:>4} {cnt:>4} {pdf:>4} {geo:>4} {enr:>4}  "
            f"{', '.join(a.flags)}"
        )
    return "\n".join(lines)


def _status_label(a: StateAudit) -> str:
    if "blocked" in a.flags:
        return "blocked"
    if "no_data" in a.flags:
        return "no data"
    broken = {"scraper_fetch_failed", "scraper_parse_failed",
              "scraper_validation_failed", "scraper_storage_failed",
              "row_drift", "dead_links"}
    if broken & set(a.flags):
        return "broken"
    gap_flags = set(a.flags) - {"has_superseded"}
    if gap_flags:
        return "gaps"
    return "complete"


# Map a flag to the remediation command that addresses it.
_REMEDY = {
    "low_geo": "backfill-geo",
    "out_of_state_coords": "fix geocode / address source",
    "missing_pdf": "download-pdfs --state {st}",
    "no_effective_date": "backfill-effective-dates --state {st}",
    "mostly_estimated_dates": "source detail/PDF for real dates",
    "year_gaps": "backfill-historical --state {st}",
    "has_superseded": "mark-superseded --state {st}",
    "low_enrichment": "enrich --state {st}",
    "dead_links": "fix scraper URL pattern",
    "row_drift": "/heal-scraper {st}",
    "scraper_fetch_failed": "/heal-scraper {st}",
    "scraper_parse_failed": "/heal-scraper {st}",
    "date_sanity": "inspect parser date handling",
    "count_outliers": "inspect parser count handling",
    "blocked": "re-check source access",
    "no_data": "re-check source access",
}


def _next_action(a: StateAudit) -> str:
    actions = []
    for f in a.flags:
        remedy = _REMEDY.get(f)
        if remedy:
            actions.append(remedy.format(st=a.state))
    seen: set[str] = set()
    uniq = [x for x in actions if not (x in seen or seen.add(x))]
    return "; ".join(uniq) if uniq else "-"


# Accuracy order for the geo-source breakdown: census = rooftop, then
# progressively coarser centroids; 'unknown' = pre-migration rows.
_GEO_SOURCES = ("census", "zip", "city", "county", "unknown")


def _geo_src_cell(a: StateAudit) -> str:
    """Render geo_by_source as e.g. ``census 82% / zip 12% / ? 6%`` of geocoded."""
    if not a.geocoded:
        return "-"
    parts = []
    for src in _GEO_SOURCES:
        n = a.geo_by_source.get(src, 0)
        if n:
            label = "?" if src == "unknown" else src
            parts.append(f"{label} {_pct(n, a.geocoded)}")
    return " / ".join(parts) if parts else "-"


def render_markdown(audits: list[StateAudit]) -> str:
    """Emit the STATE_AUDIT.md table body."""
    head = (
        "| State | Active | Superseded | Years | Eff% | Count% | PDF% | Geo% | "
        "Geo src | Enrich% | Scraper | Status | Next action |\n"
        "|-------|-------:|-----------:|-------|-----:|-------:|-----:|-----:|"
        "---------|--------:|---------|--------|-------------|"
    )
    rows = [head]
    for a in audits:
        years = (
            f"{a.first_year}-{a.last_year}"
            if a.first_year and a.last_year
            else "-"
        )
        eff = _pct(a.fill.get("effective_date", 0), a.active)
        cnt = _pct(a.fill.get("layoff_count", 0), a.active)
        pdf = _pct(a.pdf_have, a.pdf_eligible) if a.pdf_state else "n/a"
        geo = _pct(a.geocoded, a.active)
        enr = _pct(a.company_enriched, a.active)
        scr = a.last_status or "-"
        rows.append(
            f"| {a.state} | {a.active} | {a.superseded} | {years} | {eff} | "
            f"{cnt} | {pdf} | {geo} | {_geo_src_cell(a)} | {enr} | {scr} | "
            f"{_status_label(a)} | {_next_action(a)} |"
        )
    return "\n".join(rows)
