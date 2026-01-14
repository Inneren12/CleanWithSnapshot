"""add worker onboarding and certificates

Revision ID: 0072_worker_onboarding_and_certificates
Revises: 0071_worker_reviews_and_notes
Create Date: 2025-09-22 00:00:00.000000
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0072_worker_onboarding_and_certificates"
down_revision = "0071_worker_reviews_and_notes"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    op.create_table(
        "worker_onboarding",
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.worker_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column("docs_received", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("background_check", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("training_completed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("first_booking_done", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_worker_onboarding_org_id", "worker_onboarding", ["org_id"])

    op.create_table(
        "worker_certificates",
        sa.Column("cert_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_ORG_ID}'"),
        ),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.worker_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("issued_at", sa.Date()),
        sa.Column("expires_at", sa.Date()),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_worker_certificates_org_id", "worker_certificates", ["org_id"])
    op.create_index("ix_worker_certificates_worker_id", "worker_certificates", ["worker_id"])
    op.create_index("ix_worker_certificates_status", "worker_certificates", ["status"])
    op.create_index("ix_worker_certificates_expires_at", "worker_certificates", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_worker_certificates_expires_at", table_name="worker_certificates")
    op.drop_index("ix_worker_certificates_status", table_name="worker_certificates")
    op.drop_index("ix_worker_certificates_worker_id", table_name="worker_certificates")
    op.drop_index("ix_worker_certificates_org_id", table_name="worker_certificates")
    op.drop_table("worker_certificates")

    op.drop_index("ix_worker_onboarding_org_id", table_name="worker_onboarding")
    op.drop_table("worker_onboarding")
