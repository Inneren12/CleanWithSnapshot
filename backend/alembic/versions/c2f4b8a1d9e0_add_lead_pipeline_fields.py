"""add lead pipeline fields

Revision ID: c2f4b8a1d9e0
Revises: 03149fcdd67f
Create Date: 2026-02-03 10:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c2f4b8a1d9e0"
down_revision = "03149fcdd67f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("leads") as batch_op:
        batch_op.add_column(sa.Column("source", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("campaign", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("keyword", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("landing_page", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_column("landing_page")
        batch_op.drop_column("keyword")
        batch_op.drop_column("campaign")
        batch_op.drop_column("source")
