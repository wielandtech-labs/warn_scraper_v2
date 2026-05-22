"""initial

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-05-22 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("county", sa.String(128), nullable=True),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("zip", sa.String(10), nullable=True),
        sa.Column("lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("lon", sa.Numeric(9, 6), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state", "city", "zip", name="uq_locations_state_city_zip"),
    )
    op.create_index(op.f("ix_locations_state"), "locations", ["state"], unique=False)

    op.create_table(
        "companies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("duns", sa.String(16), nullable=True),
        sa.Column("sic_code", sa.String(8), nullable=True),
        sa.Column("sic_desc", sa.String(256), nullable=True),
        sa.Column("website", sa.String(512), nullable=True),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrichment_confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("enrichment_sources", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_companies_duns"), "companies", ["duns"], unique=False)
    op.create_index(op.f("ix_companies_name"), "companies", ["name"], unique=False)

    op.create_table(
        "notices",
        sa.Column("notice_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("employer", sa.String(512), nullable=False),
        sa.Column("notice_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("layoff_count", sa.Integer(), nullable=True),
        sa.Column("closure_type", sa.String(32), nullable=True),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column("raw_notice_url", sa.String(1024), nullable=True),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("company_id", sa.BigInteger(), nullable=True),
        sa.Column("location_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("notice_id"),
    )
    op.create_index(op.f("ix_notices_notice_date"), "notices", ["notice_date"], unique=False)
    op.create_index(op.f("ix_notices_state"), "notices", ["state"], unique=False)
    op.create_index(
        "ix_notices_state_notice_date",
        "notices",
        ["state", "notice_date"],
        unique=False,
    )

    op.create_table(
        "scraper_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rows_scraped", sa.Integer(), nullable=True),
        sa.Column("rows_new", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("snapshot_path", sa.String(1024), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scraper_runs_state"), "scraper_runs", ["state"], unique=False)


def downgrade() -> None:
    op.drop_table("scraper_runs")
    op.drop_index("ix_notices_state_notice_date", table_name="notices")
    op.drop_index(op.f("ix_notices_state"), table_name="notices")
    op.drop_index(op.f("ix_notices_notice_date"), table_name="notices")
    op.drop_table("notices")
    op.drop_index(op.f("ix_companies_name"), table_name="companies")
    op.drop_index(op.f("ix_companies_duns"), table_name="companies")
    op.drop_table("companies")
    op.drop_index(op.f("ix_locations_state"), table_name="locations")
    op.drop_table("locations")
