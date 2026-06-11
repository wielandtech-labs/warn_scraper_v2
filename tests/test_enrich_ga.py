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


# ---------------------------------------------------------------------------
# Consecutive-timeout abort
# ---------------------------------------------------------------------------


def test_process_one_returns_timeout_on_timeout_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_process_one returns 'timeout' (not 'errors') on httpx.TimeoutException."""
    from datetime import date

    from warn_v2.db.models import Notice
    from warn_v2.scripts.enrich_ga import _process_one

    monkeypatch.setattr(
        ega.httpx,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(
            httpx.TimeoutException("timed out")
        ),
    )
    monkeypatch.setattr(ega.time, "sleep", lambda s: None)

    notice = Notice(
        notice_id="abc123",
        state="GA",
        employer="Acme",
        notice_date=date(2026, 1, 1),
        raw_notice_url="https://www.tcsg.edu/warn-public-view/entry/12345/",
    )
    result = _process_one(None, notice, pdf_dir=ega.Path("/tmp"), dry_run=True)
    assert result == "timeout"


def test_enrich_ga_aborts_on_consecutive_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """enrich_ga aborts early and returns errors > 0 after _MAX_CONSECUTIVE_TIMEOUTS."""
    from datetime import date

    from warn_v2.db.models import Notice
    from warn_v2.scripts import enrich_ga as ega_mod

    # Build fake notices
    fake_notices = [
        Notice(
            notice_id=f"ga{i:04d}",
            state="GA",
            employer=f"Co {i}",
            notice_date=date(2026, 1, 1),
            raw_notice_url=f"https://www.tcsg.edu/warn-public-view/entry/{i}/",
        )
        for i in range(10)
    ]

    # Patch the DB query to return our fake notices without a real DB
    class _FakeScalars:
        def all(self):
            return fake_notices

    class _FakeSession:
        def scalars(self, _stmt):
            return _FakeScalars()
        def commit(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    monkeypatch.setattr(ega_mod, "session_scope", lambda: _FakeSession())

    # All requests time out
    monkeypatch.setattr(
        ega.httpx,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(httpx.TimeoutException("timed out")),
    )
    monkeypatch.setattr(ega.time, "sleep", lambda s: None)

    stats = ega_mod.enrich_ga(limit=None, dry_run=True)

    # Should have aborted after _MAX_CONSECUTIVE_TIMEOUTS attempts
    assert stats["errors"] == ega_mod._MAX_CONSECUTIVE_TIMEOUTS
    # Far fewer than the full 10 notices processed
    assert stats["considered"] == len(fake_notices)


def test_enrich_ga_unexpected_error_banks_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unexpected (non-httpx) error must stop the run gracefully, not propagate.

    Committed batches survive; the run returns normally so the CronJob doesn't
    flap and the next run resumes from the durably-banked progress.
    """
    from datetime import date

    from warn_v2.db.models import Notice
    from warn_v2.scripts import enrich_ga as ega_mod

    fake_notices = [
        Notice(
            notice_id=f"ga{i:04d}",
            state="GA",
            employer=f"Co {i}",
            notice_date=date(2026, 1, 1),
            raw_notice_url=f"https://www.tcsg.edu/warn-public-view/entry/{i}/",
        )
        for i in range(3)
    ]

    class _FakeScalars:
        def all(self):
            return fake_notices

    class _FakeSession:
        def scalars(self, _stmt):
            return _FakeScalars()
        def commit(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    monkeypatch.setattr(ega_mod, "session_scope", lambda: _FakeSession())
    monkeypatch.setattr(ega.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        ega_mod,
        "_process_one",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    # Must not raise.
    stats = ega_mod.enrich_ga(limit=None, dry_run=False)
    assert stats["considered"] == len(fake_notices)
    assert stats["enriched"] == 0
