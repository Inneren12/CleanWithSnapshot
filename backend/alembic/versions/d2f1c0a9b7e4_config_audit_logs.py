"""config audit logs

Revision ID: d2f1c0a9b7e4
Revises: 71ae992e9c57
Create Date: 2025-09-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d2f1c0a9b7e4"
down_revision = "71ae992e9c57"
branch_labels = None
depends_on = None


IMMUTABLE_UPDATE_FN = "prevent_config_audit_updates"
IMMUTABLE_DELETE_FN = "prevent_config_audit_deletes"


def upgrade() -> None:
    """Create immutable config audit log table for governance and compliance."""
    op.create_table(
        "config_audit_logs",
        sa.Column("audit_id", sa.String(length=36), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("actor_role", sa.String(length=64), nullable=True),
        sa.Column("auth_method", sa.String(length=64), nullable=True),
        sa.Column("actor_source", sa.String(length=255), nullable=True),
        sa.Column("org_id", sa.Uuid(), sa.ForeignKey("organizations.org_id", ondelete="SET NULL"), nullable=True),
        sa.Column("config_scope", sa.String(length=64), nullable=False),
        sa.Column("config_key", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before_value", sa.JSON(), nullable=True),
        sa.Column("after_value", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        comment="Immutable audit trail for configuration mutations.",
    )
    op.create_index("ix_config_audit_logs_org_id", "config_audit_logs", ["org_id"])
    op.create_index("ix_config_audit_logs_scope", "config_audit_logs", ["config_scope"])
    op.create_index("ix_config_audit_logs_occurred_at", "config_audit_logs", ["occurred_at"])
    op.create_index(
        "ix_config_audit_logs_org_scope_time",
        "config_audit_logs",
        ["org_id", "config_scope", "occurred_at"],
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {IMMUTABLE_UPDATE_FN}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'config audit logs are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {IMMUTABLE_DELETE_FN}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'config audit logs are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER config_audit_logs_no_update
        BEFORE UPDATE ON config_audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_config_audit_updates();
        """
    )
    op.execute(
        """
        CREATE TRIGGER config_audit_logs_no_delete
        BEFORE DELETE ON config_audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_config_audit_deletes();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS config_audit_logs_no_update ON config_audit_logs")
        op.execute("DROP TRIGGER IF EXISTS config_audit_logs_no_delete ON config_audit_logs")
        op.execute(f"DROP FUNCTION IF EXISTS {IMMUTABLE_UPDATE_FN}()")
        op.execute(f"DROP FUNCTION IF EXISTS {IMMUTABLE_DELETE_FN}()")

    op.drop_index("ix_config_audit_logs_org_scope_time", table_name="config_audit_logs")
    op.drop_index("ix_config_audit_logs_occurred_at", table_name="config_audit_logs")
    op.drop_index("ix_config_audit_logs_scope", table_name="config_audit_logs")
    op.drop_index("ix_config_audit_logs_org_id", table_name="config_audit_logs")
    op.drop_table("config_audit_logs")
