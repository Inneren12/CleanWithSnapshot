"""fix org_id uuid mismatches for leads/outbox

Revision ID: e1b2c3d4e5f7
Revises: d7e4b1c2a3f4
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

revision = "e1b2c3d4e5f7"
down_revision = "d7e4b1c2a3f4"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)
DEFAULT_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _table_exists(conn: sa.engine.Connection, table: str) -> bool:
    inspector = sa.inspect(conn)
    return table in inspector.get_table_names()


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    inspector = sa.inspect(conn)
    return any(col["name"] == column for col in inspector.get_columns(table))


def _is_uuid_column(conn: sa.engine.Connection, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = :table
              AND column_name = :column
            """
        ),
        {"table": table, "column": column},
    )
    return (result.scalar() or "").lower() == "uuid"


def _org_fk_names(inspector: sa.inspect, table: str) -> list[str]:
    fks = []
    for fk in inspector.get_foreign_keys(table):
        if fk.get("referred_table") == "organizations" and fk.get("constrained_columns") == ["org_id"]:
            if fk.get("name"):
                fks.append(fk["name"])
    return fks


def _convert_org_id(conn: sa.engine.Connection, table: str) -> None:
    if not _table_exists(conn, table) or not _column_exists(conn, table, "org_id"):
        return
    if _is_uuid_column(conn, table, "org_id"):
        return

    inspector = sa.inspect(conn)
    fk_names = _org_fk_names(inspector, table)
    for fk in fk_names:
        op.drop_constraint(fk, table_name=table, type_="foreignkey")

    conn.execute(sa.text(f"UPDATE {table} SET org_id = NULL WHERE org_id = ''"))

    op.alter_column(
        table,
        "org_id",
        type_=UUID_TYPE,
        existing_type=sa.String(length=36),
        postgresql_using="NULLIF(org_id, '')::uuid",
    )

    conn.execute(
        sa.text(f"UPDATE {table} SET org_id = :default_org_id WHERE org_id IS NULL"),
        {"default_org_id": str(DEFAULT_ORG_ID)},
    )

    for fk in fk_names:
        op.create_foreign_key(
            fk,
            table,
            "organizations",
            ["org_id"],
            ["org_id"],
            ondelete="CASCADE",
        )


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    _convert_org_id(conn, "leads")
    _convert_org_id(conn, "outbox_events")


def downgrade() -> None:
    # Avoid type downgrade (unsafe). Leave org_id as UUID.
    pass
