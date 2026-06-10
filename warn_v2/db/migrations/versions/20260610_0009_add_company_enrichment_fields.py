"""Add company enrichment fields for the D&B Hoovers provider tier.

Captures the richer company data the provider can resolve:
  employee_count, parent_company_name, parent_duns, global_ultimate_name,
  hq_address.

Additive migration — all nullable, no data risk. Rows enriched before this
migration are left NULL. ``parent_duns`` is indexed to support future
corporate-family rollups.

Note on public exposure: these columns are populated for internal use; only
low-risk fields are surfaced via the public API (see api/schemas.py CompanyOut)
to respect D&B's redistribution terms.

Revision ID: j1f2a3b4c5d6
Revises: i0e1f2a3b4c5
Create Date: 2026-06-10 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j1f2a3b4c5d6"
down_revision: str | None = "i0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("employee_count", sa.Integer(), nullable=True))
    op.add_column("companies", sa.Column("parent_company_name", sa.String(512), nullable=True))
    op.add_column("companies", sa.Column("parent_duns", sa.String(16), nullable=True))
    op.add_column("companies", sa.Column("global_ultimate_name", sa.String(512), nullable=True))
    op.add_column("companies", sa.Column("hq_address", sa.Text(), nullable=True))
    op.create_index(
        op.f("ix_companies_parent_duns"), "companies", ["parent_duns"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_companies_parent_duns"), table_name="companies")
    op.drop_column("companies", "hq_address")
    op.drop_column("companies", "global_ultimate_name")
    op.drop_column("companies", "parent_duns")
    op.drop_column("companies", "parent_company_name")
    op.drop_column("companies", "employee_count")
