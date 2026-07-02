"""JobLink incremental detail fetch: skip pages whose data is already stored.

Covers the DetailSkipping hook end-to-end: JobLinkScraper.fetch() must not
request skipped detail URLs, and the runner must pass exactly the URLs whose
notice already has address AND layoff_count and is older than the re-fetch
window.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from warn_v2.db.models import Notice
from warn_v2.pipeline import runner
from warn_v2.scrapers import job_link
from warn_v2.scrapers.base import DetailSkipping
from warn_v2.scrapers.job_link import JobLinkScraper

_FIXTURE_HTML = (
    Path(__file__).resolve().parent.parent
    / "warn_v2" / "scrapers" / "fixtures" / "az" / "sample.html"
)

_DETAIL_HTML = (
    '<div class="definition-list">'
    "<h3>Address</h3><p>1 Main St</p>"
    "<h3>Number of Employees Affected</h3><p>5</p>"
    "</div>"
)


class _Scraper(JobLinkScraper):
    """Fresh instance per test — avoids the registry's process singletons."""

    state = "AZ"
    host = "www.azjobconnection.gov"


class _Resp:
    def __init__(self, body: str) -> None:
        self.text = body
        self.content = body.encode()

    def raise_for_status(self) -> None:
        pass


@pytest.fixture
def requested(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub httpx.get/time.sleep in job_link; returns the list of URLs hit."""
    urls: list[str] = []
    search_html = _FIXTURE_HTML.read_text()

    def fake_get(url: str, **kwargs) -> _Resp:
        urls.append(url)
        return _Resp(_DETAIL_HTML if "/warn_lookups/" in url else search_html)

    monkeypatch.setattr(job_link.httpx, "get", fake_get)
    monkeypatch.setattr(job_link.time, "sleep", lambda s: None)
    return urls


def _detail_urls(requested: list[str]) -> list[str]:
    return [u for u in requested if "/warn_lookups/" in u]


def test_no_skip_set_fetches_all_details(requested: list[str]) -> None:
    scraper = _Scraper()
    bundle = json.loads(scraper.fetch())
    assert len(_detail_urls(requested)) == 7
    assert len(bundle["details"]) == 7


def test_skip_set_urls_never_requested(requested: list[str]) -> None:
    scraper = _Scraper()
    skip = {
        "https://www.azjobconnection.gov/search/warn_lookups/954",
        "https://www.azjobconnection.gov/search/warn_lookups/955",
    }
    scraper.set_skip_detail_urls(skip)
    bundle = json.loads(scraper.fetch())

    hit = set(_detail_urls(requested))
    assert not hit & skip
    assert len(hit) == 5
    assert set(bundle["details"]) == hit


def test_skipped_rows_parse_with_none_fields(requested: list[str]) -> None:
    scraper = _Scraper()
    skipped_url = "https://www.azjobconnection.gov/search/warn_lookups/954"
    scraper.set_skip_detail_urls({skipped_url})
    rows = scraper.parse(scraper.fetch())

    by_url = {r.raw_notice_url: r for r in rows}
    assert by_url[skipped_url].address is None
    assert by_url[skipped_url].layoff_count is None
    others = [r for r in rows if r.raw_notice_url != skipped_url]
    assert all(r.address == "1 Main St" and r.layoff_count == 5 for r in others)


def test_set_skip_detail_urls_replaces(requested: list[str]) -> None:
    scraper = _Scraper()
    old = "https://www.azjobconnection.gov/search/warn_lookups/954"
    new = "https://www.azjobconnection.gov/search/warn_lookups/955"
    scraper.set_skip_detail_urls({old})
    scraper.set_skip_detail_urls({new})
    scraper.fetch()
    hit = _detail_urls(requested)
    assert old in hit
    assert new not in hit


def test_joblink_scraper_satisfies_protocol() -> None:
    assert isinstance(_Scraper(), DetailSkipping)


# ---------------------------------------------------------------------------
# Runner-side query: which URLs count as "complete"
# ---------------------------------------------------------------------------

def _notice(
    nid: str,
    url: str | None,
    *,
    age_days: int,
    address: str | None = "1 Main St",
    layoff_count: int | None = 10,
    state: str = "AZ",
) -> Notice:
    return Notice(
        notice_id=nid,
        state=state,
        employer=f"Employer {nid}",
        notice_date=date.today() - timedelta(days=age_days),
        address=address,
        layoff_count=layoff_count,
        raw_notice_url=url,
    )


def test_complete_detail_urls_query(db: Session) -> None:
    db.add_all(
        [
            _notice("a", "https://x/warn_lookups/1", age_days=90),
            _notice("b", "https://x/warn_lookups/2", age_days=5),  # too recent
            _notice("c", "https://x/warn_lookups/3", age_days=90, address=None),
            _notice("d", "https://x/warn_lookups/4", age_days=90, layoff_count=None),
            _notice("e", None, age_days=90),  # no detail URL at all
            _notice("f", "https://x/warn_lookups/6", age_days=90, state="DE"),
        ]
    )
    db.commit()
    assert runner._complete_detail_urls("AZ") == {"https://x/warn_lookups/1"}


def test_run_state_passes_skip_set_to_scraper(db: Session, monkeypatch) -> None:
    db.add(_notice("a", "https://x/warn_lookups/1", age_days=90))
    db.commit()

    received: list[set[str]] = []

    class _Stub:
        state = "AZ"
        source_url = "https://x"
        expected_row_range = (0, 10)
        required_fields = frozenset()
        raw_notice_url_is_pdf = False

        def set_skip_detail_urls(self, urls: set[str]) -> None:
            received.append(set(urls))

        def fetch(self) -> bytes:
            return b"{}"

        def parse(self, raw: bytes) -> list:
            return []

    run = runner.run_state(_Stub())
    assert received == [{"https://x/warn_lookups/1"}]
    assert run.status == "ok"


def test_run_state_skip_query_failure_falls_back_to_empty(
    db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(
        runner, "_complete_detail_urls", lambda state: 1 / 0
    )
    received: list[set[str]] = []

    class _Stub:
        state = "AZ"
        source_url = "https://x"
        expected_row_range = (0, 10)
        required_fields = frozenset()
        raw_notice_url_is_pdf = False

        def set_skip_detail_urls(self, urls: set[str]) -> None:
            received.append(set(urls))

        def fetch(self) -> bytes:
            return b"{}"

        def parse(self, raw: bytes) -> list:
            return []

    run = runner.run_state(_Stub())
    assert received == [set()]
    assert run.status == "ok"
