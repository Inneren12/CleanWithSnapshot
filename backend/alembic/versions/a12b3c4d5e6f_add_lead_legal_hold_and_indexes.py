"""add lead legal hold and deleted_at index

Revision ID: a12b3c4d5e6f
Revises: fedcba987654
Create Date: 2026-03-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a12b3c4d5e6f"
down_revision = "fedcba987654"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("legal_hold", sa.Boolean(), server_default="0", nullable=False),
    )
    op.create_index(
        "ix_leads_deleted_at_legal_hold",
        "leads",
        ["deleted_at", "legal_hold"],
    )


def downgrade() -> None:
    op.drop_index("ix_leads_deleted_at_legal_hold", table_name="leads")
    op.drop_column("leads", "legal_hold")
