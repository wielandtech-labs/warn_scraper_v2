"""add subscription filters, manage token, user link

Revision ID: 3217765813fc
Revises: b3e3a81da979
Create Date: 2026-09-07 04:27:51.420769

"""
from __future__ import annotations

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3217765813fc'
down_revision: str | None = 'b3e3a81da979'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = "fk_subscriptions_user_id_users"

# Minimal projection of the table, used for the manage_token backfill.
_subs = sa.table(
    "subscriptions", sa.column("id", sa.BigInteger), sa.column("manage_token", sa.String)
)


def upgrade() -> None:
    op.add_column('subscriptions', sa.Column('subsector', sa.String(length=8), nullable=True))
    op.add_column('subscriptions', sa.Column('min_layoffs', sa.Integer(), nullable=True))
    op.add_column(
        'subscriptions', sa.Column('closure_category', sa.String(length=16), nullable=True)
    )
    # manage_token is added nullable and backfilled row by row (each value must
    # be unique), then tightened to NOT NULL — adding it NOT NULL outright would
    # fail on any table that already has subscribers.
    op.add_column('subscriptions', sa.Column('manage_token', sa.String(length=64), nullable=True))
    op.add_column('subscriptions', sa.Column('user_id', sa.BigInteger(), nullable=True))

    conn = op.get_bind()
    for (sub_id,) in conn.execute(sa.select(_subs.c.id)).all():
        conn.execute(
            sa.update(_subs)
            .where(_subs.c.id == sub_id)
            .values(manage_token=secrets.token_urlsafe(24))
        )

    # batch_alter_table so the constraint changes also work on SQLite (a plain
    # ALTER of a constraint is unsupported there); on Postgres it is a direct
    # ALTER, same as op.alter_column/op.create_foreign_key.
    with op.batch_alter_table('subscriptions') as batch:
        batch.alter_column('manage_token', existing_type=sa.String(length=64), nullable=False)
        batch.create_foreign_key(
            _FK_NAME, 'users', ['user_id'], ['id'], ondelete='SET NULL'
        )
    op.create_index(
        op.f('ix_subscriptions_manage_token'), 'subscriptions', ['manage_token'], unique=True
    )
    op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_subscriptions_user_id'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_manage_token'), table_name='subscriptions')
    with op.batch_alter_table('subscriptions') as batch:
        batch.drop_constraint(_FK_NAME, type_='foreignkey')
    op.drop_column('subscriptions', 'user_id')
    op.drop_column('subscriptions', 'manage_token')
    op.drop_column('subscriptions', 'closure_category')
    op.drop_column('subscriptions', 'min_layoffs')
    op.drop_column('subscriptions', 'subsector')
