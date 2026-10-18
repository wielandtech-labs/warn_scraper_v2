"""PA pre-CDX-era backfill (Jul-1998 - Nov-2000): pinned Wayback captures.

The dli/li.state.pa.us pages carry the same notice-block template as the
2001+ portal pages, with 1990s drift that these tests pin down:

- bare ``AFFECTED:`` labels without the ``#`` (Jan-1999 SANYO cell);
- the colon escaping the bold tag (``<b>COUNTY</b>: Wayne``) or vanishing
  (``EFFECTIVE DATE </b>03/23/99``), splitting label and value onto
  separate lines;
- 2-digit effective-date years that must pivot to the 1900s (``11/30/98``);
- comma-less city lines on the 1998 page (``PITTSBURGH PA 15222``);
- an unclosed ``</td>`` mis-nesting one notice cell inside another
  (June-1999 Fidelity Bond cell);
- the 1998 host serving ALL month sections on one page, which the fetch
  splits into per-month envelopes so each keeps its own first-of-month
  notice_date proxy.
"""
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from warn_v2.scrapers.base import ScrapeFailed

_FIXTURES = (
    Path(__file__).resolve().parents[1] / "warn_v2" / "scrapers" / "fixtures" / "pa"
)


def _fixture_html(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8", errors="replace")


def _envelope(name: str, month: int) -> bytes:
    return json.dumps({"month": month, "html": _fixture_html(name)}).encode()


def test_parse_pa_month_early_era_label_drift():
    from warn_v2.scrapers.states.pa import parse_pa_month

    rows = parse_pa_month(_envelope("archive_early_1999_01.html", 1), 1999)
    assert len(rows) == 29

    # Bare "AFFECTED:" label (no #) — the cell must still be selected.
    sanyo = rows[0]
    assert sanyo.employer == "SANYO"
    assert sanyo.notice_date == date(1999, 1, 1)  # month page -> first-of-month
    assert sanyo.city == "Reedsville"
    assert sanyo.county == "Mifflin"
    assert sanyo.layoff_count == 81
    # 2-digit year "11/30/98" pivots to 1998, not 2098.
    assert sanyo.effective_date == date(1998, 11, 30)

    # Colon-less "EFFECTIVE DATE </b>03/13/99" still yields the date.
    hills = next(r for r in rows if r.employer == "HILL'S STORE COMPANY")
    assert hills.effective_date == date(1999, 3, 13)

    # "<b>COUNTY</b>: Wayne" — colon outside the bold tag.
    moore = next(r for r in rows if r.employer == "THE MOORE NORTH AMERICA")
    assert moore.county == "Wayne"

    # "# AFFECTED</b> 308" — label without colon, value on the next line.
    dvmc = next(r for r in rows if r.employer == "DELAWARE VALLEY MEDICAL CENTER")
    assert dvmc.layoff_count == 308

    # No label/closure text ever leaks into employer names.
    assert not any(
        w in r.employer.upper()
        for r in rows
        for w in ("CLOSING", "CLOSURE", "AFFECTED", "COUNTY:", "EFFECTIVE")
    )


def test_parse_pa_month_recovers_malformed_td():
    """June-1999's Fidelity Bond cell never closes its </td>, so the HTML
    parser nests the next notice inside it; both notices must survive,
    neither duplicated."""
    from warn_v2.scrapers.states.pa import parse_pa_month

    rows = parse_pa_month(_envelope("archive_early_1999_06.html", 6), 1999)
    assert len(rows) == 28
    fidelity = [r for r in rows if r.employer == "Fidelity Bond & Mortgage"]
    nycomed = [r for r in rows if r.employer == "Nycomed Amersham Imaging"]
    assert len(fidelity) == 1 and len(nycomed) == 1
    assert fidelity[0].layoff_count == 50
    assert fidelity[0].effective_date == date(1999, 8, 10)
    assert nycomed[0].layoff_count == 177


def test_split_1998_months_sections_and_rows():
    """The 1998 page holds Jul-Nov sections; each becomes its own month
    envelope with its own first-of-month notice_date."""
    from warn_v2.scrapers.states.pa import _split_1998_months, parse_pa_month

    chunks = _split_1998_months(_fixture_html("archive_early_1998_all.html"))
    months = [json.loads(c)["month"] for c in chunks]
    assert months == [11, 10, 9, 8, 7]  # page lists newest first

    by_month = {
        m: parse_pa_month(c, 1998) for m, c in zip(months, chunks, strict=True)
    }
    assert {m: len(rows) for m, rows in by_month.items()} == {
        7: 10, 8: 9, 9: 9, 10: 4, 11: 7,
    }

    cbs = next(r for r in by_month[11] if r.employer == "CBS CORPORATION")
    assert cbs.notice_date == date(1998, 11, 1)
    assert cbs.effective_date == date(1998, 12, 31)
    assert cbs.layoff_count == 119
    assert cbs.county == "Allegheny"
    # Comma-less "PITTSBURGH PA 15222" address line still yields the city.
    assert cbs.city == "PITTSBURGH"

    # "VARIOUS LOCATIONS" is not a city.
    first_union = next(
        r for r in by_month[8] if r.employer == "FIRST UNION CORPORATION"
    )
    assert first_union.city is None
    assert first_union.layoff_count == 2453


def test_fetch_pa_year_uses_pinned_early_captures(monkeypatch):
    """1999/2000 month captures are pinned statically (no CDX discovery)."""
    from warn_v2.scrapers.states import pa

    requested: list[str] = []

    def fake_get(url: str) -> str:
        requested.append(url)
        return _fixture_html("archive_early_1999_01.html")

    monkeypatch.setattr(pa, "_wayback_get", fake_get)
    chunks = pa._fetch_pa_year(1999)
    assert [json.loads(c)["month"] for c in chunks] == list(range(1, 13))
    assert requested[0] == (
        "https://web.archive.org/web/20010307175852id_/"
        "http://www.li.state.pa.us/dept/warn/jan99.html"
    )
    assert all("li.state.pa.us/dept/warn/" in u for u in requested)

    requested.clear()
    chunks = pa._fetch_pa_year(2000)
    # Dec-2000 was never captured — 11 months only, with the "sept" spelling.
    assert [json.loads(c)["month"] for c in chunks] == list(range(1, 12))
    assert any(u.endswith("/sept00.html") for u in requested)


def test_fetch_pa_year_1998_splits_the_single_page(monkeypatch):
    from warn_v2.scrapers.states import pa

    requested: list[str] = []

    def fake_get(url: str) -> str:
        requested.append(url)
        return _fixture_html("archive_early_1998_all.html")

    monkeypatch.setattr(pa, "_wayback_get", fake_get)
    chunks = pa._fetch_pa_year(1998)
    assert requested == [
        "https://web.archive.org/web/19991104100952id_/"
        "http://www.dli.state.pa.us/warn.html"
    ]
    assert [json.loads(c)["month"] for c in chunks] == [11, 10, 9, 8, 7]


def test_fetch_pa_year_floor():
    """Nothing below Jul-1998 exists — 1997 must not hit the network."""
    from warn_v2.scrapers.states.pa import _fetch_pa_year

    assert _fetch_pa_year(1997) is None


def test_backfill_registry_pa_year_start():
    from warn_v2.scripts.backfill_historical import _BACKFILL

    assert _BACKFILL["PA"].year_start == 1998


# ---------------------------------------------------------------------------
# 2023 - Sep-2024: the pa.gov migration window
# ---------------------------------------------------------------------------
# The live AEM page stamps every entry it bulk-copied from dli.pa.gov with the
# migration day (2024-09-16..19), so prod had no PA notices Jan-2023 - Aug-2024.
# Those months now come from the archived SharePoint month pages instead.


@respx.mock
def test_cdx_snapshots_keeps_latest_capture_without_collapse():
    """collapse=urlkey returned each page's EARLIEST capture (Jan-2023 -> a
    2023-01-05 snapshot holding one week of notices); the latest must win."""
    from warn_v2.scrapers.states import pa

    page = (
        "https://www.dli.pa.gov/Individuals/Workforce-Development/warn/notices/"
        "Pages/January-2023.aspx"
    )
    route = respx.get(pa._CDX_API).mock(
        return_value=httpx.Response(
            200,
            json=[
                ["timestamp", "original"],
                ["20230105161242", page],
                ["20240614064321", page],
                ["20240212160102", page],
            ],
        )
    )
    with patch("time.sleep"):
        snaps = pa._cdx_snapshots("dli.pa.gov/x/", pa._SP_MONTH_RE)
    assert snaps == {
        (2023, 1): f"https://web.archive.org/web/20240614064321id_/{page}"
    }
    assert "collapse" not in route.calls.last.request.url.params


@respx.mock
def test_cdx_snapshots_refuses_a_truncated_listing(monkeypatch):
    from warn_v2.scrapers.states import pa

    monkeypatch.setattr(pa, "_CDX_LIMIT", 2)
    respx.get(pa._CDX_API).mock(
        return_value=httpx.Response(
            200, json=[["timestamp", "original"], ["1", "a"], ["2", "b"]]
        )
    )
    with patch("time.sleep"), pytest.raises(ScrapeFailed, match="row limit"):
        pa._cdx_snapshots("dli.pa.gov/x/", pa._SP_MONTH_RE)


def test_fetch_pa_year_covers_2023_and_stops_at_the_cutover(monkeypatch):
    from warn_v2.scrapers.states import pa

    snaps = {(y, m): f"snap-{y}-{m}" for y in (2023, 2024) for m in range(1, 13)}
    monkeypatch.setattr(pa, "_month_snapshots", lambda: snaps)
    monkeypatch.setattr(pa, "_wayback_get", lambda url: "<html></html>")

    months = lambda y: [json.loads(c)["month"] for c in pa._fetch_pa_year(y)]  # noqa: E731
    assert months(2023) == list(range(1, 13))
    # Sep-2024 is the last SharePoint month; Oct+ notices live on pa.gov
    # with real publish dates.
    assert months(2024) == list(range(1, 10))
    assert pa._fetch_pa_year(2025) is None


def test_parse_pa_month_sharepoint_2023_multiline_schedules():
    """Jan-2023 (capture 2024-06-14). Three notices spread their EFFECTIVE
    DATE over several lines ("2nd Phase:  7/31/2023 (15 Employees)",
    "March 1, 2023 - 1 Employee"); those later lines must not become
    employers, and the closure line after them still belongs to the notice."""
    from warn_v2.scrapers.states.pa import parse_pa_month

    rows = parse_pa_month(_envelope("archive_sp_2023_01.html", 1), 2023)
    assert [r.employer for r in rows] == [
        "Morrison HealthCare",
        "LSC Communications \u2013 Lancaster EAST Plant",
        "LSC Communications \u2013 Lancaster WEST Plant",
        "C.H. Briggs",
        "Brinks Home",
        "Spreadshirt, Inc.",
        "Heartland Healthcare Services",
        "Finance of America Holdings, LLC",
        "Ascent Tubular Products",
        "Qualfon",
    ]
    assert {r.notice_date for r in rows} == {date(2023, 1, 1)}
    by = {r.employer: r for r in rows}
    # "February 1, 2023 - 82 Employees" / "March 1, ..." / "April 1, ..."
    assert by["C.H. Briggs"].effective_date == date(2023, 2, 1)
    assert by["C.H. Briggs"].closure_type == "Closing"
    assert by["C.H. Briggs"].layoff_count == 104
    # "1st Phase:  1/9/2023 (49 Employees)" / "2nd Phase:  7/31/2023 ..."
    assert by["Spreadshirt, Inc."].effective_date == date(2023, 1, 9)
    assert by["Spreadshirt, Inc."].closure_type == "Closing"
    # "Phase 1:  1/11/23 (38 workers)" ... "Phase 4:  TBD (6 workers)"
    assert by["Ascent Tubular Products"].effective_date == date(2023, 1, 11)
    assert by["Ascent Tubular Products"].city == "Munhall"


def test_parse_pa_month_sharepoint_2023_schedule_variants():
    """Apr-2023 lists a year-less schedule ("05/05 - 20 Employees") and Aug-2023
    splits "Beginning: ... - / Ending:  April 15, 2024" over two lines; neither
    continuation line may become an employer."""
    from warn_v2.scrapers.states.pa import parse_pa_month

    apr = parse_pa_month(_envelope("archive_sp_2023_04.html", 4), 2023)
    assert len(apr) == 9
    lightning = apr[0]
    assert lightning.employer == "Lightning Source, LLC"
    assert lightning.layoff_count == 260
    assert lightning.closure_type == "Layoff"

    aug = parse_pa_month(_envelope("archive_sp_2023_08.html", 8), 2023)
    assert len(aug) == 10
    ames = next(r for r in aug if r.employer == "The AMES Companies")
    assert ames.effective_date == date(2023, 10, 31)
    assert ames.closure_type == "Closure"
    assert not any(r.employer.lower().startswith(("ending", "beginning")) for r in apr + aug)
