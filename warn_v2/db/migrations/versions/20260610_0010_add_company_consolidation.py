"""Add company-consolidation columns.

Non-destructive, all nullable:
  canonical_company_id  self-FK; set => this row is a duplicate of the canonical
                        (same legal entity). Canonical rows are NULL.
  name_normalized       normalized name for fallback matching + forward-prevention.
  global_ultimate_duns  DUNS of the global ultimate parent (sibling-grouping key).
  parent_group_key      resolved sibling-grouping key (GU DUNS preferred).

See warn_v2/scripts/consolidate_companies.py.

Revision ID: k2a3b4c5d6e7
Revises: j1f2a3b4c5d6
Create Date: 2026-06-10 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "k2a3b4c5d6e7"
down_revision: str | None = "j1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("canonical_company_id", sa.BigInteger(), nullable=True),
    )
    op.add_column("companies", sa.Column("name_normalized", sa.String(512), nullable=True))
    op.add_column("companies", sa.Column("global_ultimate_duns", sa.String(16), nullable=True))
    op.add_column("companies", sa.Column("parent_group_key", sa.String(512), nullable=True))
    op.create_foreign_key(
        op.f("fk_companies_canonical_company_id_companies"),
        "companies", "companies",
        ["canonical_company_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_companies_canonical_company_id"), "companies",
        ["canonical_company_id"], unique=False,
    )
    op.create_index(
        op.f("ix_companies_name_normalized"), "companies",
        ["name_normalized"], unique=False,
    )
    op.create_index(
        op.f("ix_companies_global_ultimate_duns"), "companies",
        ["global_ultimate_duns"], unique=False,
    )
    op.create_index(
        op.f("ix_companies_parent_group_key"), "companies",
        ["parent_group_key"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_companies_parent_group_key"), table_name="companies")
    op.drop_index(op.f("ix_companies_global_ultimate_duns"), table_name="companies")
    op.drop_index(op.f("ix_companies_name_normalized"), table_name="companies")
    op.drop_index(op.f("ix_companies_canonical_company_id"), table_name="companies")
    op.drop_constraint(
        op.f("fk_companies_canonical_company_id_companies"),
        "companies", type_="foreignkey",
    )
    op.drop_column("companies", "parent_group_key")
    op.drop_column("companies", "global_ultimate_duns")
    op.drop_column("companies", "name_normalized")
    op.drop_column("companies", "canonical_company_id")
