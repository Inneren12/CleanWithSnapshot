"""add notifications digest settings

Revision ID: 7a4c2d1f8e3b
Revises: 1b2c3d4e5f6a
Create Date: 2026-02-01 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "7a4c2d1f8e3b"
down_revision = "1b2c3d4e5f6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications_digest_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            sa.Uuid(as_uuid=True),
            nullable=False,
        ),
        sa.Column("digest_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("schedule", sa.String(length=16), nullable=False),
        sa.Column("recipients", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "digest_key", name="uq_notifications_digest_settings_org_key"),
    )
    op.create_index(
        "ix_notifications_digest_settings_org_id",
        "notifications_digest_settings",
        ["org_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_digest_settings_org_id", table_name="notifications_digest_settings")
    op.drop_table("notifications_digest_settings")
