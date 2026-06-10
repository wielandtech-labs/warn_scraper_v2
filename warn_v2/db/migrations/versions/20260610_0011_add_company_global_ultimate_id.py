"""Add companies.global_ultimate_id — D&B id of the global ultimate parent.

Exact, free sibling-grouping key (from the ultimate's profile href) shared by
all subsidiaries of one parent. Additive/nullable.

Revision ID: l3b4c5d6e7f8
Revises: k2a3b4c5d6e7
Create Date: 2026-06-10 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "l3b4c5d6e7f8"
down_revision: str | None = "k2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("global_ultimate_id", sa.String(64), nullable=True))
    op.create_index(
        op.f("ix_companies_global_ultimate_id"), "companies",
        ["global_ultimate_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_companies_global_ultimate_id"), table_name="companies")
    op.drop_column("companies", "global_ultimate_id")
