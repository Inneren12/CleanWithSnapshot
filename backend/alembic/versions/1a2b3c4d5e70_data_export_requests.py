"""add data export requests

Revision ID: 1a2b3c4d5e70
Revises: fedcba987654
Create Date: 2026-03-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "1a2b3c4d5e70"
down_revision = "fedcba987654"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "data_export_requests",
        sa.Column("export_id", UUID_TYPE, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_email", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.String(length=128), nullable=True),
        sa.Column("requested_by_type", sa.String(length=32), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.org_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("export_id"),
    )
    op.create_index(
        "ix_data_export_requests_org_status",
        "data_export_requests",
        ["org_id", "status"],
    )
    op.create_index(
        "ix_data_export_requests_org_subject",
        "data_export_requests",
        ["org_id", "subject_id"],
    )
    op.create_index(
        "ix_data_export_requests_org_created",
        "data_export_requests",
        ["org_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_data_export_requests_org_created", table_name="data_export_requests")
    op.drop_index("ix_data_export_requests_org_subject", table_name="data_export_requests")
    op.drop_index("ix_data_export_requests_org_status", table_name="data_export_requests")
    op.drop_table("data_export_requests")
