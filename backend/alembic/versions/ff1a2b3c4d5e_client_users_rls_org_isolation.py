"""add RLS org isolation for client_users

Revision ID: ff1a2b3c4d5e
Revises: fedcba987654
Create Date: 2026-03-20 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ff1a2b3c4d5e"
down_revision = "fedcba987654"
branch_labels = None
depends_on = None

SCHEMA = "public"
TABLE = "client_users"
TABLES = (TABLE,)
POLICY_NAMES = ("client_users_org_isolation", "client_users_org_rls")


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _policy_sql() -> str:
    qualified_table = f"{SCHEMA}.{TABLE}"
    return f"""
ALTER TABLE {qualified_table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {qualified_table} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS {POLICY_NAMES[0]} ON {qualified_table};
DROP POLICY IF EXISTS {POLICY_NAMES[1]} ON {qualified_table};
CREATE POLICY {POLICY_NAMES[0]} ON {qualified_table}
    FOR ALL
    USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
"""


def _downgrade_sql() -> str:
    qualified_table = f"{SCHEMA}.{TABLE}"
    return f"""
DROP POLICY IF EXISTS {POLICY_NAMES[0]} ON {qualified_table};
DROP POLICY IF EXISTS {POLICY_NAMES[1]} ON {qualified_table};
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
