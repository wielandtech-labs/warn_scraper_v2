"""Tests for warn_v2.pdf_extract — best-effort field extraction from WARN PDF text."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from warn_v2.pdf_extract import _parse_text, extract_warn_fields

# ---------------------------------------------------------------------------
# _parse_text — direct text parsing (no pdfplumber needed)
# ---------------------------------------------------------------------------

def test_extracts_layoff_count_specific_form():
    text = "This notice affects 150 full-time employees effective April 1, 2024."
    result = _parse_text(text)
    assert result["layoff_count"] == 150


def test_extracts_layoff_count_generic_form():
    text = "The company will lay off 42 workers at its facility."
    result = _parse_text(text)
    assert result["layoff_count"] == 42


def test_count_prefers_specific_form():
    text = "We employ 500 employees. This action is affecting 150 employees."
    result = _parse_text(text)
    assert result["layoff_count"] == 150


def test_extracts_effective_date_month_name():
    text = "The layoff will be effective March 15, 2024."
    result = _parse_text(text)
    assert result["effective_date"] == date(2024, 3, 15)


def test_extracts_effective_date_numeric():
    text = "Effective date of layoff: 03/15/2024."
    result = _parse_text(text)
    assert result["effective_date"] == date(2024, 3, 15)


def test_extracts_effective_date_on_or_about():
    text = "The layoff shall be effective on or about January 1, 2025."
    result = _parse_text(text)
    assert result["effective_date"] == date(2025, 1, 1)


def test_extracts_zip_from_city_state_block():
    text = "Acme Corp\n123 Main Street\nAnchorage, AK 99501\nDear Sir,"
    result = _parse_text(text)
    assert result["zip"] == "99501"


def test_extracts_city_from_city_state_block():
    text = "Acme Corp\n123 Main Street\nAnchorage, AK 99501\nDear Sir,"
    result = _parse_text(text)
    assert result["city"] == "Anchorage"


def test_extracts_street_address():
    text = "The facility is located at 456 Industrial Blvd, Wilmington, DE 19801."
    result = _parse_text(text)
    assert "456 Industrial Blvd" in result.get("address", "")


def test_zip_fallback_when_no_city_state():
    text = "Workers at ZIP 12345 will be affected."
    result = _parse_text(text)
    assert result["zip"] == "12345"


def test_returns_empty_on_blank_text():
    result = _parse_text("")
    assert result == {}


def test_missing_fields_not_in_result():
    text = "This is a letter about something unrelated."
    result = _parse_text(text)
    assert "layoff_count" not in result
    assert "effective_date" not in result


# ---------------------------------------------------------------------------
# extract_warn_fields — integration via mocked pdfplumber
# ---------------------------------------------------------------------------

def _make_fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4 fake content"


def test_extract_warn_fields_returns_dict_from_pdf():
    fake_text = "This notice affects 200 employees effective June 1, 2024.\nSeattle, WA 98101"

    with patch("warn_v2.pdf_extract.pdfplumber") as mock_pp:
        page = MagicMock()
        page.extract_text.return_value = fake_text
        mock_pp.open.return_value.__enter__.return_value.pages = [page]

        result = extract_warn_fields(_make_fake_pdf_bytes())

    assert result["layoff_count"] == 200
    assert result["effective_date"] == date(2024, 6, 1)
    assert result["zip"] == "98101"


def test_extract_warn_fields_returns_empty_on_pdfplumber_error():
    with patch("warn_v2.pdf_extract.pdfplumber") as mock_pp:
        mock_pp.open.side_effect = Exception("corrupt PDF")
        result = extract_warn_fields(b"not a pdf")

    assert result == {}


def test_extract_warn_fields_returns_empty_on_empty_pdf():
    with patch("warn_v2.pdf_extract.pdfplumber") as mock_pp:
        page = MagicMock()
        page.extract_text.return_value = None
        mock_pp.open.return_value.__enter__.return_value.pages = [page]

        result = extract_warn_fields(_make_fake_pdf_bytes())

    assert result == {}
