"""add missing legal_hold and admin_id columns

Revision ID: f37a5ac2c3a3
Revises: c3e9a1b2d4f5
Create Date: 2026-02-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f37a5ac2c3a3"
down_revision = "c3e9a1b2d4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "admin_audit_logs",
        sa.Column("admin_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("admin_audit_logs", "admin_id")
    op.drop_column("leads", "legal_hold")
