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
