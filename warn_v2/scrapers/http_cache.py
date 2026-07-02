"""Conditional HTTP GET with validators persisted in the source_cache table.

For scrapers that download one file from a stable URL (state XLSX/CSV/PDF
reports), re-downloading and re-parsing an unchanged file every night is pure
waste. ``conditional_get`` sends ``If-None-Match`` / ``If-Modified-Since``
from the previous run and raises ``NotModified`` when the source is unchanged
— either via a 304 response or a byte-identical body (sha256 backstop for
servers without working validators).

Trust rules:

  * ``fetched_at`` records the last *full body* download; it is not bumped on
    304s.  Once it is older than ``_FORCE_REFETCH_AFTER`` the conditional
    headers are omitted, forcing a full download — so a broken server that
    304s unconditionally can freeze a state for at most that long.
  * The hash short-circuit compares actual downloaded bytes, so it is always
    trustworthy (and re-verifies + bumps ``fetched_at``).
  * The cache is only meaningful for content that was successfully INGESTED.
    The entry is written at fetch time, so when parse/validate/store fails
    afterwards the runner calls ``invalidate_state`` — otherwise the next run
    would 304 on content that never made it into the DB (and a parser fix
    could go unexercised until the source next changes).
  * Read-only consumers that must see the live source regardless (cross-check)
    wrap their fetch in ``bypass()``: plain GET, no cache reads or writes —
    they must never consume a change event the nightly scrape hasn't stored.
  * Any source_cache read/write failure degrades to a plain GET — the cache
    must never block a scrape.

HTTP errors propagate as ``httpx.HTTPError`` for the caller's usual
``ScrapeFailed`` wrapping; ``NotModified`` must propagate out of ``fetch()``.
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta

import httpx

from warn_v2.scrapers.base import NotModified

log = logging.getLogger(__name__)

# Distrust an unbroken streak of 304s after this long: force a full download.
_FORCE_REFETCH_AFTER = timedelta(days=7)

_BYPASS: ContextVar[bool] = ContextVar("http_cache_bypass", default=False)


@contextmanager
def bypass() -> Iterator[None]:
    """Make conditional_get behave as a plain GET (no cache reads/writes)."""
    token = _BYPASS.set(True)
    try:
        yield
    finally:
        _BYPASS.reset(token)


def conditional_get(
    url: str,
    *,
    state: str,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> bytes:
    """GET ``url``, raising NotModified when the content is unchanged.

    ``state`` tags the cache row so the runner can invalidate a state's
    entries when ingestion fails after a successful fetch.
    """
    if _BYPASS.get():
        r = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return r.content

    cached = _load(url)
    req_headers = dict(headers or {})
    conditional = cached is not None and _age(cached.fetched_at) <= _FORCE_REFETCH_AFTER
    if conditional:
        if cached.etag:
            req_headers["If-None-Match"] = cached.etag
        if cached.last_modified:
            req_headers["If-Modified-Since"] = cached.last_modified

    r = httpx.get(url, headers=req_headers, timeout=timeout, follow_redirects=True)
    if conditional and r.status_code == 304:
        raise NotModified(f"{url}: 304 Not Modified")
    r.raise_for_status()

    body = r.content
    digest = hashlib.sha256(body).hexdigest()
    _store(
        url,
        state=state,
        etag=r.headers.get("ETag"),
        last_modified=r.headers.get("Last-Modified"),
        content_hash=digest,
    )
    if cached is not None and cached.content_hash == digest:
        raise NotModified(f"{url}: body unchanged (sha256 match)")
    return body


def invalidate_state(state: str) -> None:
    """Drop a state's cache rows so its next fetch is a full re-download.

    Called by the runner when a run fails AFTER fetch (parse/validate/store):
    the fetched content was never ingested, so the cache must not vouch for it.
    """
    from sqlalchemy import delete

    from warn_v2.db.models import SourceCache
    from warn_v2.db.session import session_scope

    try:
        with session_scope() as session:
            session.execute(
                delete(SourceCache).where(SourceCache.state == state.upper())
            )
    except Exception:
        log.exception("source_cache invalidation failed for %s", state)


def _age(fetched_at: datetime) -> timedelta:
    # SQLite returns naive datetimes; everything we store is UTC.
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - fetched_at


class _CacheEntry:
    __slots__ = ("content_hash", "etag", "fetched_at", "last_modified")

    def __init__(
        self,
        etag: str | None,
        last_modified: str | None,
        content_hash: str | None,
        fetched_at: datetime,
    ) -> None:
        self.etag = etag
        self.last_modified = last_modified
        self.content_hash = content_hash
        self.fetched_at = fetched_at


def _load(url: str) -> _CacheEntry | None:
    from warn_v2.db.models import SourceCache
    from warn_v2.db.session import session_scope

    try:
        with session_scope() as session:
            row = session.get(SourceCache, url)
            if row is None:
                return None
            return _CacheEntry(
                row.etag, row.last_modified, row.content_hash, row.fetched_at
            )
    except Exception:
        log.exception("source_cache read failed for %s; plain GET", url)
        return None


def _store(
    url: str,
    *,
    state: str,
    etag: str | None,
    last_modified: str | None,
    content_hash: str,
) -> None:
    from warn_v2.db.models import SourceCache
    from warn_v2.db.session import session_scope

    try:
        with session_scope() as session:
            row = session.get(SourceCache, url)
            if row is None:
                row = SourceCache(url=url)
                session.add(row)
            row.state = state.upper()
            row.etag = etag
            row.last_modified = last_modified
            row.content_hash = content_hash
            row.fetched_at = datetime.now(UTC)
    except Exception:
        log.exception("source_cache write failed for %s", url)
