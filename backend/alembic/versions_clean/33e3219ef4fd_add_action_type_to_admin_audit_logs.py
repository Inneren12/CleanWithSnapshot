"""add action_type to admin_audit_logs

Revision ID: 33e3219ef4fd
Revises: f37a5ac2c3a3
Create Date: 2026-02-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "33e3219ef4fd"
down_revision = "f37a5ac2c3a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_audit_logs",
        sa.Column("action_type", sa.String(length=10), nullable=False, server_default="WRITE"),
    )


def downgrade() -> None:
    op.drop_column("admin_audit_logs", "action_type")
