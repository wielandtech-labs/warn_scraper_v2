"""Tests for the GA detail-page enricher parser."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

from warn_v2.scripts import enrich_ga as ega
from warn_v2.scripts.enrich_ga import (
    _find_pdf_url,
    _get_with_backoff,
    _parse_detail_fields,
    _parse_mdY,
    _parse_retry_after,
)

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


# ---------------------------------------------------------------------------
# Rate-limit backoff
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code: int, headers: dict | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "http://example.test"),
                response=httpx.Response(self.status_code),
            )


def test_parse_retry_after() -> None:
    assert _parse_retry_after("7") == 7.0
    assert _parse_retry_after(" 12 ") == 12.0
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("") is None
    assert _parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None  # HTTP-date


def test_get_with_backoff_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([_FakeResp(429), _FakeResp(200)])
    sleeps: list[float] = []
    monkeypatch.setattr(ega.httpx, "get", lambda *a, **k: next(responses))
    monkeypatch.setattr(ega.time, "sleep", lambda s: sleeps.append(s))

    r = _get_with_backoff("http://x", timeout=5, request_delay=3.0)

    assert r.status_code == 200
    assert sleeps == [3.0]  # one backoff: request_delay * 2**0


def test_get_with_backoff_honors_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([_FakeResp(503, {"Retry-After": "9"}), _FakeResp(200)])
    sleeps: list[float] = []
    monkeypatch.setattr(ega.httpx, "get", lambda *a, **k: next(responses))
    monkeypatch.setattr(ega.time, "sleep", lambda s: sleeps.append(s))

    r = _get_with_backoff("http://x", timeout=5, request_delay=3.0)

    assert r.status_code == 200
    assert sleeps == [9.0]  # Retry-After wins over computed backoff


def test_get_with_backoff_exhausts_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(ega.httpx, "get", lambda *a, **k: _FakeResp(429))
    monkeypatch.setattr(ega.time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(httpx.HTTPStatusError):
        _get_with_backoff("http://x", timeout=5, request_delay=2.0)

    # _MAX_ATTEMPTS attempts → backs off on all but the last: 2.0, 4.0
    assert sleeps == [2.0, 4.0]
