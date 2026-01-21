"""enforce RLS org isolation for client_users

Revision ID: 0087_client_users_rls_enforce
Revises: 0086_client_users_rls_org_isolation
Create Date: 2026-03-05 00:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0087_client_users_rls_enforce"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None

SCHEMA = "public"
TABLE = "client_users"
POLICY_NAME = f"{TABLE}_org_isolation"
TENANT_EXPR = "org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid"


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    qualified_table = f"{SCHEMA}.{TABLE}"
    op.execute(
        sa.text(
            f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = '{SCHEMA}'
          AND c.relname = '{TABLE}'
          AND c.relrowsecurity
    ) THEN
        EXECUTE 'ALTER TABLE {qualified_table} ENABLE ROW LEVEL SECURITY';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = '{SCHEMA}'
          AND c.relname = '{TABLE}'
          AND c.relforcerowsecurity
    ) THEN
        EXECUTE 'ALTER TABLE {qualified_table} FORCE ROW LEVEL SECURITY';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = '{SCHEMA}'
          AND tablename = '{TABLE}'
          AND policyname = '{POLICY_NAME}'
    ) THEN
        EXECUTE $sql$
            CREATE POLICY {POLICY_NAME} ON {qualified_table}
            USING ({TENANT_EXPR})
            WITH CHECK ({TENANT_EXPR})
        $sql$;
    END IF;
END
$$;
"""
        )
    )


def downgrade() -> None:
    if not _is_postgres():
        return

    qualified_table = f"{SCHEMA}.{TABLE}"
    op.execute(
        sa.text(
            f"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = '{SCHEMA}'
          AND tablename = '{TABLE}'
          AND policyname = '{POLICY_NAME}'
    ) THEN
        EXECUTE 'DROP POLICY {POLICY_NAME} ON {qualified_table}';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = '{SCHEMA}'
          AND c.relname = '{TABLE}'
          AND (c.relforcerowsecurity OR c.relrowsecurity)
    ) THEN
        EXECUTE 'ALTER TABLE {qualified_table} NO FORCE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE {qualified_table} DISABLE ROW LEVEL SECURITY';
    END IF;
END
$$;
"""
        )
    )
