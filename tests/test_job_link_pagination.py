"""JobLink search pagination: fetch() must walk every results page.

The platform paginates at 25 rows per page; before the walk, fetch() read
page 1 only and spike years were silently truncated (AZ 2020: 188 rows on 8
pages, prod held exactly 25 — same fingerprint on KS 2002-2014/2020, ME 2020).
"""
from __future__ import annotations

import json

import pytest

from warn_v2.scrapers import job_link
from warn_v2.scrapers.job_link import JobLinkScraper

HOST = "www.azjobconnection.gov"


class _Scraper(JobLinkScraper):
    """Fresh instance per test — avoids the registry's process singletons."""

    state = "AZ"
    host = HOST


def _row(employer: str, notice_id: int) -> str:
    return (
        "<tr>"
        f'<td><a href="/search/warn_lookups/{notice_id}">{employer}</a></td>'
        "<td>Phoenix</td><td>85001</td><td>Area 1</td>"
        "<td>2020-05-01</td><td>WARN</td>"
        "</tr>"
    )


def _page(rows: str, next_page: int | None) -> str:
    pagination = (
        (
            '<div class="pagination">'
            f'<a class="next_page" rel="next" href="/search/warn_lookups?page={next_page}">'
            "Next &#8594;</a></div>"
        )
        if next_page
        else '<div class="pagination"><span class="next_page disabled">Next</span></div>'
    )
    return f"<html><body><table><tbody>{rows}</tbody></table>{pagination}</body></html>"


@pytest.fixture
def fake_pages(monkeypatch: pytest.MonkeyPatch):
    """Serve a 3-page search result; returns the list of URLs requested."""
    pages = {
        None: _page(_row("Acme p1", 1), next_page=2),
        "2": _page(_row("Beta p2", 2), next_page=3),
        "3": _page(_row("Gamma p3", 3), next_page=None),
    }
    urls: list[str] = []

    class _Resp:
        def __init__(self, body: str) -> None:
            self.text = body
            self.content = body.encode()

        def raise_for_status(self) -> None:
            pass

    def fake_get(url: str, **kwargs) -> _Resp:
        urls.append(url)
        if "/warn_lookups/" in url:  # detail page
            return _Resp("<html><body>no definition list</body></html>")
        page = None
        if "page=" in url:
            page = url.split("page=")[1].split("&")[0]
        return _Resp(pages[page])

    monkeypatch.setattr(job_link.httpx, "get", fake_get)
    monkeypatch.setattr(job_link.time, "sleep", lambda s: None)
    return urls


def test_fetch_walks_all_pages(fake_pages: list[str]) -> None:
    scraper = _Scraper()
    bundle = json.loads(scraper.fetch(year=2020))
    assert len(bundle["more_search_html"]) == 2
    rows = scraper.parse(json.dumps(bundle).encode())
    assert [r.employer for r in rows] == ["Acme p1", "Beta p2", "Gamma p3"]
    assert [u for u in fake_pages if "page=2" in u]
    assert [u for u in fake_pages if "page=3" in u]


def test_fetch_stops_on_repeated_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """A next link pointing at an already-seen URL must not loop forever."""
    # every response's next link points at page=1, forever
    body = _page(_row("Loop", 9), next_page=1)

    class _Resp:
        text = body
        content = body.encode()

        def raise_for_status(self) -> None:
            pass

    calls: list[str] = []

    def fake_get(url: str, **kwargs) -> _Resp:
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(job_link.httpx, "get", fake_get)
    monkeypatch.setattr(job_link.time, "sleep", lambda s: None)
    scraper = _Scraper()
    bundle = json.loads(scraper.fetch(year=2020))
    # first page + the (distinct) page=1 URL, then the walk stops
    assert len(calls) <= 3
    assert bundle["search_html"]


def test_parse_old_bundle_without_more_pages() -> None:
    """Snapshots that pre-date the walk have no more_search_html key."""
    bundle = json.dumps(
        {"search_html": _page(_row("Solo", 5), next_page=None), "details": {}}
    ).encode()
    rows = _Scraper().parse(bundle)
    assert [r.employer for r in rows] == ["Solo"]
