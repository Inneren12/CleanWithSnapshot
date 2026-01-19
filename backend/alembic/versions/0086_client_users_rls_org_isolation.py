"""add RLS org isolation for client_users

Revision ID: 0086_client_users_rls_org_isolation
Revises: 0044_postgres_rls_org_isolation
Create Date: 2026-03-05 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0086_client_users_rls_org_isolation"
down_revision = "0044_postgres_rls_org_isolation"
branch_labels = None
depends_on = None

TABLE = "client_users"


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _policy_sql() -> str:
    return f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS {TABLE}_org_isolation ON {TABLE};
CREATE POLICY {TABLE}_org_isolation ON {TABLE}
    USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
"""


def _downgrade_sql() -> str:
    return f"""
DROP POLICY IF EXISTS {TABLE}_org_isolation ON {TABLE};
ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(sa.text(_policy_sql()))


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(sa.text(_downgrade_sql()))
