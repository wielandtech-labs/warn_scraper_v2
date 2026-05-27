"""New Hampshire WARN scraper tests.

NH does not publish a public WARN notice listing online. Notices are available
only via public records request to masslayoff@nhes.nh.gov. The scraper is
deregistered; tests are skipped until a public data source is found.
"""
from __future__ import annotations

import pytest

# NH is deregistered: no public online WARN notice listing exists.
pytestmark = pytest.mark.skip(reason="NH deferred: no public WARN listing; records request only")


def test_nh_placeholder() -> None:
    """Placeholder — skipped until NH publishes WARN data online."""
    pass
