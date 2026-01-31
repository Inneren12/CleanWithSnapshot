"""add RLS policies for finance + marketing tables

Revision ID: c3e9a1b2d4f5
Revises: 0088_enable_pg_stat_statements
Create Date: 2026-04-20 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3e9a1b2d4f5"
down_revision = "0088_enable_pg_stat_statements"
branch_labels = None
depends_on = None

SCHEMA = "public"
TABLES = (
    "finance_expense_categories",
    "finance_expenses",
    "finance_budgets",
    "promo_codes",
    "promo_code_redemptions",
    "marketing_spend",
)
TENANT_EXPR = "org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid"


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _policy_sql(table: str) -> str:
    qualified_table = f"{SCHEMA}.{table}"
    policy_name = f"{table}_org_isolation"
    return f"""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = '{SCHEMA}'
          AND c.relname = '{table}'
          AND c.relrowsecurity
    ) THEN
        EXECUTE 'ALTER TABLE {qualified_table} ENABLE ROW LEVEL SECURITY';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = '{SCHEMA}'
          AND c.relname = '{table}'
          AND c.relforcerowsecurity
    ) THEN
        EXECUTE 'ALTER TABLE {qualified_table} FORCE ROW LEVEL SECURITY';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = '{SCHEMA}'
          AND tablename = '{table}'
          AND policyname = '{policy_name}'
    ) THEN
        EXECUTE $sql$
            CREATE POLICY {policy_name} ON {qualified_table}
            USING ({TENANT_EXPR})
            WITH CHECK ({TENANT_EXPR})
        $sql$;
    END IF;
END
$$;
"""


def _downgrade_sql(table: str) -> str:
    qualified_table = f"{SCHEMA}.{table}"
    policy_name = f"{table}_org_isolation"
    return f"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = '{SCHEMA}'
          AND tablename = '{table}'
          AND policyname = '{policy_name}'
    ) THEN
        EXECUTE 'DROP POLICY {policy_name} ON {qualified_table}';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = '{SCHEMA}'
          AND c.relname = '{table}'
          AND (c.relforcerowsecurity OR c.relrowsecurity)
    ) THEN
        EXECUTE 'ALTER TABLE {qualified_table} NO FORCE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE {qualified_table} DISABLE ROW LEVEL SECURITY';
    END IF;
END
$$;
"""


def upgrade() -> None:
    if not _is_postgres():
        return

    for table in TABLES:
        op.execute(sa.text(_policy_sql(table)))


def downgrade() -> None:
    if not _is_postgres():
        return

    for table in TABLES:
        op.execute(sa.text(_downgrade_sql(table)))
