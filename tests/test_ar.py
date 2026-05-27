"""Arkansas WARN scraper tests.

AR WARN notices are legally confidential (A.C.A. § 11-10-314) and not
published publicly. The scraper is deregistered; tests are skipped until
a public data source becomes available.
"""
from __future__ import annotations

import pytest

# AR is deregistered: WARN data is confidential under A.C.A. § 11-10-314.
pytestmark = pytest.mark.skip(reason="AR deferred: WARN data confidential under A.C.A. 11-10-314")


def test_ar_placeholder() -> None:
    """Placeholder — skipped until AR publishes WARN data online."""
    pass
