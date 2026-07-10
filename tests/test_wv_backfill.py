"""WV historical backfill: the bundled 2011-2021 cumulative notice log.

The bundle is the raw 1 MiB-truncated Wayback capture of
``WV_WARN_Notices_3-1-11_to_6-7-21.pdf`` (fonts lost, content streams intact);
``parse_wv_archive_pdf`` reconstructs text from the content streams directly.
The fixture slice keeps three pages of the sanitized capture that cover every
parser feature: a two-address block and a month header (p1), a hex-encoded
(Type0-font) company name and a statewide multi-county block (p19), and a
per-site count cell with a Total line (p116).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.states.wv import parse_wv_archive_pdf, wv_archive_files

FIXTURES = Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "wv"


@pytest.fixture(scope="module")
def slice_rows():
    return parse_wv_archive_pdf((FIXTURES / "archive_slice.pdf").read_bytes())


def test_slice_parses_all_blocks(slice_rows) -> None:
    assert [(r.employer, r.notice_date) for r in slice_rows] == [
        ("Monongalia Coal Company, Inc.", date(2021, 6, 4)),
        ("Mylan Pharmaceuticals, Inc.", date(2021, 5, 24)),
        ("Argos USA LLC", date(2020, 4, 29)),
        ("Bloomin\u2019 Brands", date(2020, 4, 27)),
        ("Arch Coal Eastern Complex", date(2012, 12, 3)),
        (
            "CONSOL Energy Wiley Surface Mine Minway Preparation Plant "
            "Wiley Creek Surface Mine Miller Creek Administration "
            "Minway Surface Mine Group",
            date(2012, 10, 30),
        ),
    ]
    assert all(r.state == "WV" and r.source_url for r in slice_rows)


def test_slice_field_extraction(slice_rows) -> None:
    # Two side-by-side addresses in one cell: the WV one wins city/zip.
    monongalia = slice_rows[0]
    assert monongalia.city == "Wana"
    assert monongalia.zip == "26590"
    assert monongalia.county == "Monongalia"
    assert monongalia.layoff_count == 180
    assert monongalia.effective_date == date(2021, 8, 9)
    assert monongalia.closure_type == "Mass Layoff"

    mylan = slice_rows[1]
    assert mylan.layoff_count == 1246  # "1,246" — thousands separator
    assert mylan.city == "Morgantown"
    assert mylan.closure_type == "Closure"


def test_slice_hex_encoded_company_name(slice_rows) -> None:
    # "Bloomin' Brands" is drawn with the embedded Type0 font (CID hex
    # strings); regular text extraction loses it entirely.
    bloomin = slice_rows[3]
    assert bloomin.employer == "Bloomin\u2019 Brands"
    assert bloomin.layoff_count == 626
    assert bloomin.county == (
        "Raleigh, Mercer, Cabell, Kanawha, Wood, Monongalia, Harrison, and Berkeley"
    )
    # Multi-mall notice: the first WV address line supplies city/zip.
    assert bloomin.city == "Beckley"
    assert bloomin.zip == "25801"


def test_slice_multi_site_count_uses_total(slice_rows) -> None:
    # "Number Affected" lists one count per site ("Wiley Surface Mine 47",
    # ...) plus "Total 145" — the total wins over the first number.
    consol = slice_rows[5]
    assert consol.layoff_count == 145
    assert consol.city == "Naugatuck"
    assert consol.county == "Mingo"


def test_slice_annotation_line_not_absorbed(slice_rows) -> None:
    # p116 opens with "Update to Previous Notice 9/24/12" above the Arch Coal
    # block; the annotation must not leak into any field.
    arch = slice_rows[4]
    assert arch.employer == "Arch Coal Eastern Complex"
    assert arch.notice_date == date(2012, 12, 3)  # not the annotation's 9/24/12
    assert arch.layoff_count == 124


def test_parse_rejects_non_pdf() -> None:
    with pytest.raises(ParseFailed):
        parse_wv_archive_pdf(b"<html>not a pdf</html>")


def test_bundle_full_parse() -> None:
    """Integrity check on the committed tar.gz: the truncated capture still
    yields all 373 notice blocks with the verified per-year distribution."""
    members = wv_archive_files()
    assert [(n, len(b)) for n, b in members] == [
        ("WV_WARN_Notices_3-1-11_to_6-7-21.pdf", 1_048_576),  # 1 MiB crawler cut
    ]

    rows = parse_wv_archive_pdf(members[0][1])
    assert len(rows) == 373
    per_year: dict[int, int] = {}
    for r in rows:
        per_year[r.notice_date.year] = per_year.get(r.notice_date.year, 0) + 1
    assert per_year == {
        2011: 16, 2012: 48, 2013: 28, 2014: 38, 2015: 68, 2016: 34,
        2017: 17, 2018: 20, 2019: 27, 2020: 75, 2021: 2,
    }
    assert min(r.notice_date for r in rows) == date(2011, 3, 1)
    assert max(r.notice_date for r in rows) == date(2021, 6, 4)
    assert sum(r.layoff_count or 0 for r in rows) == 56_298
    # Two rows legitimately have no count ("Unknown" / "All").
    assert sum(1 for r in rows if r.layoff_count is None) == 2
    assert all(r.county for r in rows)


def test_registry_entry() -> None:
    from warn_v2.scripts.backfill_historical import _BACKFILL

    spec = _BACKFILL["WV"]
    assert spec.bundled_files is wv_archive_files
    assert spec.parse_for_url("WV_WARN_Notices_3-1-11_to_6-7-21.pdf") is parse_wv_archive_pdf
