"""add feature flag audit logs

Revision ID: fc2d3e4f5a6b
Revises: fb1c2d3e4f5c
Create Date: 2026-03-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "fc2d3e4f5a6b"
down_revision = "fb1c2d3e4f5c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feature_flag_audit_logs",
        sa.Column("audit_id", sa.String(length=36), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("actor_role", sa.String(length=64), nullable=True),
        sa.Column("auth_method", sa.String(length=64), nullable=True),
        sa.Column("actor_source", sa.String(length=255), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("flag_key", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rollout_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index(
        "ix_feature_flag_audit_logs_flag_key",
        "feature_flag_audit_logs",
        ["flag_key"],
    )
    op.create_index(
        "ix_feature_flag_audit_logs_org_id",
        "feature_flag_audit_logs",
        ["org_id"],
    )
    op.create_index(
        "ix_feature_flag_audit_logs_occurred_at",
        "feature_flag_audit_logs",
        ["occurred_at"],
    )
    op.create_index(
        "ix_feature_flag_audit_logs_org_flag_time",
        "feature_flag_audit_logs",
        ["org_id", "flag_key", "occurred_at"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_feature_flag_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Feature flag audit records are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER feature_flag_audit_no_update
        BEFORE UPDATE ON feature_flag_audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_feature_flag_audit_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER feature_flag_audit_no_delete
        BEFORE DELETE ON feature_flag_audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_feature_flag_audit_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS feature_flag_audit_no_delete ON feature_flag_audit_logs")
    op.execute("DROP TRIGGER IF EXISTS feature_flag_audit_no_update ON feature_flag_audit_logs")
    op.execute("DROP FUNCTION IF EXISTS prevent_feature_flag_audit_mutation")
    op.drop_index("ix_feature_flag_audit_logs_org_flag_time", table_name="feature_flag_audit_logs")
    op.drop_index("ix_feature_flag_audit_logs_occurred_at", table_name="feature_flag_audit_logs")
    op.drop_index("ix_feature_flag_audit_logs_org_id", table_name="feature_flag_audit_logs")
    op.drop_index("ix_feature_flag_audit_logs_flag_key", table_name="feature_flag_audit_logs")
    op.drop_table("feature_flag_audit_logs")
