"""Add dispatcher alert state table.

Revision ID: 0083_dispatcher_alert_state
Revises: 0082_merge_heads_0081_and_9c1b2f4a8d0b
Create Date: 2026-01-15 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0083_dispatcher_alert_state"
down_revision = "0082_merge_heads_0081_and_9c1b2f4a8d0b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dispatcher_alert_state",
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("alert_key", sa.String(length=120), nullable=False),
        sa.Column("acked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sms_throttle_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.org_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("org_id", "alert_key"),
    )


def downgrade() -> None:
    op.drop_table("dispatcher_alert_state")
