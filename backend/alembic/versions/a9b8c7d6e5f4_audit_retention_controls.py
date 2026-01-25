"""audit retention controls and legal holds

Revision ID: a9b8c7d6e5f4
Revises: c0e1f2a3b4c5, d2f1c0a9b7e4, fe12a3b4c5d6
Create Date: 2026-03-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a9b8c7d6e5f4"
down_revision = ("c0e1f2a3b4c5", "d2f1c0a9b7e4", "fe12a3b4c5d6")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_legal_holds",
        sa.Column("hold_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("audit_scope", sa.String(length=32), nullable=False),
        sa.Column("applies_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applies_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("investigation_id", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.String(length=128), nullable=True),
        sa.Column("release_reason", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("hold_id"),
    )
    op.create_index("ix_audit_legal_holds_org_id", "audit_legal_holds", ["org_id"])
    op.create_index("ix_audit_legal_holds_scope", "audit_legal_holds", ["audit_scope"])
    op.create_index("ix_audit_legal_holds_investigation", "audit_legal_holds", ["investigation_id"])
    op.create_index("ix_audit_legal_holds_active", "audit_legal_holds", ["released_at"])

    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.create_table(
        "audit_purge_events",
        sa.Column("purge_id", sa.String(length=36), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("policy_snapshot", json_type, nullable=True),
        sa.Column("purge_summary", json_type, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("purge_id"),
    )
    op.create_index("ix_audit_purge_events_started_at", "audit_purge_events", ["started_at"])
    op.create_index("ix_audit_purge_events_actor_type", "audit_purge_events", ["actor_type"])

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_admin_audit_deletes()
        RETURNS trigger AS $$
        BEGIN
            IF current_setting('app.audit_purge', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'admin audit logs are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_config_audit_deletes()
        RETURNS trigger AS $$
        BEGIN
            IF current_setting('app.audit_purge', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'config audit logs are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_feature_flag_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('app.audit_purge', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Feature flag audit records are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_integration_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND current_setting('app.audit_purge', true) = 'on' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Integration audit records are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION prevent_admin_audit_deletes()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'admin audit logs are immutable';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE OR REPLACE FUNCTION prevent_config_audit_deletes()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'config audit logs are immutable';
            END;
            $$ LANGUAGE plpgsql;
            """
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
            CREATE OR REPLACE FUNCTION prevent_integration_audit_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Integration audit records are immutable';
            END;
            $$ LANGUAGE plpgsql;
            """
        )

    op.drop_index("ix_audit_purge_events_actor_type", table_name="audit_purge_events")
    op.drop_index("ix_audit_purge_events_started_at", table_name="audit_purge_events")
    op.drop_table("audit_purge_events")

    op.drop_index("ix_audit_legal_holds_active", table_name="audit_legal_holds")
    op.drop_index("ix_audit_legal_holds_investigation", table_name="audit_legal_holds")
    op.drop_index("ix_audit_legal_holds_scope", table_name="audit_legal_holds")
    op.drop_index("ix_audit_legal_holds_org_id", table_name="audit_legal_holds")
    op.drop_table("audit_legal_holds")
