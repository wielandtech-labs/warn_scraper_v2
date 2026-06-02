"""Per-notice detail-page / PDF enrichment.

Some state sources only publish a thin list view (employer, date, count) and keep
the location, closure type, and supporting PDF behind a per-notice detail page or
attachment. Those states register a `NoticeEnricher` here; the scraper captures
the list view nightly, and the enricher fills the gaps in a throttled second pass.

This mirrors `warn_v2.scrapers.registry`: enrichers self-register on import and
are dispatched by state.
"""
