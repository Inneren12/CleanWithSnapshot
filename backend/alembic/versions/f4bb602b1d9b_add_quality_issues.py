"""add quality issues

Revision ID: f4bb602b1d9b
Revises: c4b6c7ab0034
Create Date: 2026-01-16 07:18:32.912242

"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

revision = "f4bb602b1d9b"
down_revision = "c4b6c7ab0034"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    op.create_table(
        "quality_issues",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column(
            "booking_id",
            sa.String(length=36),
            sa.ForeignKey("bookings.booking_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.worker_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "client_id",
            sa.String(length=36),
            sa.ForeignKey("client_users.client_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("summary", sa.String(length=255)),
        sa.Column("details", sa.Text()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'open'")),
        sa.Column("severity", sa.String(length=16)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("first_response_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_type", sa.String(length=64)),
        sa.Column("resolution_value", sa.String(length=255)),
        sa.Column(
            "assignee_user_id",
            UUID_TYPE,
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_quality_issues_org_id", "quality_issues", ["org_id"])
    op.create_index("ix_quality_issues_org_status", "quality_issues", ["org_id", "status"])
    op.create_index("ix_quality_issues_org_severity", "quality_issues", ["org_id", "severity"])
    op.create_index("ix_quality_issues_org_created", "quality_issues", ["org_id", "created_at"])
    op.create_index("ix_quality_issues_booking_id", "quality_issues", ["booking_id"])
    op.create_index("ix_quality_issues_worker_id", "quality_issues", ["worker_id"])
    op.create_index("ix_quality_issues_client_id", "quality_issues", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_quality_issues_client_id", table_name="quality_issues")
    op.drop_index("ix_quality_issues_worker_id", table_name="quality_issues")
    op.drop_index("ix_quality_issues_booking_id", table_name="quality_issues")
    op.drop_index("ix_quality_issues_org_created", table_name="quality_issues")
    op.drop_index("ix_quality_issues_org_severity", table_name="quality_issues")
    op.drop_index("ix_quality_issues_org_status", table_name="quality_issues")
    op.drop_index("ix_quality_issues_org_id", table_name="quality_issues")
    op.drop_table("quality_issues")
