"""Add cascade delete for event_logs booking FK.

Revision ID: 0067
Revises: 0066
Create Date: 2026-01-13 12:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind else ""

    if dialect == "sqlite":
        inspector = sa.inspect(bind)
        has_named_fk = any(
            fk.get("name") == "event_logs_booking_id_fkey"
            for fk in inspector.get_foreign_keys("event_logs")
        )
        if not has_named_fk:
            # SQLite often omits FK names; skip to keep migrations runnable in tests.
            return
        with op.batch_alter_table("event_logs", recreate="always") as batch_op:
            batch_op.drop_constraint("event_logs_booking_id_fkey", type_="foreignkey")
            batch_op.create_foreign_key(
                "event_logs_booking_id_fkey",
                "bookings",
                ["booking_id"],
                ["booking_id"],
                ondelete="CASCADE",
            )
        return

    op.drop_constraint("event_logs_booking_id_fkey", "event_logs", type_="foreignkey")
    op.create_foreign_key(
        "event_logs_booking_id_fkey",
        "event_logs",
        "bookings",
        ["booking_id"],
        ["booking_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind else ""

    if dialect == "sqlite":
        inspector = sa.inspect(bind)
        has_named_fk = any(
            fk.get("name") == "event_logs_booking_id_fkey"
            for fk in inspector.get_foreign_keys("event_logs")
        )
        if not has_named_fk:
            # SQLite often omits FK names; skip to keep migrations runnable in tests.
            return
        with op.batch_alter_table("event_logs", recreate="always") as batch_op:
            batch_op.drop_constraint("event_logs_booking_id_fkey", type_="foreignkey")
            batch_op.create_foreign_key(
                "event_logs_booking_id_fkey",
                "bookings",
                ["booking_id"],
                ["booking_id"],
            )
        return

    op.drop_constraint("event_logs_booking_id_fkey", "event_logs", type_="foreignkey")
    op.create_foreign_key(
        "event_logs_booking_id_fkey",
        "event_logs",
        "bookings",
        ["booking_id"],
        ["booking_id"],
    )
