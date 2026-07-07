"""MA historical FY XLSX backfill parser (parse_ma_xlsx).

Two real mass.gov fixtures cover both layouts the reports come in:
  * sample_fy22.xlsx — one sheet per region (region = sheet name), a title row
    then a header at row 3, columns Date Received / Company Name / City /
    Layoff Date / # Affected.
  * sample_fy24.xlsx — a single sheet whose row-1 header matches the live CSV
    (RECEIVED / EMPLOYER / CITY/TOWN / REGION / DATE(S) OF LAYOFFS /
    # EMPLOYEES IMPACTED), region in its own column.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states.ma import parse_ma_xlsx

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
