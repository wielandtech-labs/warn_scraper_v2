"""Tests for the public dataset mirror (warn_v2.scripts.export_public_mirror)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
from click.testing import CliRunner

from warn_v2 import cli
from warn_v2.api.routes.exports import NOTICE_PUBLIC_COLS
from warn_v2.db.models import Company, Location, Notice
from warn_v2.scripts import export_public_mirror as mirror

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
# Provider-licensed fields: display only, never redistributed.
ENRICHED = {
    "employee_count", "parent_company_name", "global_ultimate_name", "unique_id",
    "company_unique_id", "hq_address",
}


def _seed(db) -> None:
    co = Company(
        name="Acme Corp", naics_code="334111", naics_desc="Computer Manufacturing",
        employee_count=12_000, parent_company_name="Acme Holdings", unique_id="123456789",
    )
    loc = Location(city="Austin", county="Travis", state="TX", zip="78701",
                   lat=Decimal("30.267153"), lon=Decimal("-97.743057"))
    db.add_all([co, loc])
    db.flush()
    db.add_all(
        [
            Notice(notice_id="a1", state="TX", employer="ACME CORP", notice_date=date(2026, 9, 1),
                   layoff_count=300, company_id=co.id, location_id=loc.id,
                   source_url="https://twc.texas.gov/warn"),
            Notice(notice_id="b2", state="CA", employer="Beta LLC", notice_date=date(2019, 1, 5),
                   layoff_count=None, source_url="https://edd.ca.gov/warn"),
            Notice(notice_id="old", state="CA", employer="Beta LLC", notice_date=date(2019, 1, 5),
                   layoff_count=10, is_superseded=True, source_url="https://edd.ca.gov/warn"),
        ]
    )
    db.commit()


def test_frame_is_public_columns_only(db):
    _seed(db)
    df = mirror.fetch_frame(db)
    assert list(df.columns) == [*NOTICE_PUBLIC_COLS, "detail_url"]
    assert not ENRICHED & set(df.columns)
    assert sorted(df["notice_id"]) == ["a1", "b2"]  # superseded excluded
    row = df.set_index("notice_id").loc["a1"]
    assert row["company_name"] == "Acme Corp" and row["city"] == "Austin"
    assert row["detail_url"] == "https://warnindex.com/notices/a1"
    assert row["lat"] == 30.267153
    assert pd.isna(df.set_index("notice_id").loc["b2", "layoff_count"])  # stays null, not 0


def test_write_mirror_files_and_card(db, tmp_path):
    _seed(db)
    mirror.write_mirror(db, tmp_path, now=NOW)
    parquet = pd.read_parquet(tmp_path / mirror.PARQUET)
    assert len(parquet) == 2 and not ENRICHED & set(parquet.columns)
    assert len(pd.read_csv(tmp_path / mirror.CSV_GZ)) == 2
    card = (tmp_path / mirror.CARD).read_text(encoding="utf-8")
    assert card.startswith("---\nlanguage:")
    assert "license: cc-by-4.0" in card
    assert "- n<1K" in card
    assert "**Notices:** 2" in card
    assert "2019-01-05 to 2026-09-01" in card
    assert "from 2 state" in card
    assert "author = {{WARN Index}}" in card
    assert "howpublished = {\\url{https://warnindex.com}}" in card
    assert "employee_count" not in card


def test_empty_database_still_writes(db, tmp_path):
    df = mirror.write_mirror(db, tmp_path, now=NOW)
    assert df.empty and (tmp_path / mirror.CARD).exists()


def test_size_categories():
    assert mirror._size_category(999) == "n<1K"
    assert mirror._size_category(150_000) == "100K<n<1M"


def test_cli_push_uploads(db, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mirror, "push_mirror", lambda out, repo, token: calls.append((repo, token)))
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    result = CliRunner().invoke(
        cli.main, ["export-public-mirror", "--out", str(tmp_path), "--push", "--repo", "o/r"]
    )
    assert result.exit_code == 0, result.output
    assert calls == [("o/r", "hf_test")]


def test_cli_push_without_token_fails(db, tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    args = ["export-public-mirror", "--out", str(tmp_path), "--push"]
    result = CliRunner().invoke(cli.main, args)
    assert result.exit_code != 0 and "HF_TOKEN" in result.output
