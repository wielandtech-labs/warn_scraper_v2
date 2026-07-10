"""MA historical backfill parsers (parse_ma_xlsx / parse_ma_xls / the bundle).

Two real mass.gov fixtures cover both layouts the FY reports come in:
  * sample_fy22.xlsx — one sheet per region (region = sheet name), a title row
    then a header at row 3, columns Date Received / Company Name / City /
    Layoff Date / # Affected.
  * sample_fy24.xlsx — a single sheet whose row-1 header matches the live CSV
    (RECEIVED / EMPLOYER / CITY/TOWN / REGION / DATE(S) OF LAYOFFS /
    # EMPLOYEES IMPACTED), region in its own column.

The bundled snapshot (warn_v2/scrapers/data/ma_archive.tar.gz) holds the two
Wayback captures predating the "Previous WARN reports" section:
  * warn-report-fy2020.xls — legacy .xls, same regional layout as FY22, read
    via xlrd (capture 20200828043125).
  * warn-report-week-ending-08-21-20.xlsx — the FY2021 weekly cumulative
    through 2020-08-21 (capture 20200828041524).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states.ma import (
    ma_archive_files,
    parse_ma_archive_member,
    parse_ma_xls,
    parse_ma_xlsx,
)

FIXTURES = Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "ma"


@pytest.fixture
def fy22() -> bytes:
    return (FIXTURES / "sample_fy22.xlsx").read_bytes()


@pytest.fixture
def fy24() -> bytes:
    return (FIXTURES / "sample_fy24.xlsx").read_bytes()


def _find(rows, needle: str):
    return next(r for r in rows if needle in r.employer)


def test_fy22_regional_layout(fy22: bytes) -> None:
    rows = parse_ma_xlsx(fy22, 2022)
    # One row per real notice across the six region sheets (blank spacer rows
    # dropped); region comes from the sheet name.
    assert len(rows) == 37
    assert all(r.state == "MA" for r in rows)
    assert {r.extra.get("region") for r in rows} == {
        "Boston", "Central", "Metro Southwest", "Southeast", "Northeast", "West",
    }


def test_fy22_range_received_date_and_effective(fy22: bytes) -> None:
    # "Date Received" cell is the range string "07/07/2021 - (08/30/2021)":
    # take the first date. The layoff date is a real datetime cell.
    sodexo = _find(parse_ma_xlsx(fy22, 2022), "Sodexo @ Suffolk")
    assert sodexo.notice_date == date(2021, 7, 7)
    assert sodexo.effective_date == date(2021, 7, 31)
    assert sodexo.layoff_count == 74
    assert sodexo.city == "Boston"
    assert sodexo.extra["region"] == "Boston"


def test_fy22_strips_amendment_marker(fy22: bytes) -> None:
    # Source cell is "*UDATED* Schneider Electric" (sic).
    schneider = _find(parse_ma_xlsx(fy22, 2022), "Schneider Electric")
    assert schneider.employer == "Schneider Electric"


def test_fy22_count_from_text_cell(fy22: bytes) -> None:
    # "# Affected" is text like "207 total locations" — recover the integer.
    hso = _find(parse_ma_xlsx(fy22, 2022), "Human Service Option")
    assert hso.layoff_count == 207


def test_fy24_columnar_layout(fy24: bytes) -> None:
    rows = parse_ma_xlsx(fy24, 2024)
    assert len(rows) == 70
    assert all(r.state == "MA" for r in rows)
    # Region is a real column in this layout.
    takeda = _find(rows, "Takeda Pharmaceuticals")
    assert takeda.notice_date == date(2024, 6, 27)
    assert takeda.layoff_count == 189
    assert takeda.city == "Cambridge"
    assert takeda.extra["region"] == "Boston"


def test_fy24_validates(fy24: bytes) -> None:
    rows = parse_ma_xlsx(fy24, 2024)
    result = validate(get_scraper("MA"), rows)
    assert result.ok, result.reason


def test_raises_on_non_xlsx() -> None:
    with pytest.raises(ParseFailed):
        parse_ma_xlsx(b"not a workbook", 2022)


# ---------------------------------------------------------------------------
# Bundled FY2020 + early-FY2021 snapshot (backfill Mode 3b)
# ---------------------------------------------------------------------------

_FY2020_XLS = "warn-report-fy2020.xls"
_WEEKLY_XLSX = "warn-report-week-ending-08-21-20.xlsx"


@pytest.fixture(scope="module")
def archive() -> dict[str, bytes]:
    return dict(ma_archive_files())


def _parse_member(archive: dict[str, bytes], name: str):
    return parse_ma_archive_member(name)(archive[name])


def test_archive_bundle_members(archive: dict[str, bytes]) -> None:
    assert sorted(archive) == [_FY2020_XLS, _WEEKLY_XLSX]


def test_fy2020_xls_regional_layout(archive: dict[str, bytes]) -> None:
    rows = _parse_member(archive, _FY2020_XLS)
    assert len(rows) == 173
    assert all(r.state == "MA" for r in rows)
    per_region: dict[str, int] = {}
    for r in rows:
        region = r.extra["region"]
        per_region[region] = per_region.get(region, 0) + 1
    assert per_region == {
        "Boston": 87,
        "Central": 9,
        "Metro Southwest": 16,
        "Northeast": 25,
        "Southeast": 22,
        "West": 14,
    }
    # Provenance: the Wayback capture, not the (long-gone) live document URL.
    assert all("web.archive.org/web/20200828043125" in r.source_url for r in rows)


def test_fy2020_xls_spot_rows(archive: dict[str, bytes]) -> None:
    rows = _parse_member(archive, _FY2020_XLS)

    # Excel serial date cells → real dates via xlrd's datemode conversion.
    babbo = next(r for r in rows if "Babbo" in r.employer)
    assert babbo.notice_date == date(2019, 7, 23)
    assert babbo.effective_date == date(2019, 9, 15)
    assert babbo.layoff_count == 62
    assert babbo.city == "Boston"

    # Text layoff-date range → first date; text count "T/B/C" → None.
    sisters = next(r for r in rows if "Sisters of the Presentation" in r.employer)
    assert sisters.notice_date == date(2019, 9, 30)
    assert sisters.effective_date == date(2019, 11, 23)  # "11/23/19 - 12/31/19"
    assert sisters.layoff_count is None  # "T/B/C"

    # Text count "201 total (three locations)" → 201.
    urban = next(r for r in rows if r.employer == "Urban Mobility Now, LLC")
    assert urban.layoff_count == 201


def test_fy2020_xls_strips_updated_prefix(archive: dict[str, bytes]) -> None:
    # This era marks amendments "UPDATED: X" / "Update: X" (no asterisks).
    rows = _parse_member(archive, _FY2020_XLS)
    employers = {r.employer for r in rows}
    assert "Cirque Du Soleil (Blue Man Group)" in employers
    assert "MGM Springfield" in employers
    assert not any(e.upper().startswith(("UPDATED:", "UPDATE:")) for e in employers)


def test_weekly_xlsx_early_fy2021(archive: dict[str, bytes]) -> None:
    # FY2021 cumulative through Aug 21 2020 — same regional layout, but .xlsx
    # (openpyxl path) and only five regions had notices by then.
    rows = _parse_member(archive, _WEEKLY_XLSX)
    assert len(rows) == 31
    assert {r.extra["region"] for r in rows} == {
        "Boston", "Central", "Metro Southwest", "Northeast", "Southeast",
    }
    delaware = next(
        r for r in rows
        if "Delaware North" in r.employer and r.city and "Boston" in r.city
    )
    assert delaware.notice_date == date(2020, 7, 3)
    assert delaware.layoff_count == 2778
    assert all("web.archive.org/web/20200828041524" in r.source_url for r in rows)


def test_bundle_no_overlap_with_prod_floor(archive: dict[str, bytes]) -> None:
    # Prod's MA floor is 2021-04 (FY22 backfill); every bundled row must
    # predate it. (One FY2020 row is received-dated 2020-09-10 — a source
    # typo, the capture itself is 2020-08-28 — still comfortably below.)
    rows = [r for name in archive for r in _parse_member(archive, name)]
    assert len(rows) == 204
    assert all(r.notice_date is not None for r in rows)
    assert max(r.notice_date for r in rows) < date(2021, 4, 1)
    assert min(r.notice_date for r in rows) == date(2019, 7, 1)


def test_bundle_validates(archive: dict[str, bytes]) -> None:
    for name in archive:
        result = validate(get_scraper("MA"), _parse_member(archive, name))
        assert result.ok, (name, result.reason)


def test_registry_spec_is_bundled() -> None:
    from warn_v2.scripts.backfill_historical import _BACKFILL

    spec = _BACKFILL["MA"]
    assert spec.bundled_files is not None
    assert spec.parse_for_url is not None
    assert spec.fetch_year is None and spec.discover_urls is None


def test_xls_raises_on_garbage() -> None:
    with pytest.raises(ParseFailed):
        parse_ma_xls(b"not an xls", "http://example.test/x.xls")
