"""add RLS policies for training tables

Revision ID: 2f3a4b5c6d7e
Revises: 1b9c3d4e5f6a
Create Date: 2026-04-15 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "2f3a4b5c6d7e"
down_revision = "1b9c3d4e5f6a"
branch_labels = None
depends_on = None

SCHEMA = "public"
TABLES = (
    "training_requirements",
    "worker_training_records",
    "training_courses",
    "training_assignments",
    "training_sessions",
)


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _org_id_expr() -> str:
    return "NULLIF(current_setting('app.current_org_id', true), '')::uuid"


def _policy_sql(table: str) -> str:
    qualified_table = f"{SCHEMA}.{table}"
    policy_name = f"{table}_org_isolation"
    org_expr = _org_id_expr()
    return f"""
ALTER TABLE {qualified_table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {qualified_table} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS {policy_name} ON {qualified_table};
CREATE POLICY {policy_name} ON {qualified_table}
    USING (org_id = {org_expr})
    WITH CHECK (org_id = {org_expr});
"""


def _downgrade_sql(table: str) -> str:
    qualified_table = f"{SCHEMA}.{table}"
    policy_name = f"{table}_org_isolation"
    return f"""
DROP POLICY IF EXISTS {policy_name} ON {qualified_table};
ALTER TABLE {qualified_table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {qualified_table} DISABLE ROW LEVEL SECURITY;
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
