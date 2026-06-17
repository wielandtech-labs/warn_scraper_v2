"""Add subscriptions table for email alerts (double opt-in).

Revision ID: p7f8a9b0c1d2
Revises: o6e7f8a9b0c1
Create Date: 2026-06-17 00:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p7f8a9b0c1d2"
down_revision: str | None = "o6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                  primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("state", sa.String(2), nullable=True),
        sa.Column("industry", sa.String(8), nullable=True),
        sa.Column("employer_query", sa.String(256), nullable=True),
        sa.Column("frequency", sa.String(16), nullable=False, server_default="daily"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirm_token", sa.String(64), nullable=False),
        sa.Column("unsubscribe_token", sa.String(64), nullable=False),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_subscriptions_email"), "subscriptions", ["email"])
    op.create_index(op.f("ix_subscriptions_confirm_token"), "subscriptions",
                    ["confirm_token"], unique=True)
    op.create_index(op.f("ix_subscriptions_unsubscribe_token"), "subscriptions",
                    ["unsubscribe_token"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_subscriptions_unsubscribe_token"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_confirm_token"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_email"), table_name="subscriptions")
    op.drop_table("subscriptions")
