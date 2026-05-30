"""Tests for warn_v2.scripts.download_pdfs."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from warn_v2.db.models import Company, Location, Notice
from warn_v2.pipeline.dedup import notice_id
from warn_v2.scrapers.base import NoticeRow
from warn_v2.scripts.download_pdfs import download_pdfs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _insert_notice(
    db,
    *,
    state: str = "AK",
    employer: str = "Acme Corp",
    notice_date: date = date(2024, 1, 15),
    raw_notice_url: str | None = "https://labor.alaska.gov/RR/notices/test.pdf",
    pdf_path: str | None = None,
    layoff_count: int | None = None,
    effective_date: date | None = None,
    address: str | None = None,
) -> Notice:
    row = NoticeRow(state=state, employer=employer, notice_date=notice_date)
    nid = notice_id(row)
    notice = Notice(
        notice_id=nid,
        state=state,
        employer=employer,
        notice_date=notice_date,
        raw_notice_url=raw_notice_url,
        pdf_path=pdf_path,
        layoff_count=layoff_count,
        effective_date=effective_date,
        address=address,
        source_url="https://example.com",
    )
    db.add(notice)
    db.flush()
    return notice


_FAKE_PDF = b"%PDF-1.4 fake content"
_PDF_URL = "https://labor.alaska.gov/RR/notices/test.pdf"


# ---------------------------------------------------------------------------
# Core download behaviour
# ---------------------------------------------------------------------------

@respx.mock
def test_downloads_and_stores_pdf(db, tmp_path):
    """PDF is fetched, written to disk, and pdf_path set on the notice."""
    notice = _insert_notice(db)
    db.commit()

    respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=_FAKE_PDF))

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch("warn_v2.scripts.download_pdfs.extract_warn_fields", return_value={}):
            stats = download_pdfs("AK", pdf_dir=tmp_path)

    db.refresh(notice)
    assert stats["fetched"] == 1
    assert stats["errors"] == 0
    assert notice.pdf_path is not None
    stored = tmp_path / notice.pdf_path
    assert stored.exists()
    assert stored.read_bytes() == _FAKE_PDF


@respx.mock
def test_dry_run_no_file_written(db, tmp_path):
    """Dry run: nothing written to disk, pdf_path stays None."""
    notice = _insert_notice(db)
    db.commit()

    respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=_FAKE_PDF))

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch("warn_v2.scripts.download_pdfs.extract_warn_fields", return_value={}):
            stats = download_pdfs("AK", dry_run=True, pdf_dir=tmp_path)

    db.refresh(notice)
    assert stats["fetched"] == 1
    assert notice.pdf_path is None
    assert not (tmp_path / "ak").exists()


@respx.mock
def test_skips_already_stored(db, tmp_path):
    """Notice with an existing pdf_path is not re-fetched."""
    notice = _insert_notice(db, pdf_path="ak/existing.pdf")
    db.commit()

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats = download_pdfs("AK", pdf_dir=tmp_path)

    assert stats["fetched"] == 0
    assert stats["enriched"] == 0


def test_skips_notice_without_raw_url(db, tmp_path):
    """Notice with raw_notice_url=None is excluded from the query."""
    notice = _insert_notice(db, raw_notice_url=None)
    db.commit()

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats = download_pdfs("AK", pdf_dir=tmp_path)

    assert stats["fetched"] == 0


@respx.mock
def test_http_error_leaves_pdf_path_null(db, tmp_path):
    """HTTP 404 increments errors; pdf_path stays None so it retries next run."""
    notice = _insert_notice(db)
    db.commit()

    respx.get(_PDF_URL).mock(return_value=httpx.Response(404))

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats = download_pdfs("AK", pdf_dir=tmp_path)

    db.refresh(notice)
    assert stats["errors"] == 1
    assert notice.pdf_path is None


# ---------------------------------------------------------------------------
# Field enrichment
# ---------------------------------------------------------------------------

@respx.mock
def test_enrichment_fills_layoff_count(db, tmp_path):
    notice = _insert_notice(db, layoff_count=None)
    db.commit()

    respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=_FAKE_PDF))
    extracted = {"layoff_count": 75}

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch("warn_v2.scripts.download_pdfs.extract_warn_fields", return_value=extracted):
            stats = download_pdfs("AK", pdf_dir=tmp_path)

    db.refresh(notice)
    assert notice.layoff_count == 75
    assert stats["enriched"] == 1


@respx.mock
def test_enrichment_overwrites_60day_effective_date(db, tmp_path):
    """If effective_date is the 60-day WARN estimate, replace it with the real PDF date."""
    notice_dt = date(2024, 1, 15)
    estimated = notice_dt + timedelta(days=60)
    notice = _insert_notice(db, notice_date=notice_dt, effective_date=estimated)
    db.commit()

    real_date = date(2024, 3, 1)
    respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=_FAKE_PDF))
    extracted = {"effective_date": real_date}

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch("warn_v2.scripts.download_pdfs.extract_warn_fields", return_value=extracted):
            stats = download_pdfs("AK", pdf_dir=tmp_path)

    db.refresh(notice)
    assert notice.effective_date == real_date
    assert stats["enriched"] == 1


@respx.mock
def test_enrichment_does_not_overwrite_existing_address(db, tmp_path):
    """Existing address is not overwritten by PDF-extracted address."""
    notice = _insert_notice(db, address="123 Real St, Juneau, AK 99801")
    db.commit()

    respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=_FAKE_PDF))
    extracted = {"address": "456 PDF St, Juneau, AK 99801"}

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch("warn_v2.scripts.download_pdfs.extract_warn_fields", return_value=extracted):
            download_pdfs("AK", pdf_dir=tmp_path)

    db.refresh(notice)
    assert notice.address == "123 Real St, Juneau, AK 99801"


@respx.mock
def test_enrichment_fills_address_when_null(db, tmp_path):
    """NULL address gets populated from PDF extraction."""
    notice = _insert_notice(db, address=None)
    db.commit()

    respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=_FAKE_PDF))
    extracted = {"address": "789 New Ave, Anchorage, AK 99501"}

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch("warn_v2.scripts.download_pdfs.extract_warn_fields", return_value=extracted):
            download_pdfs("AK", pdf_dir=tmp_path)

    db.refresh(notice)
    assert notice.address == "789 New Ave, Anchorage, AK 99501"


# ---------------------------------------------------------------------------
# Location enrichment
# ---------------------------------------------------------------------------

@respx.mock
def test_location_created_from_pdf_city_zip(db, tmp_path):
    """Notice with no location gets one created from PDF-extracted city/zip."""
    notice = _insert_notice(db)
    assert notice.location_id is None
    db.commit()

    respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=_FAKE_PDF))
    extracted = {"city": "Anchorage", "zip": "99501"}

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        # Suppress geocode calls in unit tests
        with patch("warn_v2.geo.geocoder._census_geocode", return_value=None):
            with patch("warn_v2.scripts.download_pdfs.extract_warn_fields", return_value=extracted):
                stats = download_pdfs("AK", pdf_dir=tmp_path)

    db.refresh(notice)
    assert notice.location_id is not None
    loc = db.get(Location, notice.location_id)
    assert loc.city == "Anchorage"
    assert loc.zip == "99501"
    assert stats["enriched"] == 1
