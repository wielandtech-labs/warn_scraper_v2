"""requeue-provider-misses CLI: undo miss-stamps written while the provider was broken."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from click.testing import CliRunner

from warn_v2.cli import main
from warn_v2.db.models import Company


@pytest.fixture()
def runner():
    return CliRunner()


BAD_WINDOW_START = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)


def _seed(db_session_factory) -> None:
    with db_session_factory() as session:
        session.add_all(
            [
                # Stamped inside the bad window, never enriched — a false miss.
                Company(
                    name="Bridgeport Machines, Inc.",
                    provider_attempted_at=BAD_WINDOW_START + timedelta(hours=6),
                ),
                Company(
                    name="AltaMed",
                    provider_attempted_at=BAD_WINDOW_START + timedelta(hours=12),
                ),
                # Stamped BEFORE the window — a real miss from a healthy run.
                Company(
                    name="Old Miss Co",
                    provider_attempted_at=BAD_WINDOW_START - timedelta(days=3),
                ),
                # Inside the window but actually enriched — a real D&B hit.
                Company(
                    name="Real Hit Co",
                    provider_attempted_at=BAD_WINDOW_START + timedelta(hours=7),
                    enriched_at=BAD_WINDOW_START + timedelta(hours=7),
                    enrichment_source="provider",
                    enrichment_confidence=Decimal("0.95"),
                    duns="123456789",
                ),
                # Never attempted at all.
                Company(name="Untouched Co"),
            ]
        )
        session.commit()


def _stamps(db_session_factory) -> dict[str, bool]:
    with db_session_factory() as session:
        return {
            c.name: c.provider_attempted_at is not None
            for c in session.query(Company).all()
        }


def test_requeue_clears_only_false_misses_in_the_window(db_session_factory, runner) -> None:
    _seed(db_session_factory)

    result = runner.invoke(
        main, ["requeue-provider-misses", "--since", "2026-09-08T00:00:00"]
    )

    assert result.exit_code == 0, result.output
    assert "re-queued 2 companies" in result.output
    stamps = _stamps(db_session_factory)
    assert stamps["Bridgeport Machines, Inc."] is False  # re-queued
    assert stamps["AltaMed"] is False
    assert stamps["Old Miss Co"] is True  # outside the window
    assert stamps["Real Hit Co"] is True  # a real hit keeps its provenance
    assert stamps["Untouched Co"] is False


def test_requeue_dry_run_writes_nothing(db_session_factory, runner) -> None:
    _seed(db_session_factory)

    result = runner.invoke(
        main,
        ["requeue-provider-misses", "--since", "2026-09-08T00:00:00", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "2 provider misses stamped" in result.output
    assert "dry run" in result.output
    assert _stamps(db_session_factory)["AltaMed"] is True


def test_requeue_honours_an_until_bound(db_session_factory, runner) -> None:
    _seed(db_session_factory)

    result = runner.invoke(
        main,
        [
            "requeue-provider-misses",
            "--since", "2026-09-08T00:00:00",
            "--until", "2026-09-08T08:00:00",
        ],
    )

    assert result.exit_code == 0, result.output
    stamps = _stamps(db_session_factory)
    assert stamps["Bridgeport Machines, Inc."] is False  # 06:00, inside
    assert stamps["AltaMed"] is True  # 12:00, past --until


def test_requeue_rejects_a_bad_timestamp(db_session_factory, runner) -> None:
    result = runner.invoke(main, ["requeue-provider-misses", "--since", "last tuesday"])
    assert result.exit_code == 1
    assert "not an ISO 8601 timestamp" in result.output
