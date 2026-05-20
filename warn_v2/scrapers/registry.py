"""Scraper registry. States self-register on import."""
from __future__ import annotations

import importlib
import pkgutil

from warn_v2.scrapers.base import StateScraper

REGISTRY: dict[str, StateScraper] = {}


def register(scraper: StateScraper) -> StateScraper:
    """Decorator/helper: register a scraper instance under its `state` key."""
    key = scraper.state.upper()
    if key in REGISTRY:
        raise ValueError(f"Scraper for {key} already registered")
    REGISTRY[key] = scraper
    return scraper


def get_scraper(state: str) -> StateScraper:
    _load_all()
    try:
        return REGISTRY[state.upper()]
    except KeyError as e:
        raise KeyError(f"No scraper registered for {state!r}") from e


def all_states() -> list[str]:
    _load_all()
    return sorted(REGISTRY)


def _load_all() -> None:
    """Import every module under warn_v2.scrapers.states so registrations fire."""
    from warn_v2.scrapers import states

    for mod_info in pkgutil.iter_modules(states.__path__):
        importlib.import_module(f"{states.__name__}.{mod_info.name}")
