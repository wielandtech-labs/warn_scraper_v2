from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "ga"
    / "sample.html"
)


@pytest.fixture
def ga_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_ga_parses_fixture(ga_sample_html: bytes) -> None:
    scraper = get_scraper("GA")
    rows = scraper.parse(ga_sample_html)
    assert len(rows) >= 5
    assert all(r.state == "GA" for r in rows)

    first = rows[0]
    assert "Dexter Axle" in first.employer
    assert first.notice_date == date(2023, 1, 17)
    assert first.layoff_count == 67
    assert first.raw_notice_url == "https://www.tcsg.edu/warn-public-view/entry/41068/"


def test_ga_raw_notice_urls_present(ga_sample_html: bytes) -> None:
    scraper = get_scraper("GA")
    rows = scraper.parse(ga_sample_html)
    with_url = [r for r in rows if r.raw_notice_url]
    assert len(with_url) == len(rows), "every GA row should have a raw_notice_url"


def test_ga_layoff_counts_present(ga_sample_html: bytes) -> None:
    scraper = get_scraper("GA")
    rows = scraper.parse(ga_sample_html)
    with_count = [r for r in rows if r.layoff_count is not None]
    assert len(with_count) >= 5, "expected at least some rows to have layoff counts"


def test_ga_validation_passes(ga_sample_html: bytes) -> None:
    scraper = get_scraper("GA")
    rows = scraper.parse(ga_sample_html)
    # The fixture is a 25-row snapshot (one DataTables page); validate against
    # a range that fits the fixture rather than the live expected_row_range.
    import types
    fixture_scraper = types.SimpleNamespace(
        state=scraper.state,
        source_url=scraper.source_url,
        expected_row_range=(5, 50),
        required_fields=scraper.required_fields,
    )
    result = validate(fixture_scraper, rows)
    assert result.ok, result.reason


def test_ga_raises_without_table() -> None:
    scraper = get_scraper("GA")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table here</p></body></html>")


class _FakeDataTablesPage:
    """Server-side DataTables over GravityView's REST endpoint, capped at 200 rows."""

    CAP = 200

    def __init__(self, total: int) -> None:
        self.rows = [
            f'<tr><td><a href="https://www.tcsg.edu/warn-public-view/entry/{i}/">GA{i}</a></td>'
            f"<td>Company {i}</td><td>January 17, 2023</td><td>{i}</td><td>{i}</td></tr>"
            for i in range(total)
        ]
        self.length, self.start = 25, 0
        self.spliced: list[str] | None = None

    def _current(self) -> list[str]:
        return self.rows[self.start : self.start + min(self.length, self.CAP)]

    def goto(self, *a, **k) -> None: ...

    def wait_for_selector(self, *a, **k) -> None: ...

    def wait_for_function(self, js, arg, timeout) -> None:
        assert arg != self._info()  # the draw changed it

    def _info(self) -> str:
        shown = self._current()
        return f"Showing {self.start + 1} to {self.start + len(shown)} of {len(self.rows)} entries"

    @contextmanager
    def expect_response(self, predicate, timeout):
        yield
        assert predicate(
            SimpleNamespace(
                url="https://www.tcsg.edu/wp-json/gravityview/v1/views/77460/refresh"
                f"?limit={min(self.length, self.CAP)}&page={self.start // self.CAP + 1}"
            )
        )

    def evaluate(self, js: str, n: int) -> None:
        assert "page.len(n)" in js
        self.length, self.start = n, 0

    def query_selector(self, sel: str):
        assert sel == "#DataTables_Table_0_next:not(.disabled)"
        page_size = min(self.length, self.CAP)
        return object() if self.start + page_size < len(self.rows) else None

    def click(self, sel: str) -> None:
        self.start += min(self.length, self.CAP)

    def eval_on_selector_all(self, sel: str, js: str) -> list[str]:
        return self._current()

    def eval_on_selector(self, sel: str, js: str, rows: list[str] | None = None):
        if sel == ".dataTables_info":
            return self._info()
        self.spliced = rows


def test_ga_navigate_pages_past_the_200_row_cap() -> None:
    # Oct 2026: GravityView's REST endpoint returns at most 200 rows per draw,
    # so "All" stopped at "1 to 200 of 286". _navigate must page through and
    # splice every page into the one table parse() reads.
    scraper = get_scraper("GA")
    page = _FakeDataTablesPage(total=286)
    scraper._navigate(page)

    html = (
        "<table><thead><tr><th>GA WARN ID</th><th>Company Name</th><th>Submitted Date</th>"
        "<th>Total Number of Affected Employees</th><th>Entry ID</th></tr></thead>"
        f"<tbody>{''.join(page.spliced)}</tbody></table>"
    ).encode()
    rows = scraper.parse(html)
    assert len(rows) == 286
    assert len({r.raw_notice_url for r in rows}) == 286
