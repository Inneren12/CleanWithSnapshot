"""add notifications center events and reads

Revision ID: 4c2b1c9e7d8a
Revises: 1b2c3d4e5f6a
Create Date: 2026-01-30 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "4c2b1c9e7d8a"
down_revision = "1b2c3d4e5f6a"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "notifications_events",
        sa.Column("id", UUID_TYPE, primary_key=True, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("action_href", sa.String(length=255), nullable=True),
        sa.Column("action_kind", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_notifications_events_org_created",
        "notifications_events",
        ["org_id", "created_at"],
    )
    op.create_index(
        "ix_notifications_events_org_priority",
        "notifications_events",
        ["org_id", "priority"],
    )

    op.create_table(
        "notifications_reads",
        sa.Column("id", UUID_TYPE, primary_key=True, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("event_id", UUID_TYPE, nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["notifications_events.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "event_id", name="uq_notifications_reads_user_event"),
    )
    op.create_index(
        "ix_notifications_reads_org_user",
        "notifications_reads",
        ["org_id", "user_id"],
    )
    op.create_index(
        "ix_notifications_reads_event",
        "notifications_reads",
        ["event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_reads_event", table_name="notifications_reads")
    op.drop_index("ix_notifications_reads_org_user", table_name="notifications_reads")
    op.drop_table("notifications_reads")
    op.drop_index("ix_notifications_events_org_priority", table_name="notifications_events")
    op.drop_index("ix_notifications_events_org_created", table_name="notifications_events")
    op.drop_table("notifications_events")
