"""add lead retention fields + admin audit columns

Revision ID: d7e4b1c2a3f4
Revises: c3e9a1b2d4f5
Create Date: 2026-05-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d7e4b1c2a3f4"
down_revision = "c3e9a1b2d4f5"
branch_labels = None
depends_on = None


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    inspector = sa.inspect(conn)
    return any(col["name"] == column for col in inspector.get_columns(table))


def _index_exists(conn: sa.engine.Connection, table: str, index: str) -> bool:
    inspector = sa.inspect(conn)
    return any(idx["name"] == index for idx in inspector.get_indexes(table))


def upgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "leads", "pending_deletion"):
        op.add_column(
            "leads",
            sa.Column(
                "pending_deletion",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if not _column_exists(conn, "leads", "legal_hold"):
        op.add_column(
            "leads",
            sa.Column(
                "legal_hold",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if not _column_exists(conn, "leads", "deletion_requested_at"):
        op.add_column(
            "leads",
            sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _column_exists(conn, "leads", "deleted_at"):
        op.add_column(
            "leads",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _index_exists(conn, "leads", "ix_leads_deleted_at_legal_hold"):
        op.create_index(
            "ix_leads_deleted_at_legal_hold",
            "leads",
            ["deleted_at", "legal_hold"],
        )

    if not _column_exists(conn, "admin_audit_logs", "admin_id"):
        op.add_column(
            "admin_audit_logs",
            sa.Column("admin_id", sa.String(length=128), nullable=True),
        )
    if not _column_exists(conn, "admin_audit_logs", "action_type"):
        op.add_column(
            "admin_audit_logs",
            sa.Column(
                "action_type",
                sa.String(length=10),
                nullable=False,
                server_default=sa.text("'WRITE'"),
            ),
        )
    if not _column_exists(conn, "admin_audit_logs", "sensitivity_level"):
        op.add_column(
            "admin_audit_logs",
            sa.Column(
                "sensitivity_level",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'normal'"),
            ),
        )
    if not _column_exists(conn, "admin_audit_logs", "auth_method"):
        op.add_column(
            "admin_audit_logs",
            sa.Column("auth_method", sa.String(length=32), nullable=True),
        )
    if not _column_exists(conn, "admin_audit_logs", "context"):
        op.add_column(
            "admin_audit_logs",
            sa.Column("context", sa.JSON(), nullable=True),
        )

    if not _index_exists(conn, "admin_audit_logs", "ix_admin_audit_logs_action_type"):
        op.create_index(
            "ix_admin_audit_logs_action_type",
            "admin_audit_logs",
            ["action_type"],
        )
    if not _index_exists(conn, "admin_audit_logs", "ix_admin_audit_logs_resource_type"):
        op.create_index(
            "ix_admin_audit_logs_resource_type",
            "admin_audit_logs",
            ["resource_type"],
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _index_exists(conn, "admin_audit_logs", "ix_admin_audit_logs_resource_type"):
        op.drop_index("ix_admin_audit_logs_resource_type", table_name="admin_audit_logs")
    if _index_exists(conn, "admin_audit_logs", "ix_admin_audit_logs_action_type"):
        op.drop_index("ix_admin_audit_logs_action_type", table_name="admin_audit_logs")

    with op.batch_alter_table("admin_audit_logs") as batch_op:
        if _column_exists(conn, "admin_audit_logs", "context"):
            batch_op.drop_column("context")
        if _column_exists(conn, "admin_audit_logs", "auth_method"):
            batch_op.drop_column("auth_method")
        if _column_exists(conn, "admin_audit_logs", "sensitivity_level"):
            batch_op.drop_column("sensitivity_level")
        if _column_exists(conn, "admin_audit_logs", "action_type"):
            batch_op.drop_column("action_type")
        if _column_exists(conn, "admin_audit_logs", "admin_id"):
            batch_op.drop_column("admin_id")

    if _index_exists(conn, "leads", "ix_leads_deleted_at_legal_hold"):
        op.drop_index("ix_leads_deleted_at_legal_hold", table_name="leads")

    with op.batch_alter_table("leads") as batch_op:
        if _column_exists(conn, "leads", "deleted_at"):
            batch_op.drop_column("deleted_at")
        if _column_exists(conn, "leads", "deletion_requested_at"):
            batch_op.drop_column("deletion_requested_at")
        if _column_exists(conn, "leads", "legal_hold"):
            batch_op.drop_column("legal_hold")
        if _column_exists(conn, "leads", "pending_deletion"):
            batch_op.drop_column("pending_deletion")
