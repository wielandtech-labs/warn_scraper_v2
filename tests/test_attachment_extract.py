"""Tests for warn_v2.attachment_extract (non-PDF WARN attachment extraction)."""
from __future__ import annotations

import io
import zipfile

from warn_v2.attachment_extract import (
    _classify,
    _csv_to_text,
    _docx_to_text,
    _html_to_text,
    _xlsx_to_text,
    extract_attachment_fields,
)

_DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _make_docx(paragraphs: list[str]) -> bytes:
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs
    )
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc)
    return buf.getvalue()


def _make_xlsx(rows: list[list[str]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# A WARN letter: recipient agency block, a corporate-HQ line, and the worksite.
_WARN_PARAGRAPHS = [
    "Date: February 12, 2026",
    "To: State Rapid Response Unit, Technical College System, Atlanta, GA 30345",
    "From: Impact Outsourcing Solutions, 300 Wilson Road, Griffin, GA 30224",
    "TV Hardware Distribution will permanently close its distribution center "
    "located at 7600 Jonesboro Road, Jonesboro, GA 30236.",
    "This action is affecting 150 full-time employees.",
]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_classify_pdf_by_magic() -> None:
    assert _classify(b"%PDF-1.4 ...", "application/octet-stream", None) == "pdf"


def test_classify_docx_by_members() -> None:
    # A generic/wrong content-type still classifies via the zip member names.
    assert _classify(_make_docx(["x"]), "application/octet-stream", None) == "docx"


def test_classify_xlsx_by_members() -> None:
    assert _classify(_make_xlsx([["x"]]), "application/octet-stream", None) == "xlsx"


def test_classify_by_content_type_and_extension() -> None:
    assert _classify(b"a,b", "text/csv", None) == "csv"
    assert _classify(b"<html></html>", "text/html", None) == "html"
    assert _classify(b"hello", "text/plain", None) == "text"
    assert _classify(b"x", "application/octet-stream", "notice.docx") == "docx"


def test_classify_unknown_returns_none() -> None:
    assert _classify(b"\x00\x01\x02\x03", "application/octet-stream", None) is None


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def test_docx_to_text_one_line_per_paragraph() -> None:
    text = _docx_to_text(_make_docx(["First line", "Second line"]))
    assert text.splitlines() == ["First line", "Second line"]


def test_xlsx_to_text_joins_cells() -> None:
    text = _xlsx_to_text(_make_xlsx([["Job Title", "Total"], ["Welder", "12"]]))
    assert "Job Title Total" in text
    assert "Welder 12" in text


def test_csv_to_text() -> None:
    assert "Macon GA 31201" in _csv_to_text(b"city,state,zip\nMacon,GA,31201\n")


def test_html_to_text() -> None:
    assert "located at 5 Main St" in _html_to_text(b"<p>located at 5 Main St</p>")


# ---------------------------------------------------------------------------
# End-to-end: attachment bytes -> WARN fields (worksite, not recipient)
# ---------------------------------------------------------------------------

def test_docx_extracts_worksite_not_recipient() -> None:
    fields = extract_attachment_fields(
        _make_docx(_WARN_PARAGRAPHS), _DOCX_CT, "letter.docx", "GA"
    )
    # _choose_city_zip must pick the worksite (Jonesboro) over the Rapid-Response
    # recipient block (Atlanta) and the corporate HQ (Griffin).
    assert fields.get("city") == "Jonesboro"
    assert fields.get("zip") == "30236"
    assert fields.get("layoff_count") == 150


def test_xlsx_extracts_worksite_address() -> None:
    rows = [["Worksite"], ["Operations located at 5 Main St, Macon, GA 31201"]]
    fields = extract_attachment_fields(_make_xlsx(rows), _XLSX_CT, "roster.xlsx", "GA")
    assert fields.get("city") == "Macon"
    assert fields.get("zip") == "31201"


def test_html_attachment_extracts_fields() -> None:
    html = b"<html><body><p>Plant closing located at 9 Oak Ave, Rome, GA 30161</p></body></html>"
    fields = extract_attachment_fields(html, "text/html", "notice.html", "GA")
    assert fields.get("city") == "Rome"
    assert fields.get("zip") == "30161"


def test_unsupported_returns_empty() -> None:
    assert extract_attachment_fields(b"\x00\x01\x02", "application/octet-stream", None, "GA") == {}


def test_corrupt_docx_returns_empty() -> None:
    # Zip magic but not a valid OOXML archive — must degrade to {} (never raise).
    assert extract_attachment_fields(b"PK\x03\x04garbage", _DOCX_CT, "x.docx", "GA") == {}
