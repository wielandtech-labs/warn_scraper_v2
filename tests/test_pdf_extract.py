"""Tests for warn_v2.pdf_extract — best-effort field extraction from WARN PDF text."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from warn_v2.pdf_extract import _normalize_state, _parse_text, extract_warn_fields

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
    # No text layer AND OCR unavailable in the test env -> {}.
    with patch("warn_v2.pdf_extract.pdfplumber") as mock_pp:
        page = MagicMock()
        page.extract_text.return_value = None
        mock_pp.open.return_value.__enter__.return_value.pages = [page]

        result = extract_warn_fields(_make_fake_pdf_bytes())

    assert result == {}


# ---------------------------------------------------------------------------
# State-aware city/ZIP selection (skip recipient block + out-of-state HQ)
# ---------------------------------------------------------------------------

def test_city_zip_prefers_in_state_most_frequent():
    # A WARN letter: addressed to the state capital, repeats the worksite city,
    # and lists an out-of-state corporate HQ.
    text = (
        "The Honorable Governor\nCharleston, WV 25305\n"
        "Affected employees at the Mine:\nLorado, WV 25630\nLorado, WV 25630\n"
        "Corporate HQ: Dallas, TX 75201\n"
    )
    result = _parse_text(text, "WV")
    assert result["city"] == "Lorado"
    assert result["zip"] == "25630"


def test_city_zip_skips_out_of_state_hq():
    text = "Worksite: Kailua, HI 96734\nHQ: Rancho Santa Margarita, CA 92688\n"
    result = _parse_text(text, "HI")
    assert result["city"] == "Kailua"
    assert result["zip"] == "96734"


def test_city_zip_no_state_falls_back_to_first():
    text = "Charleston, WV 25305\nLorado, WV 25630\n"
    result = _parse_text(text, None)
    assert result["city"] == "Charleston"  # legacy first-match behavior


def test_city_zip_no_in_state_match_returns_nothing():
    # Only an out-of-state address for a WV notice -> no city (no false HQ pin).
    text = "Dallas, TX 75201\n"
    result = _parse_text(text, "WV")
    assert "city" not in result and "zip" not in result


def test_city_zip_excludes_known_recipient_zip():
    # WorkForce WV recipient (25305) is excluded; the located-at worksite wins.
    text = (
        "Rapid Response, Bldg. 3, Room 312\nCharleston, WV 25305\n"
        "a total closure of the plant located at 1 Moore Ave, Buckhannon, WV 26201\n"
    )
    result = _parse_text(text, "WV")
    assert result["city"] == "Buckhannon"
    assert result["zip"] == "26201"


def test_city_zip_excludes_recipient_by_marker():
    text = (
        "Dear Dislocated Worker Unit Director:\n4 Randolph Ave., Suite 102\n"
        "Elkins, WV 26241\n"
        "Our facility is located at 100 Main St, Moorefield, WV 26836.\n"
    )
    result = _parse_text(text, "WV")
    assert result["city"] == "Moorefield"
    assert result["zip"] == "26836"


# ---------------------------------------------------------------------------
# Full state-name worksites (WARN letters often spell the state out)
# ---------------------------------------------------------------------------

def test_normalize_state():
    assert _normalize_state("HI") == "HI"
    assert _normalize_state("hi") == "HI"
    assert _normalize_state("Hawaii") == "HI"
    assert _normalize_state("WEST VIRGINIA") == "WV"
    assert _normalize_state("Notastate") is None


def test_city_zip_full_state_name_worksite():
    # Real HI WARN pattern: recipient (DLIR, 96813) spelled out, worksite spelled out.
    text = (
        "Department of Labor and Industrial Relations\nHonolulu, Hawaii 96813\n"
        "operations located at 1001 Kamokila Blvd, Kapolei, Hawaii 96707\n"
    )
    result = _parse_text(text, "HI")
    assert result["city"] == "Kapolei"
    assert result["zip"] == "96707"


def test_city_zip_full_state_name_recipient_zip_still_excluded():
    # The 96813 recipient is excluded even when the state is spelled "Hawaii".
    text = (
        "Rapid Response Unit\nHonolulu, Hawaii 96813\n"
        "the facility located at 91-110 Hanua St, Kapolei, Hawaii 96707\n"
    )
    result = _parse_text(text, "HI")
    assert result["city"] == "Kapolei"
    assert result["zip"] == "96707"


def test_city_zip_multiword_state_name_longest_match():
    # "West Virginia" must win over "Virginia" (longest-first alternation).
    text = (
        "The Honorable Governor\nCharleston, West Virginia 25305\n"
        "plant located at 1 Moore Ave, Lorado, West Virginia 25630\n"
    )
    result = _parse_text(text, "WV")
    assert result["city"] == "Lorado"
    assert result["zip"] == "25630"


# ---------------------------------------------------------------------------
# OCR fallback for scanned-image PDFs
# ---------------------------------------------------------------------------

def test_ocr_fallback_used_when_no_text_layer():
    with patch("warn_v2.pdf_extract.pdfplumber") as mock_pp, patch(
        "warn_v2.pdf_extract._ocr_text",
        return_value="affecting 12 employees\nLorado, WV 25630",
    ) as mock_ocr:
        page = MagicMock()
        page.extract_text.return_value = None
        mock_pp.open.return_value.__enter__.return_value.pages = [page]

        result = extract_warn_fields(_make_fake_pdf_bytes(), "WV")

    mock_ocr.assert_called_once()
    assert result["layoff_count"] == 12
    assert result["zip"] == "25630"


def test_ocr_not_called_when_text_layer_present():
    with patch("warn_v2.pdf_extract.pdfplumber") as mock_pp, patch(
        "warn_v2.pdf_extract._ocr_text"
    ) as mock_ocr:
        page = MagicMock()
        page.extract_text.return_value = "affecting 5 employees"
        mock_pp.open.return_value.__enter__.return_value.pages = [page]

        extract_warn_fields(_make_fake_pdf_bytes(), "WV")

    mock_ocr.assert_not_called()


def test_ocr_text_degrades_to_empty_without_libs():
    # pytesseract/pdf2image are not installed in the test env -> "" (never raises).
    from warn_v2.pdf_extract import _ocr_text

    assert _ocr_text(b"%PDF-1.4 fake") == ""


# ---------------------------------------------------------------------------
# _capped_ocr_dpi — bound OCR rasterization memory for oversized pages
# ---------------------------------------------------------------------------

def test_capped_ocr_dpi_unchanged_for_normal_page():
    from warn_v2.pdf_extract import _capped_ocr_dpi

    with patch("warn_v2.pdf_extract.pdfplumber") as mock_pp:
        page = MagicMock(width=612, height=792)  # US Letter, in points
        mock_pp.open.return_value.__enter__.return_value.pages = [page]

        assert _capped_ocr_dpi(_make_fake_pdf_bytes(), 200, 3) == 200


def test_capped_ocr_dpi_lowered_for_oversized_page():
    from warn_v2.pdf_extract import _capped_ocr_dpi

    with patch("warn_v2.pdf_extract.pdfplumber") as mock_pp:
        # A scan embedded at an abnormal point size — a real TN Wayback
        # capture was seen at 1600x2140pt vs. ~612x792pt for a normal letter
        # page, which OOM'd the pdf-downloader Job at dpi=200 (~4444x5944px).
        page = MagicMock(width=1600, height=2140)
        mock_pp.open.return_value.__enter__.return_value.pages = [page]

        dpi = _capped_ocr_dpi(_make_fake_pdf_bytes(), 200, 3)

    assert dpi < 200
    assert 2140 * dpi / 72 <= 2500  # longest side stays within the raster budget


def test_capped_ocr_dpi_falls_back_on_open_error():
    from warn_v2.pdf_extract import _capped_ocr_dpi

    with patch("warn_v2.pdf_extract.pdfplumber") as mock_pp:
        mock_pp.open.side_effect = Exception("corrupt PDF")
        assert _capped_ocr_dpi(b"not a pdf", 200, 3) == 200
