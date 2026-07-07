from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states import wa

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "wa"
    / "sample.html"
)


@pytest.fixture
def wa_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_wa_parses_live_sample(wa_sample_html: bytes) -> None:
    scraper = get_scraper("WA")
    rows = scraper.parse(wa_sample_html)
    assert len(rows) >= 5

    first = rows[0]
    assert first.state == "WA"
    assert first.employer == "Starbucks"
    assert first.notice_date == date(2026, 5, 15)
    assert first.effective_date == date(2026, 7, 17)
    assert first.layoff_count == 252
    assert first.city == "Seattle"
    assert first.closure_type == "Permanent"


def test_wa_validation_passes(wa_sample_html: bytes) -> None:
    scraper = get_scraper("WA")
    rows = scraper.parse(wa_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_wa_skips_pagination_rows(wa_sample_html: bytes) -> None:
    scraper = get_scraper("WA")
    rows = scraper.parse(wa_sample_html)
    # No employer should be a bare page number
    employers = [r.employer for r in rows]
    assert not any(e.strip("0123456789. ") == "" for e in employers)


def test_wa_raises_without_table() -> None:
    scraper = get_scraper("WA")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table here</p></body></html>")


def _make_page(page_num: int, total_pages: int, rows_per_page: int = 3) -> bytes:
    """Render a minimal WA GridView page linking pages 2..total_pages."""
    pager = "".join(
        f'<td><a href="javascript:__doPostBack(&#39;ucPSW$gvMain&#39;,'
        f'&#39;Page${p}&#39;)">{p}</a></td>'
        for p in range(2, total_pages + 1)
        if p != page_num
    )
    data_rows = "".join(
        f"<tr><td>Page{page_num}Co{i}</td><td>Seattle</td>"
        f"<td>7/1/2026</td><td>{10 + i}</td><td>Layoff</td>"
        f"<td>Permanent</td><td>5/{page_num}/2026</td><td>notice</td></tr>"
        for i in range(rows_per_page)
    )
    return (
        "<html><body><form method='post' action='./SearchWARN.aspx'>"
        "<input type='hidden' name='__EVENTTARGET' value='' />"
        "<input type='hidden' name='__EVENTARGUMENT' value='' />"
        f"<input type='hidden' name='__VIEWSTATE' value='vs-page-{page_num}' />"
        "<input type='hidden' name='__VIEWSTATEGENERATOR' value='4465BD13' />"
        f"<input type='hidden' name='__EVENTVALIDATION' value='ev-page-{page_num}' />"
        "<input type='text' name='ucPSW$txtSearch' />"
        "<input type='submit' name='ucPSW$btnSearchCompany' value='Search' />"
        "<table id='ucPSW_gvMain'>"
        f"<tr><td colspan='8'><table><tr>{pager}</tr></table></td></tr>"
        "<tr><th>Company</th><th>Location</th><th>Layoff Start Date</th>"
        "<th># of Workers</th><th>Closure Layoff</th><th>Type of Layoff</th>"
        "<th>Received Date</th><th>Notice</th></tr>"
        f"{data_rows}"
        "</table></form></body></html>"
    ).encode()


def test_wa_parse_scans_all_concatenated_pages() -> None:
    scraper = get_scraper("WA")
    bundle = b"\n".join(_make_page(p, total_pages=3) for p in (1, 2, 3))
    rows = scraper.parse(bundle)
    assert len(rows) == 9  # 3 pages * 3 rows
    employers = {r.employer for r in rows}
    assert {"Page1Co0", "Page2Co0", "Page3Co0"} <= employers


def test_wa_fetch_follows_viewstate_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    total_pages = 4
    pages = {p: _make_page(p, total_pages) for p in range(1, total_pages + 1)}
    seen_args: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, content=pages[1])
        form = parse_qs(request.content.decode())
        # A pager postback targets the grid and carries the prior page's tokens,
        # never the search button.
        assert form["__EVENTTARGET"] == [wa._EVENT_TARGET]
        assert form["__VIEWSTATE"][0]
        assert form["__EVENTVALIDATION"][0]
        assert "ucPSW$btnSearchCompany" not in form
        arg = form["__EVENTARGUMENT"][0]
        seen_args.append(arg)
        n = int(arg.split("$")[1])
        # The token carried forward must be the one the previous page minted.
        assert form["__VIEWSTATE"] == [f"vs-page-{n - 1}"]
        return httpx.Response(200, content=pages[n])

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        wa.httpx,
        "Client",
        lambda *a, **kw: real_client(*a, **{**kw, "transport": transport}),
    )

    scraper = get_scraper("WA")
    raw = scraper.fetch()
    rows = scraper.parse(raw)

    assert seen_args == ["Page$2", "Page$3", "Page$4"]
    assert len(rows) == total_pages * 3
