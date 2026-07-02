"""Runner handling of NotModified: a success run with no parse/store."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.db.models import ScraperRun, SourceCache
from warn_v2.pipeline.runner import run_state
from warn_v2.scrapers.base import NotModified, ParseFailed


class _NotModifiedScraper:
    state = "NV"
    source_url = "https://x"
    expected_row_range = (1, 10)
    required_fields = frozenset()
    raw_notice_url_is_pdf = True

    def fetch(self) -> bytes:
        raise NotModified("https://x: 304 Not Modified")

    def parse(self, raw: bytes) -> list:  # pragma: no cover - must not be called
        raise AssertionError("parse() must not run on NotModified")


def test_not_modified_run_is_persisted_as_success(db: Session) -> None:
    run = run_state(_NotModifiedScraper())
    assert run.status == "not_modified"
    assert run.rows_new == 0
    assert run.rows_scraped is None  # None, not 0 — keeps audit row-drift silent
    assert run.error is None
    assert run.finished_at is not None

    stored = db.execute(select(ScraperRun)).scalars().all()
    assert len(stored) == 1
    assert stored[0].status == "not_modified"


class _ParseFailScraper:
    state = "NV"
    source_url = "https://x"
    expected_row_range = (1, 10)
    required_fields = frozenset()
    raw_notice_url_is_pdf = True

    def fetch(self) -> bytes:
        return b"changed content"

    def parse(self, raw: bytes) -> list:
        raise ParseFailed("layout changed")


def test_post_fetch_failure_invalidates_source_cache(
    db: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fetched-but-never-ingested content must not be vouched for by the
    # cache — otherwise the next run 304s and the data is never stored.
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path))
    db.add(
        SourceCache(
            url="https://x/warn.pdf",
            state="NV",
            etag='"abc"',
            content_hash="deadbeef",
            fetched_at=datetime.now(UTC),
        )
    )
    db.commit()

    run = run_state(_ParseFailScraper())
    assert run.status == "parse_failed"
    assert db.execute(select(SourceCache)).scalars().all() == []
