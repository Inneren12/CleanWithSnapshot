"""add nps tokens and tokenized responses

Revision ID: f2c3d4e5f6a7
Revises: f9c1d2e3a4b5
Create Date: 2026-03-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f2c3d4e5f6a7"
down_revision = "f9c1d2e3a4b5"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "nps_tokens",
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=True),
        sa.Column("booking_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["bookings.booking_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["client_users.client_id"],
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.org_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index("ix_nps_tokens_booking_id", "nps_tokens", ["booking_id"])
    op.create_index("ix_nps_tokens_expires_at", "nps_tokens", ["expires_at"])
    op.create_index("ix_nps_tokens_org_id", "nps_tokens", ["org_id"])

    with op.batch_alter_table("nps_responses") as batch:
        batch.add_column(sa.Column("org_id", UUID_TYPE, nullable=True))
        batch.add_column(sa.Column("token", sa.String(length=255), nullable=True))

    op.execute(
        """
        UPDATE nps_responses
        SET org_id = (
            SELECT org_id FROM bookings WHERE bookings.booking_id = nps_responses.order_id
        )
        """
    )
    op.execute("UPDATE nps_responses SET token = order_id WHERE token IS NULL")

    op.execute(
        """
        INSERT INTO nps_tokens (token, org_id, client_id, booking_id, created_at, expires_at, used_at)
        SELECT order_id, org_id, client_id, order_id, created_at, created_at, created_at
        FROM nps_responses
        WHERE order_id IS NOT NULL
        """
    )

    with op.batch_alter_table("nps_responses") as batch:
        batch.drop_constraint("uq_nps_responses_order", type_="unique")
        batch.create_foreign_key(
            "fk_nps_responses_token",
            "nps_tokens",
            ["token"],
            ["token"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_nps_responses_org",
            "organizations",
            ["org_id"],
            ["org_id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint("uq_nps_responses_token", ["token"])
        batch.alter_column("org_id", nullable=False)
        batch.alter_column("token", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("nps_responses") as batch:
        batch.drop_constraint("fk_nps_responses_token", type_="foreignkey")
        batch.drop_constraint("fk_nps_responses_org", type_="foreignkey")
        batch.drop_constraint("uq_nps_responses_token", type_="unique")
        batch.alter_column("token", nullable=True)
        batch.alter_column("org_id", nullable=True)
        batch.drop_column("token")
        batch.drop_column("org_id")
        batch.create_unique_constraint("uq_nps_responses_order", ["order_id"])

    op.drop_index("ix_nps_tokens_org_id", table_name="nps_tokens")
    op.drop_index("ix_nps_tokens_expires_at", table_name="nps_tokens")
    op.drop_index("ix_nps_tokens_booking_id", table_name="nps_tokens")
    op.drop_table("nps_tokens")
