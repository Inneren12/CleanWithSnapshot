"""harden work_time_entries constraints and index

Revision ID: d9e8f7a6b5c4
Revises: 6e1f9a2b3c4d
Create Date: 2026-02-23 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d9e8f7a6b5c4"
down_revision = "6e1f9a2b3c4d"
branch_labels = None
depends_on = None

FK_NAME = "fk_work_time_entries_booking_id_bookings"
UNIQUE_NAME = "uq_work_time_booking"
INDEX_NAME = "ix_work_time_entries_booking_id"
TABLE_NAME = "work_time_entries"


def _has_booking_fk(inspector: sa.Inspector) -> bool:
    for fk in inspector.get_foreign_keys(TABLE_NAME):
        if (
            set(fk.get("constrained_columns") or ()) == {"booking_id"}
            and fk.get("referred_table") == "bookings"
            and set(fk.get("referred_columns") or ()) == {"booking_id"}
        ):
            return True
    return False


def _has_booking_unique(inspector: sa.Inspector) -> bool:
    for constraint in inspector.get_unique_constraints(TABLE_NAME):
        if set(constraint.get("column_names") or ()) == {"booking_id"}:
            return True
    return False


def _has_booking_index(inspector: sa.Inspector) -> bool:
    for index in inspector.get_indexes(TABLE_NAME):
        if set(index.get("column_names") or ()) == {"booking_id"}:
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_booking_fk(inspector):
        op.create_foreign_key(
            FK_NAME,
            TABLE_NAME,
            "bookings",
            ["booking_id"],
            ["booking_id"],
            ondelete="CASCADE",
        )

    if not _has_booking_unique(inspector):
        op.create_unique_constraint(UNIQUE_NAME, TABLE_NAME, ["booking_id"])

    if not _has_booking_index(inspector):
        op.create_index(INDEX_NAME, TABLE_NAME, ["booking_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if any(index.get("name") == INDEX_NAME for index in inspector.get_indexes(TABLE_NAME)):
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)

    if any(
        constraint.get("name") == UNIQUE_NAME
        for constraint in inspector.get_unique_constraints(TABLE_NAME)
    ):
        op.drop_constraint(UNIQUE_NAME, TABLE_NAME, type_="unique")

    if any(fk.get("name") == FK_NAME for fk in inspector.get_foreign_keys(TABLE_NAME)):
        op.drop_constraint(FK_NAME, TABLE_NAME, type_="foreignkey")
