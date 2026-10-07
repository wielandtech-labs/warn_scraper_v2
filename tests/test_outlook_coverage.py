"""Coverage masks: holes and publication lag are missing data, lulls are not."""
from __future__ import annotations

from warn_v2.outlook.coverage import exclusion_reason, usable_months
from warn_v2.outlook.panel import month_range

MONTHS = month_range("2023-09", "2026-08")  # 36


def test_publication_frontier_is_masked():
    # California on 2026-10-07: ~120 a month, then 6 and 0 (not yet published).
    counts = [120] * 34 + [6, 0]
    mask = usable_months(counts, MONTHS, first_seen="2001-01")
    assert mask == [True] * 34 + [False, False]
    assert exclusion_reason(mask) is None


def test_ordinary_low_last_month_is_kept():
    counts = [10] * 35 + [6]
    assert all(usable_months(counts, MONTHS, first_seen="2001-01"))


def test_interior_hole_is_masked():
    # Ohio: ~8 a month with a 12-month scraper hole in 2025.
    counts = [8] * 16 + [0] * 12 + [8] * 8
    mask = usable_months(counts, MONTHS, first_seen="2001-01")
    assert mask == [True] * 16 + [False] * 12 + [True] * 8
    assert exclusion_reason(mask) is None  # 24 of 36 is exactly enough
    assert exclusion_reason(mask[1:]) == "only 23 of 35 months usable"


def test_lull_in_a_small_state_is_kept():
    # A ~1-a-month state goes quiet for 3 months: plausible, keep it.
    counts = [1, 2, 1, 0, 0, 0] + [1, 2, 1, 1] * 7 + [1, 1]
    assert all(usable_months(counts, MONTHS, first_seen="2001-01"))


def test_months_before_first_notice_are_masked():
    counts = [0] * 13 + [10] * 23
    mask = usable_months(counts, MONTHS, first_seen="2024-10-14")
    assert mask == [False] * 13 + [True] * 23
    assert exclusion_reason(mask) == "only 23 of 36 months usable"


def test_no_notices_at_all():
    mask = usable_months([0] * 36, MONTHS, first_seen=None)
    assert not any(mask)
    assert exclusion_reason(mask) is not None
