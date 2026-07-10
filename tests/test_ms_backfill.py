"""MS historical backfill: archive-era quarterly parsing + Wayback replay list.

Covers the fourth MS layout family (2004-2006 "wps" era and PY2010-PY2019
"# Affected" era) added for `backfill-historical --state MS`, and the era
dispatch that keeps PY2020+ files on the existing parser paths.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.scrapers.states.ms import (
    _ARCHIVE_CAPTURES,
    _discover_ms_archive_urls,
    _parse_pdf,
    parse_ms_archive_pdf,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "warn_v2" / "scrapers" / "fixtures" / "ms"
_REPLAY = "https://web.archive.org/web/20060929145342id_/http://www.mdes.ms.gov/wps/x.pdf"


def _fixture(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# 2004-2006 era ("(City) (County) (Zip)" all in parens, SIC + NAICS lines)
# ---------------------------------------------------------------------------

def test_ms_parse_archive_2004_era_tags_non_warn():
    rows = parse_ms_archive_pdf(_fixture("sample_archive_2004.pdf"), _REPLAY)

    # Page 1 holds 11 events; only two are WARN — the rest are flagged
    # "NON-WARN ..." / "NON-WARN Existing Business & Industry Listing ..."
    # and kept with extra["non_warn"] (→ closure_category "Non-WARN").
    assert len(rows) == 11
    assert all(r.state == "MS" and r.source_url == _REPLAY for r in rows)
    warn = [r for r in rows if not r.extra.get("non_warn")]
    assert [r.employer for r in warn] == ["Sacred Heart League", "Falcon Companies"]
    bucksnort = next(r for r in rows if "Bucksnort" in r.employer)
    assert bucksnort.extra["non_warn"] == "1"
    assert bucksnort.extra["reason"].startswith("NON-WARN")

    shl = warn[0]
    assert shl.notice_date == date(2004, 7, 1)
    assert shl.effective_date == date(2004, 7, 30)
    assert (shl.city, shl.county, shl.zip) == ("Walls", "Desoto", "38680")
    assert shl.layoff_count == 23
    assert shl.closure_type == "Layoff"
    assert shl.naics_code == "511130"  # NAICS line wins over the 4-digit SIC
    assert shl.extra.get("wda") == "Mississippi Partnership"
    assert "non_warn" not in shl.extra

    falcon = warn[1]
    assert falcon.layoff_count == 235
    assert falcon.closure_type == "Closure"


# ---------------------------------------------------------------------------
# PY2010-PY2019 era ("# Affected" count on a continuation grid row)
# ---------------------------------------------------------------------------

def test_ms_parse_archive_py2010_era():
    rows = parse_ms_archive_pdf(_fixture("sample_archive_py2010.pdf"), _REPLAY)

    # 7 events; 4 are "Non-WARN. Rapid Response ..." and tagged, not dropped.
    assert [r.employer for r in rows if r.extra.get("non_warn")] == [
        "Georgia Pacific",
        "Northrop Grumman",
        "North MS State Hospital",
        "Winn Dixie",
    ]
    warn = [r for r in rows if not r.extra.get("non_warn")]
    assert [r.employer for r in warn] == [
        "Simpson Dura-Vent",
        "Butler America, LLC Shelton, CT",
        "CDI Engineering Solutions",
    ]
    # "WARN. Rapid Response activities offered." must NOT trip the tag.
    assert warn[0].extra["reason"].startswith("WARN.")

    simpson = warn[0]  # count "6" sits on its own continuation row
    assert simpson.notice_date == date(2010, 7, 6)
    assert simpson.layoff_count == 6
    assert (simpson.city, simpson.county, simpson.zip) == ("Vicksburg", "Warren", "39180")
    assert simpson.closure_type == "Layoff"
    assert simpson.extra.get("wda") == "South Central"

    butler = warn[1]  # out-of-state HQ address: no "City (County)" to split
    assert (butler.city, butler.county) == (None, None)
    assert butler.zip == "06484"
    assert butler.layoff_count == 50

    cdi = warn[2]  # effective date lands on a continuation row too
    assert cdi.effective_date == date(2010, 12, 31)
    assert cdi.layoff_count == 73
    assert cdi.naics_code == "541330"


# ---------------------------------------------------------------------------
# Era dispatch: PY2020+ quarterlies must keep their existing parser paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "fixture",
    ["sample.pdf", "sample_merged_city.pdf", "sample_stacked_header.pdf"],
)
def test_ms_archive_entry_point_leaves_modern_eras_alone(fixture: str):
    """parse_ms_archive_pdf on a PY2020+ file must match the plain parse
    byte-for-byte (the URL-aware path is used for every Wayback replay,
    including the PY2023-Q4 quarter that dispatches to the stacked parser)."""
    raw = _fixture(fixture)

    def key(r):
        return (r.employer, r.notice_date, r.layoff_count, r.city, r.source_url)

    assert [key(r) for r in parse_ms_archive_pdf(raw, _REPLAY)] == [
        key(r) for r in _parse_pdf(raw)
    ]


# ---------------------------------------------------------------------------
# Static Wayback replay list + backfill registry routing
# ---------------------------------------------------------------------------

def test_ms_discover_archive_urls():
    urls = _discover_ms_archive_urls()

    assert len(urls) == len(_ARCHIVE_CAPTURES) == 52
    assert len(set(urls)) == len(urls)
    assert all(u.startswith("https://web.archive.org/web/") and "id_/" in u for u in urls)
    assert not any("-map" in u for u in urls)
    # 2004-06 era + all 40 PY2010-PY2019 quarters + the delisted PY2023-Q4.
    assert sum("/wps/" in u for u in urls) == 11
    assert sum("/media/" in u for u in urls) == 41
    assert any("py2023-q4-warn-apr2024-jun2024.pdf" in u for u in urls)
    # PY2020-PY2022 copies stay excluded — prod already has them via the hub.
    assert not any("py2020" in u or "py2021" in u or "py2022" in u for u in urls)


def test_backfill_registry_ms_routes_archive_urls_only():
    from warn_v2.scripts.backfill_historical import _BACKFILL

    spec = _BACKFILL["MS"]
    assert spec.parse_for_url("https://mdes.ms.gov/media/1/warn-py2025-q1.pdf") is None
    fn = spec.parse_for_url(_REPLAY)
    assert fn is not None
    rows = fn(_fixture("sample_archive_2004.pdf"))
    assert rows and all(r.source_url == _REPLAY for r in rows)


def test_backfill_registry_ms_discovers_hub_and_archive_union():
    from unittest.mock import patch

    from warn_v2.scripts import backfill_historical as bh

    with patch.object(bh, "_discover_ms_pdf_urls", return_value=["https://hub/a.pdf"]):
        urls = bh._BACKFILL["MS"].discover_urls()

    assert urls[0] == "https://hub/a.pdf"  # live hub kept first (PY2020+ re-runs)
    assert urls[1:] == _discover_ms_archive_urls()
