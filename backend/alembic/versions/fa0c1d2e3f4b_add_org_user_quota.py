"""add org user quota

Revision ID: fa0c1d2e3f4b
Revises: f9c1d2e3a4b5
Create Date: 2026-02-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "fa0c1d2e3f4b"
down_revision = "f9c1d2e3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organization_settings", sa.Column("max_users", sa.Integer(), nullable=True))
    op.create_index(
        "ix_memberships_org_active",
        "memberships",
        ["org_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_memberships_org_active", table_name="memberships")
    op.drop_column("organization_settings", "max_users")
