"""add maps usage

Revision ID: b2c3d4e5f6a7
Revises: f9c1d2e3a4b5
Create Date: 2026-03-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "f9c1d2e3a4b5"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "maps_usage",
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.org_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("org_id", "day"),
    )
    op.create_index("ix_maps_usage_org_id", "maps_usage", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_maps_usage_org_id", table_name="maps_usage")
    op.drop_table("maps_usage")
