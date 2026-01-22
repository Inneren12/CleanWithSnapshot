"""add client_users RLS policy from bookings

Revision ID: 0088_client_users_rls_from_bookings
Revises: 0086_client_users_rls_org_isolation
Create Date: 2026-03-05 00:25:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0088_client_users_rls_from_bookings"
down_revision = "0086_client_users_rls_org_isolation"
branch_labels = None
depends_on = None

SCHEMA = "public"
TABLE = "client_users"
POLICY_NAME = "client_users_org_rls"


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _load_booking_policy(conn) -> tuple[str, str]:
    result = conn.execute(
        sa.text(
            """
            SELECT qual, with_check
            FROM pg_policies
            WHERE schemaname = :schema
              AND tablename = :table
            ORDER BY policyname
            LIMIT 1
            """
        ),
        {"schema": SCHEMA, "table": "bookings"},
    ).mappings().first()
    if result is None or not result.get("qual"):
        raise RuntimeError("No bookings RLS policy found to copy tenant expression.")
    qual = result["qual"]
    with_check = result.get("with_check") or qual
    return qual, with_check


def upgrade() -> None:
    if not _is_postgres():
        return

    conn = op.get_bind()
    qual, with_check = _load_booking_policy(conn)
    qualified_table = f"{SCHEMA}.{TABLE}"

    rel_security = conn.execute(
        sa.text(
            """
            SELECT c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema
              AND c.relname = :table
            """
        ),
        {"schema": SCHEMA, "table": TABLE},
    ).first()
    if rel_security:
        relrowsecurity, relforcerowsecurity = rel_security
        if not relrowsecurity:
            op.execute(sa.text(f"ALTER TABLE {qualified_table} ENABLE ROW LEVEL SECURITY"))
        if not relforcerowsecurity:
            op.execute(sa.text(f"ALTER TABLE {qualified_table} FORCE ROW LEVEL SECURITY"))

    policy_exists = conn.execute(
        sa.text(
            """
            SELECT 1
            FROM pg_policies
            WHERE schemaname = :schema
              AND tablename = :table
              AND policyname = :policy
            """
        ),
        {"schema": SCHEMA, "table": TABLE, "policy": POLICY_NAME},
    ).first()
    if policy_exists is None:
        op.execute(
            sa.text(
                f"""
                CREATE POLICY {POLICY_NAME} ON {qualified_table}
                FOR ALL
                USING ({qual})
                WITH CHECK ({with_check});
                """
            )
        )


def downgrade() -> None:
    if not _is_postgres():
        return

    qualified_table = f"{SCHEMA}.{TABLE}"
    op.execute(sa.text(f"DROP POLICY IF EXISTS {POLICY_NAME} ON {qualified_table}"))
    op.execute(sa.text(f"ALTER TABLE {qualified_table} NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {qualified_table} DISABLE ROW LEVEL SECURITY"))
