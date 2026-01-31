"""add RLS policies for checklists

Revision ID: 1b9c3d4e5f6a
Revises: ff1a2b3c4d5e
Create Date: 2026-04-10 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "1b9c3d4e5f6a"
down_revision = "ff1a2b3c4d5e"
branch_labels = None
depends_on = None

SCHEMA = "public"
TABLES = ("checklist_runs", "checklist_run_items")


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _org_id_expr() -> str:
    return "NULLIF(current_setting('app.current_org_id', true), '')::uuid"


def _policy_sql(table: str) -> str:
    if table == "checklist_runs":
        predicate = (
            "EXISTS ("
            "SELECT 1 FROM bookings "
            "WHERE bookings.booking_id = checklist_runs.order_id "
            f"AND bookings.org_id = {_org_id_expr()}"
            ")"
        )
    elif table == "checklist_run_items":
        predicate = (
            "EXISTS ("
            "SELECT 1 FROM checklist_runs "
            "JOIN bookings ON bookings.booking_id = checklist_runs.order_id "
            "WHERE checklist_runs.run_id = checklist_run_items.run_id "
            f"AND bookings.org_id = {_org_id_expr()}"
            ")"
        )
    else:
        raise ValueError(f"Unhandled checklist table: {table}")

    qualified_table = f"{SCHEMA}.{table}"
    policy_name = f"{table}_org_isolation"
    return f"""
ALTER TABLE {qualified_table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {qualified_table} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS {policy_name} ON {qualified_table};
CREATE POLICY {policy_name} ON {qualified_table}
    FOR ALL
    USING ({predicate})
    WITH CHECK ({predicate});
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
