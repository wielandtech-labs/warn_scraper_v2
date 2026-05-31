"""Tests for the GA detail-page enricher parser."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from warn_v2.scripts.enrich_ga import _find_pdf_url, _parse_detail_fields, _parse_mdY

ENTRY_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "ga"
    / "entry_sample.html"
)

# ---------------------------------------------------------------------------
# Fixture-based tests (entry 41068 — Dexter Axle Company)
# ---------------------------------------------------------------------------


def test_parse_detail_fields_fixture() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(ENTRY_FIXTURE.read_bytes(), "html.parser")
    fields = _parse_detail_fields(soup)

    assert fields["Type of Layoff or Closure"] == "Permanent Closure"
    assert fields["First Date of Separation"] == "01/09/2023"
    assert "199 Perimeter Rd" in fields["Company Address"]
    assert fields["Zip Code"] == "31064"
    assert fields["County"] == "Jasper County"


def test_find_pdf_url_fixture() -> None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(ENTRY_FIXTURE.read_bytes(), "html.parser")
    url = _find_pdf_url(soup)
    assert url is not None
    assert "gk-download" in url


# ---------------------------------------------------------------------------
# Unit tests for pure helpers
# ---------------------------------------------------------------------------


def test_parse_mdY_valid() -> None:
    assert _parse_mdY("01/09/2023") == date(2023, 1, 9)
    assert _parse_mdY("12/31/2024") == date(2024, 12, 31)


def test_parse_mdY_invalid() -> None:
    assert _parse_mdY("") is None
    assert _parse_mdY("not-a-date") is None
    assert _parse_mdY("2023-01-09") is None  # wrong format


def test_parse_detail_fields_no_pdf() -> None:
    """A page with no gk-download link returns None."""
    from bs4 import BeautifulSoup

    html = b"""
    <table>
      <tr>
        <th><span class="gv-field-label">Type of Layoff or Closure</span></th>
        <td>Plant Closing</td>
      </tr>
      <tr>
        <th><span class="gv-field-label">First Date of Separation</span></th>
        <td>03/15/2024</td>
      </tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    fields = _parse_detail_fields(soup)
    assert fields["Type of Layoff or Closure"] == "Plant Closing"
    assert fields["First Date of Separation"] == "03/15/2024"

    assert _find_pdf_url(soup) is None


def test_parse_detail_fields_first_zip_wins() -> None:
    """When Zip Code appears twice, only the first value is kept."""
    from bs4 import BeautifulSoup

    html = b"""
    <table>
      <tr>
        <th><span class="gv-field-label">Zip Code</span></th>
        <td>30301</td>
      </tr>
      <tr>
        <th><span class="gv-field-label">Zip Code</span></th>
        <td>31064</td>
      </tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    fields = _parse_detail_fields(soup)
    assert fields["Zip Code"] == "30301"
