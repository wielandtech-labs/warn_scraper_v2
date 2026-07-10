"""NC calendar-2013 backfill — pinned Wayback PDF discovery + parse quality.

The 2013 report predates the commerce.nc.gov archive hub (whose per-year links
stop at 2014) and survives only as a Wayback capture of the old nccommerce.com
``Warn-2013.pdf``. It uses the same "WARN Notice - Summary Count" layout as
2014-2017, but stresses the word-position parser harder: partially
letter-spaced two-word cities ("M o u nt Airy"), a city wrapped across lines
("Winston" / "Salem"), a monthly subtotal value rendered in its own line
bucket inside the city column, and a split closure-type cell
("Layoff/ Permanent").

Fixture: ``archive_2013_slice.pdf`` = pages 1 and 4 of the capture
(37 of the 82 notices), which between them exercise every quirk above.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import respx

from warn_v2.scrapers.states.nc import (
    _ARCHIVE_HUB,
    _WARN_2013_PDF_URL,
    _discover_nc_pdf_urls,
    _join_city,
    parse_nc_pdf,
)


def _nc_fixture(name: str) -> bytes:
    return (
        Path(__file__).resolve().parents[1]
        / "warn_v2" / "scrapers" / "fixtures" / "nc" / name
    ).read_bytes()


def test_nc_2013_pinned_wayback_url_is_a_replay_url():
    assert _WARN_2013_PDF_URL == (
        "https://web.archive.org/web/20150327025758id_"
        "/http://www.nccommerce.com/Portals/11/WARN/Warn-2013.pdf"
    )


@respx.mock
def test_nc_discovery_appends_pinned_2013_capture_after_hub_years():
    html = (
        b"<html><body>"
        b"<a href='/warn-report-2019/open'>2019</a>"
        b"<a href='/warn-report-2014-0/open'>2014</a>"
        b"</body></html>"
    )
    respx.get(_ARCHIVE_HUB).mock(return_value=httpx.Response(200, content=html))

    assert _discover_nc_pdf_urls() == [
        "https://www.commerce.nc.gov/warn-report-2019/open",
        "https://www.commerce.nc.gov/warn-report-2014-0/open",
        _WARN_2013_PDF_URL,
    ]


def test_nc_parse_2013_dispatches_to_summary_count_era():
    """The 2013 layout must hit the same branch as 2014-2017 (no grid; the
    banner reads 'WARN Notice - Summary Count')."""
    rows = parse_nc_pdf(_nc_fixture("archive_2013_slice.pdf"), "http://x/2013")
    assert len(rows) == 37
    assert all(r.state == "NC" and r.source_url == "http://x/2013" for r in rows)

    first = rows[0]
    assert first.employer == "Home Care Industries Inc"
    assert first.notice_date == date(2013, 1, 2)
    assert first.effective_date == date(2013, 1, 2)
    assert first.layoff_count == 35
    assert first.city == "Oxford"  # rendered "O x ford" — despaced
    assert first.closure_type == "Closure/Permanent"

    # Monthly banner / header lines never become notices.
    assert not any("Sum of" in r.employer or "Total" in r.employer for r in rows)


def test_nc_parse_2013_letter_spaced_two_word_cities_keep_their_space():
    """'M o u nt Airy' must despace to 'Mount Airy', not glue to 'MountAiry';
    a city wrapped onto a second line ('Winston' / 'Salem') rejoins with a
    space rather than gluing."""
    rows = parse_nc_pdf(_nc_fixture("archive_2013_slice.pdf"), "http://x/2013")

    furniture = next(r for r in rows if "FurnitureBrands" in r.employer)
    assert furniture.city == "Mount Airy"
    assert furniture.layoff_count == 134

    childrens = next(r for r in rows if "Children's Home" in r.employer)
    assert childrens.city == "Winston Salem"

    # A genuinely multi-line city cell rejoins in reading order.
    pkl = next(r for r in rows if r.employer == "PKL Services, Inc.")
    assert pkl.city == "Cherry Point New River"
    # Its closure cell renders as "Layoff/ Permanent" — rejoined without space.
    assert pkl.closure_type == "Layoff/Permanent"


def test_nc_parse_2013_stray_subtotal_value_does_not_pollute_city():
    """September's 'Sum of # Employees Affected: 1420' value renders a few pt
    above its label and lands in a line bucket of its own inside the city
    column; it must not be appended to the preceding record's city."""
    rows = parse_nc_pdf(_nc_fixture("archive_2013_slice.pdf"), "http://x/2013")
    kerr = next(r for r in rows if r.employer == "Kerr Drug")
    assert kerr.city == "Raleigh"
    assert kerr.layoff_count == 84


def test_nc_parse_2013_source_date_typo_ingested_as_printed():
    """One December-section row is printed '2/03/2013' (clearly a source typo
    for 12/03/2013 — effective 01/31/2014, filed between 11/27 and 12/05 rows).
    We ingest as printed rather than guessing a correction."""
    rows = parse_nc_pdf(_nc_fixture("archive_2013_slice.pdf"), "http://x/2013")
    xerox = next(r for r in rows if r.employer == "Xerox Business Services")
    assert xerox.notice_date == date(2013, 2, 3)
    assert xerox.effective_date == date(2014, 1, 31)
    assert xerox.layoff_count == 168


def test_nc_join_city_uses_glyph_gaps():
    """Letter-spaced fragments touch (gap ~0pt); real word gaps are >=2.4pt;
    a wrapped line restarts far left (large negative gap). Positions taken
    from the 2013 PDF."""
    # "O x ford" -> Oxford (fully touching run)
    assert _join_city(
        [(335.0, 344.0, "O"), (344.0, 350.0, "x"), (350.0, 368.0, "ford")]
    ) == "Oxford"
    # "M o u nt Airy" -> Mount Airy (touching run, then a real 2.4pt word gap)
    assert _join_city(
        [(335.0, 344.0, "M"), (344.0, 350.0, "o"), (350.0, 356.0, "u"),
         (356.0, 365.0, "nt"), (368.0, 385.0, "Airy")]
    ) == "Mount Airy"
    # Plain multi-word city keeps its space.
    assert _join_city([(335.0, 365.0, "Cherry"), (367.4, 390.0, "Point")]) == "Cherry Point"
    # Cross-line wrap: second line restarts left of the first line's end.
    assert _join_city([(335.0, 373.0, "Winston"), (335.0, 355.0, "Salem")]) == "Winston Salem"
    assert _join_city([(319.0, 338.7, "Cary")]) == "Cary"
    assert _join_city([]) == ""
