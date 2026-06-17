"""Tests for warn_v2.scripts.download_pdfs."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import httpx
import respx

from warn_v2.db.models import Location, Notice
from warn_v2.pipeline.dedup import notice_id
from warn_v2.scrapers.base import NoticeRow
from warn_v2.scripts.download_pdfs import (
    _pdf_states,
    download_pdfs,
    prune_non_pdf,
    re_extract,
)

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
    _insert_notice(db, pdf_path="ak/existing.pdf")
    db.commit()

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats = download_pdfs("AK", pdf_dir=tmp_path)

    assert stats["fetched"] == 0
    assert stats["enriched"] == 0


def test_skips_notice_without_raw_url(db, tmp_path):
    """Notice with raw_notice_url=None is excluded from the query."""
    _insert_notice(db, raw_notice_url=None)
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


# ---------------------------------------------------------------------------
# mkdir hardening
# ---------------------------------------------------------------------------

@respx.mock
def test_stale_file_at_state_dir_path_is_counted_as_error(db, tmp_path):
    """Regression: an earlier run wrote a PDF directly to /var/pdfs/<state> (the
    state directory path itself).  mkdir(..., exist_ok=True) raises FileExistsError
    because exist_ok only suppresses the error when the path is already a directory,
    not when it is a regular file.  The hardened code detects this, logs an error,
    and returns 'errors' rather than crashing the entire job."""
    notice = _insert_notice(db, state="WI", raw_notice_url=_PDF_URL)
    db.commit()

    # Simulate the legacy bug: create a regular file where the state dir should be.
    stale_file = tmp_path / "wi"
    stale_file.write_bytes(b"stale pdf data")
    assert stale_file.is_file()

    respx.get(_PDF_URL).mock(return_value=httpx.Response(200, content=_FAKE_PDF))

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch("warn_v2.scripts.download_pdfs.extract_warn_fields", return_value={}):
            stats = download_pdfs("WI", pdf_dir=tmp_path)

    # Should not crash; the notice is counted as an error (retriable next run).
    assert stats["errors"] == 1
    assert stats["fetched"] == 0
    # The stale file must be untouched — we don't silently remove production data.
    assert stale_file.is_file()
    assert stale_file.read_bytes() == b"stale pdf data"
    # pdf_path must not be set — the notice is retryable.
    db.refresh(notice)
    assert notice.pdf_path is None


# ---------------------------------------------------------------------------
# Non-PDF guard (JobLink states + content-type check)
# ---------------------------------------------------------------------------

def test_pdf_states_excludes_joblink_and_ga():
    """JobLink states link to HTML detail pages, GA to GravityView — both excluded."""
    states = _pdf_states()
    for code in ("AZ", "DE", "KS", "ME", "VT", "GA"):
        assert code not in states
    assert "AK" in states


def test_joblink_state_returns_early(db, tmp_path):
    """--state AZ is refused: raw_notice_url is an HTML detail page, not a PDF."""
    _insert_notice(db, state="AZ", raw_notice_url="https://azjobconnection.gov/search/warn_lookups/42")
    db.commit()

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats = download_pdfs("AZ", pdf_dir=tmp_path)

    assert stats == {"fetched": 0, "enriched": 0, "skipped": 0, "errors": 0}


@respx.mock
def test_non_pdf_response_not_stored(db, tmp_path):
    """A 200 HTML response is counted as an error; nothing written, pdf_path stays NULL."""
    notice = _insert_notice(db)
    db.commit()

    respx.get(_PDF_URL).mock(
        return_value=httpx.Response(
            200, content=b"<html>not a pdf</html>", headers={"content-type": "text/html"}
        )
    )

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats = download_pdfs("AK", pdf_dir=tmp_path)

    db.refresh(notice)
    assert stats["errors"] == 1
    assert stats["fetched"] == 0
    assert notice.pdf_path is None
    assert not (tmp_path / "ak").exists()


@respx.mock
def test_pdf_magic_bytes_accepted_despite_wrong_content_type(db, tmp_path):
    """A real PDF served with a generic content-type is still stored."""
    notice = _insert_notice(db)
    db.commit()

    respx.get(_PDF_URL).mock(
        return_value=httpx.Response(
            200, content=_FAKE_PDF, headers={"content-type": "application/octet-stream"}
        )
    )

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch("warn_v2.scripts.download_pdfs.extract_warn_fields", return_value={}):
            stats = download_pdfs("AK", pdf_dir=tmp_path)

    db.refresh(notice)
    assert stats["fetched"] == 1
    assert notice.pdf_path is not None


# ---------------------------------------------------------------------------
# prune-non-pdf
# ---------------------------------------------------------------------------

def _store_file(tmp_path, rel: str, content: bytes) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


def test_prune_removes_non_pdf_and_clears_path(db, tmp_path):
    """HTML stored as .pdf is deleted and pdf_path cleared; real PDFs are kept."""
    bad = _insert_notice(db, employer="Bad Corp", pdf_path="ks/bad.pdf", state="KS")
    good = _insert_notice(db, employer="Good Corp", pdf_path="ct/good.pdf", state="CT")
    db.commit()
    _store_file(tmp_path, "ks/bad.pdf", b"<html>detail page</html>")
    _store_file(tmp_path, "ct/good.pdf", _FAKE_PDF)

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats = prune_non_pdf(pdf_dir=tmp_path)

    db.refresh(bad)
    db.refresh(good)
    assert stats == {"checked": 2, "pruned": 1, "missing": 0, "kept": 1}
    assert bad.pdf_path is None
    assert not (tmp_path / "ks" / "bad.pdf").exists()
    assert good.pdf_path == "ct/good.pdf"
    assert (tmp_path / "ct" / "good.pdf").read_bytes() == _FAKE_PDF

    # Idempotent: a second run finds nothing to prune.
    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats2 = prune_non_pdf(pdf_dir=tmp_path)
    assert stats2 == {"checked": 1, "pruned": 0, "missing": 0, "kept": 1}


def test_prune_missing_file_clears_path(db, tmp_path):
    """A pdf_path whose file vanished from the PVC is cleared so it can re-fetch."""
    notice = _insert_notice(db, pdf_path="ak/gone.pdf")
    db.commit()

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats = prune_non_pdf(pdf_dir=tmp_path)

    db.refresh(notice)
    assert stats["missing"] == 1
    assert notice.pdf_path is None


def test_prune_dry_run_changes_nothing(db, tmp_path):
    notice = _insert_notice(db, pdf_path="ks/bad.pdf", state="KS")
    db.commit()
    _store_file(tmp_path, "ks/bad.pdf", b"<html>junk</html>")

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats = prune_non_pdf(dry_run=True, pdf_dir=tmp_path)

    db.refresh(notice)
    assert stats["pruned"] == 1
    assert notice.pdf_path == "ks/bad.pdf"
    assert (tmp_path / "ks" / "bad.pdf").exists()


def test_prune_state_filter(db, tmp_path):
    """--state KS only touches KS rows."""
    ks = _insert_notice(db, employer="KS Corp", pdf_path="ks/bad.pdf", state="KS")
    me = _insert_notice(db, employer="ME Corp", pdf_path="me/bad.pdf", state="ME")
    db.commit()
    _store_file(tmp_path, "ks/bad.pdf", b"<html>junk</html>")
    _store_file(tmp_path, "me/bad.pdf", b"<html>junk</html>")

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats = prune_non_pdf("KS", pdf_dir=tmp_path)

    db.refresh(ks)
    db.refresh(me)
    assert stats["checked"] == 1
    assert ks.pdf_path is None
    assert me.pdf_path == "me/bad.pdf"


# ---------------------------------------------------------------------------
# re-extract
# ---------------------------------------------------------------------------

def test_re_extract_upgrades_estimate_date(db, tmp_path):
    """A stored PDF re-read with the current extractor upgrades the 60-day estimate."""
    notice_dt = date(2024, 1, 15)
    estimated = notice_dt + timedelta(days=60)
    notice = _insert_notice(
        db, notice_date=notice_dt, effective_date=estimated, pdf_path="ak/n.pdf"
    )
    db.commit()
    _store_file(tmp_path, "ak/n.pdf", _FAKE_PDF)

    real_date = date(2024, 4, 1)
    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch(
            "warn_v2.scripts.download_pdfs.extract_warn_fields",
            return_value={"effective_date": real_date},
        ):
            stats = re_extract(pdf_dir=tmp_path)

    db.refresh(notice)
    assert stats == {"considered": 1, "enriched": 1, "missing": 0, "errors": 0}
    assert notice.effective_date == real_date


def test_re_extract_dry_run_counts_but_does_not_write(db, tmp_path):
    notice_dt = date(2024, 1, 15)
    estimated = notice_dt + timedelta(days=60)
    notice = _insert_notice(
        db, notice_date=notice_dt, effective_date=estimated, pdf_path="ak/n.pdf"
    )
    db.commit()
    _store_file(tmp_path, "ak/n.pdf", _FAKE_PDF)

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch(
            "warn_v2.scripts.download_pdfs.extract_warn_fields",
            return_value={"effective_date": date(2024, 4, 1)},
        ):
            stats = re_extract(dry_run=True, pdf_dir=tmp_path)

    db.refresh(notice)
    assert stats["enriched"] == 1  # extractable fields found
    assert notice.effective_date == estimated  # but nothing written


def test_re_extract_missing_file_skipped(db, tmp_path):
    _insert_notice(db, pdf_path="ak/gone.pdf")
    db.commit()

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats = re_extract(pdf_dir=tmp_path)

    assert stats == {"considered": 1, "enriched": 0, "missing": 1, "errors": 0}


def test_re_extract_no_fields_not_enriched(db, tmp_path):
    _insert_notice(db, pdf_path="ak/n.pdf")
    db.commit()
    _store_file(tmp_path, "ak/n.pdf", _FAKE_PDF)

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch(
            "warn_v2.scripts.download_pdfs.extract_warn_fields", return_value={}
        ):
            stats = re_extract(pdf_dir=tmp_path)

    assert stats["enriched"] == 0


def test_re_extract_creates_location_from_city_zip(db, tmp_path):
    """HI recovery path: re-reading a stored PDF mints a Location from the
    extracted worksite city/zip (which backfill-geo then geocodes)."""
    notice = _insert_notice(db, state="HI", raw_notice_url=None, pdf_path="hi/n.pdf")
    assert notice.location_id is None
    db.commit()
    _store_file(tmp_path, "hi/n.pdf", _FAKE_PDF)

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch("warn_v2.geo.geocoder._census_geocode", return_value=None):
            with patch(
                "warn_v2.scripts.download_pdfs.extract_warn_fields",
                return_value={"city": "Honolulu", "zip": "96815"},
            ):
                stats = re_extract("HI", pdf_dir=tmp_path)

    db.refresh(notice)
    assert stats == {"considered": 1, "enriched": 1, "missing": 0, "errors": 0}
    assert notice.location_id is not None
    loc = db.get(Location, notice.location_id)
    assert loc.city == "Honolulu"
    assert loc.zip == "96815"


def test_re_extract_state_filter(db, tmp_path):
    ct = _insert_notice(db, employer="CT Corp", state="CT", pdf_path="ct/a.pdf")
    _insert_notice(db, employer="NE Corp", state="NE", pdf_path="ne/b.pdf")
    db.commit()
    _store_file(tmp_path, "ct/a.pdf", _FAKE_PDF)
    _store_file(tmp_path, "ne/b.pdf", _FAKE_PDF)

    with patch("warn_v2.scripts.download_pdfs.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        with patch(
            "warn_v2.scripts.download_pdfs.extract_warn_fields",
            return_value={"layoff_count": 42},
        ):
            stats = re_extract("CT", pdf_dir=tmp_path)

    db.refresh(ct)
    assert stats["considered"] == 1
    assert ct.layoff_count == 42
