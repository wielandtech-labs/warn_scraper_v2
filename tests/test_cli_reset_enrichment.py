"""reset-enrichment CLI: metadata-only re-queue of weakly-enriched companies."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from click.testing import CliRunner
from sqlalchemy import select

from warn_v2.cli import main
from warn_v2.db.models import Company


@pytest.fixture()
def runner(db_session_factory):
    return CliRunner()


def _seed(db_session_factory) -> None:
    with db_session_factory() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                Company(
                    name="DnB Co", duns="123456789", enriched_at=now,
                    enrichment_confidence=Decimal("1.00"), enrichment_source="provider",
                ),
                Company(
                    name="Web Co", website="https://web.example", enriched_at=now,
                    enrichment_confidence=Decimal("0.95"), enrichment_source="claude",
                ),
                Company(
                    name="Sec Co", sic_code="3721", enriched_at=now,
                    enrichment_confidence=Decimal("0.90"), enrichment_source="edgar",
                ),
                # Pre-source-field row: enriched, no source, no DUNS (the tail
                # --include-null-source targets).
                Company(name="Legacy Co", enriched_at=now, enrichment_source=None),
                # Source-less but HAS a DUNS — an old D&B hit; must stay untouched.
                Company(
                    name="Legacy DnB Co", duns="987654321", enriched_at=now,
                    enrichment_source=None,
                ),
                Company(name="Pending Co"),
            ]
        )
        session.commit()


def _by_name(db_session_factory, name: str) -> Company:
    with db_session_factory() as session:
        return session.scalar(select(Company).where(Company.name == name))


def test_dry_run_counts_without_writing(runner, db_session_factory):
    _seed(db_session_factory)
    result = runner.invoke(main, ["reset-enrichment", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "claude: 1" in result.output
    assert "edgar: 1" in result.output
    assert "dry run" in result.output
    assert _by_name(db_session_factory, "Web Co").enriched_at is not None


def test_reset_clears_metadata_keeps_data_and_provider_rows(runner, db_session_factory):
    _seed(db_session_factory)
    result = runner.invoke(main, ["reset-enrichment"])
    assert result.exit_code == 0, result.output
    assert "reset 2 companies" in result.output

    web = _by_name(db_session_factory, "Web Co")
    assert web.enriched_at is None  # re-queued for find_pending
    assert web.enrichment_confidence is None
    assert web.enrichment_source is None
    assert web.website == "https://web.example"  # gathered data kept

    sec = _by_name(db_session_factory, "Sec Co")
    assert sec.enriched_at is None
    assert sec.sic_code == "3721"

    dnb = _by_name(db_session_factory, "DnB Co")
    assert dnb.enrichment_source == "provider"  # untouched
    assert dnb.enriched_at is not None


def test_default_reset_leaves_null_source_rows(runner, db_session_factory):
    _seed(db_session_factory)
    result = runner.invoke(main, ["reset-enrichment"])
    assert result.exit_code == 0, result.output
    # The --sources filter can't see source-less rows.
    assert _by_name(db_session_factory, "Legacy Co").enriched_at is not None


def test_include_null_source_resets_only_dunsless_legacy_rows(runner, db_session_factory):
    _seed(db_session_factory)
    result = runner.invoke(
        main, ["reset-enrichment", "--sources", "claude,edgar", "--include-null-source"]
    )
    assert result.exit_code == 0, result.output
    assert "null: 1" in result.output  # only the DUNS-less legacy row counted
    assert "reset 3 companies" in result.output  # claude + edgar + 1 legacy

    legacy = _by_name(db_session_factory, "Legacy Co")
    assert legacy.enriched_at is None  # re-queued

    # The source-less row WITH a DUNS is a real D&B hit — must be untouched.
    legacy_dnb = _by_name(db_session_factory, "Legacy DnB Co")
    assert legacy_dnb.enriched_at is not None
    assert legacy_dnb.duns == "987654321"


def test_provider_source_refused(runner, db_session_factory):
    _seed(db_session_factory)
    result = runner.invoke(main, ["reset-enrichment", "--sources", "provider,claude"])
    assert result.exit_code == 1
    assert "refusing" in result.output
    assert _by_name(db_session_factory, "Web Co").enriched_at is not None
