"""admin audit read/write classification

Revision ID: c0e1f2a3b4c5
Revises: a1b2c3d4e5f6
Create Date: 2026-02-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c0e1f2a3b4c5"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

IMMUTABLE_UPDATE_FN = "prevent_admin_audit_updates"
IMMUTABLE_DELETE_FN = "prevent_admin_audit_deletes"


def upgrade() -> None:
    op.add_column(
        "admin_audit_logs",
        sa.Column("admin_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "admin_audit_logs",
        sa.Column(
            "action_type",
            sa.String(length=10),
            nullable=False,
            server_default="WRITE",
        ),
    )
    op.add_column(
        "admin_audit_logs",
        sa.Column(
            "sensitivity_level",
            sa.String(length=20),
            nullable=False,
            server_default="normal",
        ),
    )
    op.add_column(
        "admin_audit_logs",
        sa.Column("auth_method", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "admin_audit_logs",
        sa.Column("context", sa.JSON(), nullable=True),
    )

    op.create_index("ix_admin_audit_logs_action_type", "admin_audit_logs", ["action_type"])
    op.create_index("ix_admin_audit_logs_resource_type", "admin_audit_logs", ["resource_type"])

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {IMMUTABLE_UPDATE_FN}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'admin audit logs are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {IMMUTABLE_DELETE_FN}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'admin audit logs are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_audit_logs_no_update
        BEFORE UPDATE ON admin_audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_admin_audit_updates();
        """
    )
    op.execute(
        """
        CREATE TRIGGER admin_audit_logs_no_delete
        BEFORE DELETE ON admin_audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_admin_audit_deletes();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS admin_audit_logs_no_update ON admin_audit_logs")
        op.execute("DROP TRIGGER IF EXISTS admin_audit_logs_no_delete ON admin_audit_logs")
        op.execute(f"DROP FUNCTION IF EXISTS {IMMUTABLE_UPDATE_FN}()")
        op.execute(f"DROP FUNCTION IF EXISTS {IMMUTABLE_DELETE_FN}()")

    op.drop_index("ix_admin_audit_logs_resource_type", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_action_type", table_name="admin_audit_logs")

    op.drop_column("admin_audit_logs", "context")
    op.drop_column("admin_audit_logs", "auth_method")
    op.drop_column("admin_audit_logs", "sensitivity_level")
    op.drop_column("admin_audit_logs", "action_type")
    op.drop_column("admin_audit_logs", "admin_id")
