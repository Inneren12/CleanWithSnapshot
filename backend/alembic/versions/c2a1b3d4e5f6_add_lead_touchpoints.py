"""add lead touchpoints

Revision ID: c2a1b3d4e5f6
Revises: b2c3d4e5f6a7
Create Date: 2026-03-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c2a1b3d4e5f6"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "lead_touchpoints",
        sa.Column("touchpoint_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("channel", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("campaign", sa.String(length=100), nullable=True),
        sa.Column("medium", sa.String(length=100), nullable=True),
        sa.Column("keyword", sa.String(length=100), nullable=True),
        sa.Column("landing_page", sa.String(length=255), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("touchpoint_id"),
    )
    op.create_index("ix_lead_touchpoints_org_id", "lead_touchpoints", ["org_id"])
    op.create_index("ix_lead_touchpoints_org_lead", "lead_touchpoints", ["org_id", "lead_id"])
    op.create_index("ix_lead_touchpoints_lead_occurred_at", "lead_touchpoints", ["lead_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_lead_touchpoints_lead_occurred_at", table_name="lead_touchpoints")
    op.drop_index("ix_lead_touchpoints_org_lead", table_name="lead_touchpoints")
    op.drop_index("ix_lead_touchpoints_org_id", table_name="lead_touchpoints")
    op.drop_table("lead_touchpoints")
