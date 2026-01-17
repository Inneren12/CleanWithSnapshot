"""add referrals tracking tables

Revision ID: f1a2b3c4d5e6
Revises: e6b1c2d3f4a5
Create Date: 2026-02-28 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e6b1c2d3f4a5"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "organization_settings",
        sa.Column(
            "referral_settings",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )

    op.create_table(
        "referrals",
        sa.Column("referral_id", UUID_TYPE, primary_key=True, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("referrer_lead_id", sa.String(length=36), nullable=False),
        sa.Column("referred_lead_id", sa.String(length=36), nullable=False),
        sa.Column("referral_code", sa.String(length=16), nullable=False),
        sa.Column("booking_id", sa.String(length=36), nullable=True),
        sa.Column("payment_id", sa.String(length=36), nullable=True),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["referrer_lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["referred_lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.booking_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_id"], ["invoice_payments.payment_id"], ondelete="SET NULL"),
        sa.UniqueConstraint("referred_lead_id", name="uq_referrals_referred_lead"),
    )
    op.create_index("ix_referrals_org_id", "referrals", ["org_id"])
    op.create_index("ix_referrals_referrer_lead_id", "referrals", ["referrer_lead_id"])
    op.create_index("ix_referrals_referred_lead_id", "referrals", ["referred_lead_id"])

    with op.batch_alter_table("referral_credits") as batch:
        batch.drop_constraint("uq_referral_credits_referred_lead", type_="unique")
        batch.add_column(sa.Column("referral_id", UUID_TYPE, nullable=True))
        batch.add_column(
            sa.Column(
                "recipient_role",
                sa.String(length=16),
                nullable=False,
                server_default="referrer",
            )
        )
        batch.add_column(sa.Column("credit_cents", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("trigger_event", sa.String(length=32), nullable=True))
        batch.create_foreign_key(
            "fk_referral_credits_referral",
            "referrals",
            ["referral_id"],
            ["referral_id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint(
            "uq_referral_credits_referred_role",
            ["referred_lead_id", "recipient_role"],
        )

    op.create_index(
        "ix_referral_credits_referrer_lead_id",
        "referral_credits",
        ["referrer_lead_id"],
    )
    op.create_index(
        "ix_referral_credits_referred_lead_id",
        "referral_credits",
        ["referred_lead_id"],
    )
    op.create_index(
        "ix_referral_credits_referral_id",
        "referral_credits",
        ["referral_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_referral_credits_referral_id", table_name="referral_credits")
    op.drop_index("ix_referral_credits_referred_lead_id", table_name="referral_credits")
    op.drop_index("ix_referral_credits_referrer_lead_id", table_name="referral_credits")

    with op.batch_alter_table("referral_credits") as batch:
        batch.drop_constraint("uq_referral_credits_referred_role", type_="unique")
        batch.drop_constraint("fk_referral_credits_referral", type_="foreignkey")
        batch.drop_column("trigger_event")
        batch.drop_column("credit_cents")
        batch.drop_column("recipient_role")
        batch.drop_column("referral_id")
        batch.create_unique_constraint(
            "uq_referral_credits_referred_lead",
            ["referred_lead_id"],
        )

    op.drop_index("ix_referrals_referred_lead_id", table_name="referrals")
    op.drop_index("ix_referrals_referrer_lead_id", table_name="referrals")
    op.drop_index("ix_referrals_org_id", table_name="referrals")
    op.drop_table("referrals")

    op.drop_column("organization_settings", "referral_settings")
