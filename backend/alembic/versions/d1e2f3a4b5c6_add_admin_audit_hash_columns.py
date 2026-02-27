"""add admin audit hash columns

Revision ID: d1e2f3a4b5c6
Revises: c0e1f2a3b4c5
Create Date: 2026-02-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d1e2f3a4b5c6"
down_revision = "c0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = [c["name"] for c in inspector.get_columns("admin_audit_logs")]

    if "prev_hash" not in existing_columns:
        op.add_column("admin_audit_logs", sa.Column("prev_hash", sa.String(length=64), nullable=True))

    if "hash" not in existing_columns:
        op.add_column("admin_audit_logs", sa.Column("hash", sa.String(length=64), nullable=True))

    existing_indexes = [ix["name"] for ix in inspector.get_indexes("admin_audit_logs")]
    if "ix_admin_audit_logs_hash" not in existing_indexes:
        op.create_index("ix_admin_audit_logs_hash", "admin_audit_logs", ["hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_admin_audit_logs_hash", table_name="admin_audit_logs")
    op.drop_column("admin_audit_logs", "hash")
    op.drop_column("admin_audit_logs", "prev_hash")
