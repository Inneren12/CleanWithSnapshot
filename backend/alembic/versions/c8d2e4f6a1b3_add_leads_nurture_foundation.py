"""add leads nurture foundation

Revision ID: c8d2e4f6a1b3
Revises: f9c1d2e3a4b5
Create Date: 2026-03-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8d2e4f6a1b3"
down_revision = "f9c1d2e3a4b5"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "nurture_campaigns",
        sa.Column("campaign_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id"),
        sa.UniqueConstraint("org_id", "key", name="uq_nurture_campaigns_org_key"),
    )
    op.create_index("ix_nurture_campaigns_org_id", "nurture_campaigns", ["org_id"])

    op.create_table(
        "nurture_steps",
        sa.Column("step_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("campaign_id", UUID_TYPE, nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("delay_hours", sa.Integer(), nullable=False),
        sa.Column(
            "channel",
            sa.Enum("email", "sms", "log_only", name="nurture_channel"),
            nullable=False,
        ),
        sa.Column("template_key", sa.String(length=255), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["nurture_campaigns.campaign_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("step_id"),
        sa.UniqueConstraint(
            "org_id",
            "campaign_id",
            "step_index",
            name="uq_nurture_steps_org_campaign_index",
        ),
    )
    op.create_index(
        "ix_nurture_steps_org_campaign",
        "nurture_steps",
        ["org_id", "campaign_id"],
    )

    op.create_table(
        "nurture_enrollments",
        sa.Column("enrollment_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", UUID_TYPE, nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "paused", "completed", "cancelled", name="nurture_enrollment_status"),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["nurture_campaigns.campaign_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("enrollment_id"),
    )
    op.create_index(
        "ix_nurture_enrollments_org_lead",
        "nurture_enrollments",
        ["org_id", "lead_id"],
    )
    op.create_index(
        "ix_nurture_enrollments_org_campaign",
        "nurture_enrollments",
        ["org_id", "campaign_id"],
    )

    op.create_table(
        "nurture_step_log",
        sa.Column("log_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("enrollment_id", UUID_TYPE, nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum("planned", "sent", "skipped", "failed", name="nurture_step_log_status"),
            nullable=False,
            server_default=sa.text("'planned'"),
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["enrollment_id"], ["nurture_enrollments.enrollment_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("log_id"),
        sa.UniqueConstraint(
            "org_id",
            "idempotency_key",
            name="uq_nurture_step_log_org_idempotency",
        ),
    )
    op.create_index(
        "ix_nurture_step_log_org_enrollment",
        "nurture_step_log",
        ["org_id", "enrollment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_nurture_step_log_org_enrollment", table_name="nurture_step_log")
    op.drop_table("nurture_step_log")
    op.drop_index("ix_nurture_enrollments_org_campaign", table_name="nurture_enrollments")
    op.drop_index("ix_nurture_enrollments_org_lead", table_name="nurture_enrollments")
    op.drop_table("nurture_enrollments")
    op.drop_index("ix_nurture_steps_org_campaign", table_name="nurture_steps")
    op.drop_table("nurture_steps")
    op.drop_index("ix_nurture_campaigns_org_id", table_name="nurture_campaigns")
    op.drop_table("nurture_campaigns")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS nurture_step_log_status")
        op.execute("DROP TYPE IF EXISTS nurture_enrollment_status")
        op.execute("DROP TYPE IF EXISTS nurture_channel")
