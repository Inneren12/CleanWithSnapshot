"""add integration audit logs

Revision ID: fe12a3b4c5d6
Revises: fc2d3e4f5a6b
Create Date: 2026-03-07 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "fe12a3b4c5d6"
down_revision = "fc2d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_audit_logs",
        sa.Column("audit_id", sa.String(length=36), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("actor_role", sa.String(length=64), nullable=True),
        sa.Column("auth_method", sa.String(length=64), nullable=True),
        sa.Column("actor_source", sa.String(length=255), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("integration_type", sa.String(length=64), nullable=False),
        sa.Column("integration_scope", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("redaction_map", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index("ix_integration_audit_logs_org_id", "integration_audit_logs", ["org_id"])
    op.create_index(
        "ix_integration_audit_logs_type",
        "integration_audit_logs",
        ["integration_type"],
    )
    op.create_index(
        "ix_integration_audit_logs_occurred_at",
        "integration_audit_logs",
        ["occurred_at"],
    )
    op.create_index(
        "ix_integration_audit_logs_org_type_time",
        "integration_audit_logs",
        ["org_id", "integration_type", "occurred_at"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_integration_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Integration audit records are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER integration_audit_no_update
        BEFORE UPDATE ON integration_audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_integration_audit_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER integration_audit_no_delete
        BEFORE DELETE ON integration_audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_integration_audit_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS integration_audit_no_delete ON integration_audit_logs")
    op.execute("DROP TRIGGER IF EXISTS integration_audit_no_update ON integration_audit_logs")
    op.execute("DROP FUNCTION IF EXISTS prevent_integration_audit_mutation")
    op.drop_index("ix_integration_audit_logs_org_type_time", table_name="integration_audit_logs")
    op.drop_index("ix_integration_audit_logs_occurred_at", table_name="integration_audit_logs")
    op.drop_index("ix_integration_audit_logs_type", table_name="integration_audit_logs")
    op.drop_index("ix_integration_audit_logs_org_id", table_name="integration_audit_logs")
    op.drop_table("integration_audit_logs")
