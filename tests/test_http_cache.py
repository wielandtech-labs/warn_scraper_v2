"""Tests for conditional_get (warn_v2/scrapers/http_cache.py)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from warn_v2.db.models import SourceCache
from warn_v2.scrapers import http_cache
from warn_v2.scrapers.base import NotModified
from warn_v2.scrapers.http_cache import bypass, invalidate_state

URL = "https://example.gov/warn.xlsx"


def conditional_get(url: str) -> bytes:
    return http_cache.conditional_get(url, state="NV")


class _Resp:
    def __init__(self, status_code: int, content: bytes = b"", headers: dict | None = None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        import httpx

        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=None, response=None  # type: ignore[arg-type]
            )


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch):
    """Stub httpx.get inside http_cache; test sets .response, reads .requests."""

    class _Recorder:
        response: _Resp = _Resp(200, b"body")
        requests: list[dict] = []

        def __call__(self, url: str, *, headers=None, timeout=None, follow_redirects=None):
            self.requests.append({"url": url, "headers": dict(headers or {})})
            return self.response

    rec = _Recorder()
    monkeypatch.setattr(http_cache.httpx, "get", rec)
    return rec


def _cache_row(db: Session) -> SourceCache | None:
    return db.get(SourceCache, URL)


def test_first_fetch_stores_validators(db: Session, http) -> None:
    http.response = _Resp(
        200, b"v1", {"ETag": '"abc"', "Last-Modified": "Mon, 01 Jun 2026 00:00:00 GMT"}
    )
    assert conditional_get(URL) == b"v1"
    # No validators existed, so no conditional headers were sent.
    sent = http.requests[0]["headers"]
    assert "If-None-Match" not in sent
    row = _cache_row(db)
    assert row is not None
    assert row.state == "NV"
    assert row.etag == '"abc"'
    assert row.last_modified == "Mon, 01 Jun 2026 00:00:00 GMT"
    assert row.content_hash


def test_304_raises_not_modified(db: Session, http) -> None:
    http.response = _Resp(200, b"v1", {"ETag": '"abc"'})
    conditional_get(URL)
    http.response = _Resp(304)
    with pytest.raises(NotModified):
        conditional_get(URL)
    sent = http.requests[1]["headers"]
    assert sent["If-None-Match"] == '"abc"'


def test_identical_body_raises_not_modified_without_validators(db: Session, http) -> None:
    # Server sends no ETag/Last-Modified: the sha256 backstop catches it.
    http.response = _Resp(200, b"same-bytes")
    conditional_get(URL)
    with pytest.raises(NotModified):
        conditional_get(URL)
    # Second request carried no conditional headers (nothing to send).
    assert "If-None-Match" not in http.requests[1]["headers"]
    assert "If-Modified-Since" not in http.requests[1]["headers"]


def test_changed_body_returns_and_updates_hash(db: Session, http) -> None:
    http.response = _Resp(200, b"v1")
    conditional_get(URL)
    old_hash = _cache_row(db).content_hash
    http.response = _Resp(200, b"v2")
    assert conditional_get(URL) == b"v2"
    db.expire_all()
    assert _cache_row(db).content_hash != old_hash


def test_stale_validators_force_unconditional_get(db: Session, http) -> None:
    http.response = _Resp(200, b"v1", {"ETag": '"abc"'})
    conditional_get(URL)
    # Age the cache row past the force-refetch window.
    row = _cache_row(db)
    row.fetched_at = datetime.now(UTC) - timedelta(days=8)
    db.commit()

    http.response = _Resp(200, b"v1", {"ETag": '"abc"'})
    with pytest.raises(NotModified):  # bytes identical -> still short-circuits
        conditional_get(URL)
    # ...but the request was unconditional (no stale-304 trust).
    assert "If-None-Match" not in http.requests[1]["headers"]
    # Full download refreshes fetched_at.
    db.expire_all()
    assert _cache_row(db).fetched_at > datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)


def test_304_does_not_bump_fetched_at(db: Session, http) -> None:
    http.response = _Resp(200, b"v1", {"ETag": '"abc"'})
    conditional_get(URL)
    before = _cache_row(db).fetched_at
    http.response = _Resp(304)
    with pytest.raises(NotModified):
        conditional_get(URL)
    db.expire_all()
    assert _cache_row(db).fetched_at == before


def test_db_failure_degrades_to_plain_get(http, monkeypatch: pytest.MonkeyPatch) -> None:
    # No db fixture at all: session_scope raises (DATABASE_URL unset in tests
    # unless the factory fixture is used) — must still return the body.
    def _boom():
        raise RuntimeError("no db")

    monkeypatch.setattr("warn_v2.db.session.session_scope", _boom)
    http.response = _Resp(200, b"v1")
    assert conditional_get(URL) == b"v1"


def test_http_error_propagates(db: Session, http) -> None:
    import httpx

    http.response = _Resp(500)
    with pytest.raises(httpx.HTTPError):
        conditional_get(URL)
    assert _cache_row(db) is None


def test_bypass_is_plain_get_and_touches_no_cache(db: Session, http) -> None:
    http.response = _Resp(200, b"v1", {"ETag": '"abc"'})
    conditional_get(URL)
    with bypass():
        assert conditional_get(URL) == b"v1"  # no NotModified despite same bytes
    # Bypass sent no conditional headers and didn't bump the cache row.
    assert "If-None-Match" not in http.requests[1]["headers"]
    # A change seen under bypass must not update the cache (else the nightly
    # scrape would 304 on content it never stored).
    http.response = _Resp(200, b"v2", {"ETag": '"def"'})
    with bypass():
        assert conditional_get(URL) == b"v2"
    db.expire_all()
    assert _cache_row(db).etag == '"abc"'


def test_invalidate_state_forces_full_refetch(db: Session, http) -> None:
    http.response = _Resp(200, b"v1", {"ETag": '"abc"'})
    conditional_get(URL)
    invalidate_state("nv")
    assert _cache_row(db) is None
    # Next call is a plain GET (no validators) and returns the body again.
    http.response = _Resp(200, b"v1", {"ETag": '"abc"'})
    assert conditional_get(URL) == b"v1"
    assert "If-None-Match" not in http.requests[1]["headers"]
