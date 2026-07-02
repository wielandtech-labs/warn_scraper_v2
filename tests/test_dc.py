from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "dc"
    / "sample.html"
)


@pytest.fixture
def dc_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_dc_parses_live_sample(dc_sample_html: bytes) -> None:
    scraper = get_scraper("DC")
    rows = scraper.parse(dc_sample_html)
    assert len(rows) >= 1
    assert all(r.state == "DC" for r in rows)

    first = rows[0]
    assert first.employer == "Elior North America"
    assert first.notice_date == date(2026, 2, 2)
    assert first.layoff_count == 76
    assert first.closure_type == "Layoff"


def test_dc_code_type_2_is_permanent_closures(dc_sample_html: bytes) -> None:
    scraper = get_scraper("DC")
    rows = scraper.parse(dc_sample_html)
    perm = [r for r in rows if r.closure_type == "Permanent Closures"]
    assert perm, "expected at least one Permanent Closures row (Code Type 2)"


def test_dc_validation_passes(dc_sample_html: bytes) -> None:
    scraper = get_scraper("DC")
    rows = scraper.parse(dc_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_dc_raises_without_table() -> None:
    scraper = get_scraper("DC")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")


# 2020-era year page: count header spelled out ("Number to Employees Affected",
# space between "to" and "Employees") and comma-thousands count cells.
_2020_TABLE = b"""
<html><body><table>
  <tr>
    <th>Notice Date</th><th>Organization Name</th>
    <th>Number to Employees Affected</th>
    <th>Effective Layoff Date</th><th>Code Type</th>
  </tr>
  <tr>
    <td>October 22, 2020</td><td>Washington Metropolitan Area</td>
    <td>1,604</td><td>December 25, 2020</td><td>1</td>
  </tr>
  <tr>
    <td>October 22, 2020</td><td>Cosmos Club</td>
    <td>70</td><td>May 4, 2020</td><td>1</td>
  </tr>
</table></body></html>
"""


def test_dc_2020_header_variant_and_comma_counts() -> None:
    """Older year pages ('Number to Employees Affected', '1,604') yield counts."""
    scraper = get_scraper("DC")
    rows = scraper.parse(_2020_TABLE)
    assert [r.layoff_count for r in rows] == [1604, 70]
    assert rows[0].notice_date == date(2020, 10, 22)
