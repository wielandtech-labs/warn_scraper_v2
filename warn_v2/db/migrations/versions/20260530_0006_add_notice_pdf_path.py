"""Add notices.pdf_path column for stored PDF location.

When the download-pdfs script fetches a per-notice PDF and saves it to the
PVC, this column records the relative path (e.g. "ak/abc123def456.pdf").
NULL means no PDF has been downloaded yet.

Revision ID: g8c9d0e1f2a3
Revises: f7b8c9d0e1f2
Create Date: 2026-05-30 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "g8c9d0e1f2a3"
down_revision: str | None = "f7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notices", sa.Column("pdf_path", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("notices", "pdf_path")
