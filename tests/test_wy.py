"""Wyoming WARN scraper tests.

WY DWS does not publish a structured WARN notice listing. The scraper is
deregistered; tests are skipped until a public data source is identified.
"""
from __future__ import annotations

import pytest

# WY is deregistered: no public structured WARN notice listing available.
pytestmark = pytest.mark.skip(reason="WY deferred — no public structured WARN notice listing")


def test_wy_placeholder() -> None:
    """Placeholder — skipped until WY publishes WARN data online."""
    pass
