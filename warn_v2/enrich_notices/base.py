"""NoticeEnricher protocol shared by per-state detail-page enrichers."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

# Standard stats keys every enricher's run() reports. Kept as a module constant
# so the CLI can aggregate across enrichers without hard-coding the shape.
STAT_KEYS = ("considered", "enriched", "pdf_fetched", "skipped", "errors")


@runtime_checkable
class NoticeEnricher(Protocol):
    """A throttled second-pass enricher for one state's notices.

    Implementations fetch each notice's detail page / attachment (typically via
    `Notice.raw_notice_url`) and fill missing fields. They must self-throttle and
    back off on rate limits, and return a stats dict keyed by ``STAT_KEYS``.
    """

    state: str

    def run(
        self,
        *,
        limit: int | None,
        dry_run: bool,
        pdf_dir: Path,
        request_delay: float,
    ) -> dict[str, int]:
        ...
