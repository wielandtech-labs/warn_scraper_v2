"""Notice-enricher registry. States self-register on import.

Mirrors `warn_v2.scrapers.registry`: a new state drops a module under
`enrich_notices/states/` that calls `register(MyEnricher())`, and it is picked
up automatically by `get_enricher` / `all_enrichers`.
"""
from __future__ import annotations

import importlib
import pkgutil

from warn_v2.enrich_notices.base import NoticeEnricher

REGISTRY: dict[str, NoticeEnricher] = {}


def register(enricher: NoticeEnricher) -> NoticeEnricher:
    """Register an enricher instance under its uppercased `state` key."""
    key = enricher.state.upper()
    if key in REGISTRY:
        raise ValueError(f"Notice enricher for {key} already registered")
    REGISTRY[key] = enricher
    return enricher


def get_enricher(state: str) -> NoticeEnricher:
    _load_all()
    try:
        return REGISTRY[state.upper()]
    except KeyError as e:
        raise KeyError(f"No notice enricher registered for {state!r}") from e


def all_enrichers() -> list[NoticeEnricher]:
    """Return every registered enricher, sorted by state."""
    _load_all()
    return [REGISTRY[k] for k in sorted(REGISTRY)]


def _load_all() -> None:
    """Import every module under enrich_notices.states so registrations fire."""
    from warn_v2.enrich_notices import states

    for mod_info in pkgutil.iter_modules(states.__path__):
        importlib.import_module(f"{states.__name__}.{mod_info.name}")
