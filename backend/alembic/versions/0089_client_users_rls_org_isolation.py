"""add RLS org isolation for client_users

Revision ID: 0089_client_users_rls_org_isolation
Revises: f2c3d4e5f6a7
Create Date: 2026-03-05 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0089_client_users_rls_org_isolation"
down_revision = "0086_merge_0085_heads", "f2c3d4e5f6a7"
branch_labels = None
depends_on = None

SCHEMA = "public"
TABLE = "client_users"


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _policy_sql() -> str:
    qualified_table = f"{SCHEMA}.{TABLE}"
    return f"""
ALTER TABLE {qualified_table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {qualified_table} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS {TABLE}_org_isolation ON {qualified_table};
CREATE POLICY {TABLE}_org_isolation ON {qualified_table}
    USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
"""


def _downgrade_sql() -> str:
    qualified_table = f"{SCHEMA}.{TABLE}"
    return f"""
DROP POLICY IF EXISTS {TABLE}_org_isolation ON {qualified_table};
ALTER TABLE {qualified_table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {qualified_table} DISABLE ROW LEVEL SECURITY;
"""


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(sa.text(_policy_sql()))


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(sa.text(_downgrade_sql()))
