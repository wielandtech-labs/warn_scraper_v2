"""Add cross_check_runs table — source-cross-check drift signal per state.

Written by ``warn-v2 cross-check``: each row records one live-page-vs-DB diff
for a state (missing_from_db / extra_in_db counts + a sampled JSON slice).
Alerting reads this table, the same pattern as scraper_runs.

Revision ID: o6e7f8a9b0c1
Revises: n5d6e7f8a9b0
Create Date: 2026-06-17 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "o6e7f8a9b0c1"
down_revision: str | None = "n5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cross_check_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("live_rows", sa.Integer(), nullable=True),
        sa.Column("db_active", sa.Integer(), nullable=True),
        sa.Column("missing_from_db", sa.Integer(), nullable=True),
        sa.Column("extra_in_db", sa.Integer(), nullable=True),
        sa.Column("sample", sa.Text(), nullable=True),
    )
    op.create_index(
        op.f("ix_cross_check_runs_state"), "cross_check_runs", ["state"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_cross_check_runs_state"), table_name="cross_check_runs")
    op.drop_table("cross_check_runs")
