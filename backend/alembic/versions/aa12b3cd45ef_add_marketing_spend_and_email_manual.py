"""add marketing spend and email manual tables

Revision ID: aa12b3cd45ef
Revises: f0b1c2d3e4f5
Create Date: 2026-02-21 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "aa12b3cd45ef"
down_revision = "f0b1c2d3e4f5"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "marketing_spend",
        sa.Column("spend_id", UUID_TYPE, primary_key=True, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "source", "period", name="uq_marketing_spend_org_source_period"),
    )
    op.create_index("ix_marketing_spend_org_period", "marketing_spend", ["org_id", "period"])

    op.create_table(
        "email_segments",
        sa.Column("segment_id", UUID_TYPE, primary_key=True, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("name", sa.String(length=140), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("org_id", "name", name="uq_email_segments_org_name"),
    )
    op.create_index("ix_email_segments_org_id", "email_segments", ["org_id"])

    op.create_table(
        "email_campaigns",
        sa.Column("campaign_id", UUID_TYPE, primary_key=True, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("segment_id", UUID_TYPE, nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["email_segments.segment_id"], ondelete="SET NULL"),
    )
    op.create_index("ix_email_campaigns_org_status", "email_campaigns", ["org_id", "status"])
    op.create_index("ix_email_campaigns_org_scheduled", "email_campaigns", ["org_id", "scheduled_for"])


def downgrade() -> None:
    op.drop_index("ix_email_campaigns_org_scheduled", table_name="email_campaigns")
    op.drop_index("ix_email_campaigns_org_status", table_name="email_campaigns")
    op.drop_table("email_campaigns")
    op.drop_index("ix_email_segments_org_id", table_name="email_segments")
    op.drop_table("email_segments")
    op.drop_index("ix_marketing_spend_org_period", table_name="marketing_spend")
    op.drop_table("marketing_spend")
