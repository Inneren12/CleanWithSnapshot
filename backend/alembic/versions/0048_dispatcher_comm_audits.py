"""Dispatcher communication audit table

Revision ID: 0048_dispatcher_comm_audits
Revises: 0047_break_glass_sessions
Create Date: 2026-03-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0048_dispatcher_comm_audits"
down_revision = "0047_break_glass_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dispatcher_communication_audits",
        sa.Column("audit_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("booking_id", sa.String(length=36), nullable=False),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("template_id", sa.String(length=120), nullable=False),
        sa.Column("admin_user_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider_msg_id", sa.String(length=120), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_dispatcher_comm_audits_org_sent",
        "dispatcher_communication_audits",
        ["org_id", "sent_at"],
        unique=False,
    )
    op.create_index(
        "ix_dispatcher_comm_audits_booking_sent",
        "dispatcher_communication_audits",
        ["booking_id", "sent_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dispatcher_comm_audits_booking_sent", table_name="dispatcher_communication_audits")
    op.drop_index("ix_dispatcher_comm_audits_org_sent", table_name="dispatcher_communication_audits")
    op.drop_table("dispatcher_communication_audits")
