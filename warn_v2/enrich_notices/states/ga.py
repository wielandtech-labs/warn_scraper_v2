"""GA notice enricher — TCSG entry detail pages.

Thin adapter over `warn_v2.scripts.enrich_ga.enrich_ga`; the parsing logic and
its helpers stay in that module (and its tests).
"""
from __future__ import annotations

from pathlib import Path

from warn_v2.enrich_notices.registry import register


class GAEnricher:
    state = "GA"

    def run(
        self,
        *,
        limit: int | None,
        dry_run: bool,
        pdf_dir: Path,
        request_delay: float,
    ) -> dict[str, int]:
        from warn_v2.scripts.enrich_ga import enrich_ga

        return enrich_ga(
            limit=limit,
            dry_run=dry_run,
            pdf_dir=pdf_dir,
            request_delay=request_delay,
        )


register(GAEnricher())
