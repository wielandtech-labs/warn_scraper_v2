"""Add pg_trgm extension + GIN trigram indexes for fuzzy/substring search.

Accelerates the existing employer/name ILIKE filters (Postgres can use a
gin_trgm_ops index for ``%term%`` patterns) and backs the new /api/search
similarity ranking. Postgres-only: the SQLite test database has no pg_trgm, so
upgrade/downgrade are no-ops there and the search code falls back to ILIKE.

Revision ID: q8a9b0c1d2e3
Revises: p7f8a9b0c1d2
Create Date: 2026-06-17 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "q8a9b0c1d2e3"
down_revision: str | None = "p7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = [
    ("ix_notices_employer_trgm", "notices", "employer"),
    ("ix_companies_name_trgm", "companies", "name"),
    ("ix_companies_name_normalized_trgm", "companies", "name_normalized"),
]


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, col in _INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin ({col} gin_trgm_ops)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for name, _table, _col in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    # Leave the pg_trgm extension installed — dropping it could affect other objects.
