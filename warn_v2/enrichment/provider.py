"""Enrichment provider plugin interface.

External enrichment providers (e.g. commercial business databases) are loaded
at runtime via the ``ENRICHMENT_PROVIDER_MODULE`` environment variable, keeping
their implementation out of this public repository.

Usage
-----
Set the environment variable to ``pkg.module:ClassName`` where the class
implements the :class:`EnrichmentProvider` protocol::

    ENRICHMENT_PROVIDER_MODULE=mypkg.provider:MyProvider

The class is instantiated with no arguments; it reads its own credentials from
environment variables.

If the variable is unset or empty, :func:`load_provider` returns ``None`` and
the enrichment pipeline falls through to the EDGAR and Claude tiers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


class ProviderUnavailable(Exception):
    """Raised by ``lookup`` when the provider could not actually search a company.

    Signals an *infrastructure* condition — session trip, rate cap, cooldown,
    transport error — as distinct from a clean "searched, no confident match"
    (which returns ``None``). The worker leaves the company UNSTAMPED so a
    healthy future run retries it, instead of burning its one provider shot on a
    failure that has nothing to do with whether the company exists in the source.
    """


@dataclass
class ProviderResult:
    """Structured result returned by an external enrichment provider."""

    entity_name: str
    duns: str | None = None
    sic_code: str | None = None
    sic_desc: str | None = None
    naics_code: str | None = None
    naics_desc: str | None = None
    website: str | None = None
    employee_count: int | None = None
    parent_company_name: str | None = None
    parent_duns: str | None = None
    global_ultimate_name: str | None = None
    global_ultimate_duns: str | None = None
    global_ultimate_id: str | None = None
    hq_address: str | None = None
    confidence: float = 0.0
    sources: list[str] = field(default_factory=list)


@runtime_checkable
class EnrichmentProvider(Protocol):
    """Protocol that any external enrichment provider must satisfy.

    Implementations live outside this repo and are injected via
    ``ENRICHMENT_PROVIDER_MODULE``.
    """

    def lookup(self, company_name: str, state: str | None) -> ProviderResult | None:
        """Look up enrichment data for a company.

        Three-way contract:
        - return :class:`ProviderResult` — a confident match (a *hit*);
        - return ``None`` — the source was searched but yielded no confident
          match (a genuine *miss*; the caller may record the attempt);
        - raise :class:`ProviderUnavailable` — the company was *not* actually
          searched (session trip, rate cap, cooldown, transport error). The
          caller leaves the company un-attempted so a healthy run retries it.

        Args:
            company_name: Company name as it appears in the WARN notice.
            state: Two-letter US state code, or ``None`` if unavailable.

        Returns:
            A :class:`ProviderResult` on a hit, or ``None`` on a genuine miss.

        Raises:
            ProviderUnavailable: When the provider could not search the company.
        """
        ...

    def close(self) -> None:
        """Release any held resources (browser session, connection pool, etc.)."""
        ...


def load_provider() -> EnrichmentProvider | None:
    """Dynamically load the configured enrichment provider.

    Reads ``ENRICHMENT_PROVIDER_MODULE`` from the environment.  Returns ``None``
    when the variable is absent or empty, so callers can treat the provider as
    an optional tier without special-casing.

    Raises:
        ValueError: If the env var is set but has an invalid format.
        ImportError: If the module cannot be imported.
        AttributeError: If the class does not exist in the module.
    """
    import importlib
    import os

    spec = os.environ.get("ENRICHMENT_PROVIDER_MODULE", "").strip()
    if not spec:
        return None

    module_path, _, class_name = spec.rpartition(":")
    if not module_path or not class_name:
        raise ValueError(
            f"ENRICHMENT_PROVIDER_MODULE must be 'pkg.module:ClassName', got {spec!r}"
        )

    log.info("Loading enrichment provider from %s", spec)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    instance = cls()

    if not isinstance(instance, EnrichmentProvider):
        raise TypeError(
            f"{spec} does not implement the EnrichmentProvider protocol "
            f"(missing 'lookup' or 'close' method)"
        )

    return instance
