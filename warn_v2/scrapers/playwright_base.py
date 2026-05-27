"""Base class for Playwright (JS-rendered) scrapers.

Maintains the fetch / parse split required by the self-heal agent:
  fetch()  — renders the page to raw HTML bytes via headless Chromium
  parse()  — pure function on bytes; testable without a browser

Subclasses override _navigate() for pages that need form interaction,
button clicks, year-range selection, or pagination handling.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

from warn_v2.scrapers.base import NoticeRow, ScrapeFailed

# Required inside Docker containers (no user namespace / /dev/shm).
_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]


class PlaywrightScraper:
    state: str
    source_url: str
    expected_row_range: tuple[int, int]
    required_fields: frozenset[str]

    def _navigate(self, page: Page) -> None:
        """Navigate to source_url and wait for content to finish rendering.

        Override in subclasses that need form interaction, pagination, etc.
        Default: simple goto + networkidle wait.
        """
        page.goto(self.source_url, wait_until="networkidle", timeout=60_000)

    def fetch(self) -> bytes:
        """Render the page with headless Chromium and return the full HTML."""
        try:
            from playwright.sync_api import sync_playwright  # lazy: not needed at import time

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
                try:
                    page = browser.new_page()
                    self._navigate(page)
                    html = page.content()
                finally:
                    browser.close()
            return html.encode()
        except Exception as e:
            raise ScrapeFailed(f"{self.state}: Playwright fetch failed: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        raise NotImplementedError
