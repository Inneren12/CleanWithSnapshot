"""add admin audit hash columns

Revision ID: b1c2d3e4f5a6
Revises: c0e1f2a3b4c5
Create Date: 2026-02-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e2d3c4b5a6f7"
down_revision = "c0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin_audit_logs", sa.Column("prev_hash", sa.String(length=64), nullable=True))
    op.add_column("admin_audit_logs", sa.Column("hash", sa.String(length=64), nullable=True))
    op.create_index("ix_admin_audit_logs_hash", "admin_audit_logs", ["hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_admin_audit_logs_hash", table_name="admin_audit_logs")
    op.drop_column("admin_audit_logs", "hash")
    op.drop_column("admin_audit_logs", "prev_hash")
