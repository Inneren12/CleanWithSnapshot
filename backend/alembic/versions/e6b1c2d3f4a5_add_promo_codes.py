"""add promo codes and redemptions

Revision ID: e6b1c2d3f4a5
Revises: d3b7c1a4f8e2
Create Date: 2026-02-20 09:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "e6b1c2d3f4a5"
down_revision = "d3b7c1a4f8e2"
branch_labels = None
depends_on = None

UUID_TYPE = sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("promo_code_id", UUID_TYPE, primary_key=True, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("discount_type", sa.String(length=24), nullable=False),
        sa.Column("percent_off", sa.Integer(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("free_addon_id", sa.Integer(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_time_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("min_order_cents", sa.Integer(), nullable=True),
        sa.Column("one_per_customer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("usage_limit", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["free_addon_id"], ["service_addons.addon_id"]),
        sa.UniqueConstraint("org_id", "code", name="uq_promo_codes_org_code"),
    )
    op.create_index("ix_promo_codes_org_active", "promo_codes", ["org_id", "active"])

    op.create_table(
        "promo_code_redemptions",
        sa.Column("redemption_id", UUID_TYPE, primary_key=True, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("promo_code_id", UUID_TYPE, nullable=False),
        sa.Column("booking_id", sa.String(length=36), nullable=True),
        sa.Column("client_id", sa.String(length=36), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["promo_code_id"], ["promo_codes.promo_code_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.booking_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_id"], ["client_users.client_id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_promo_code_redemptions_org_code",
        "promo_code_redemptions",
        ["org_id", "promo_code_id"],
    )
    op.create_index(
        "ix_promo_code_redemptions_org_client",
        "promo_code_redemptions",
        ["org_id", "client_id"],
    )
    op.create_index(
        "ix_promo_code_redemptions_org_booking",
        "promo_code_redemptions",
        ["org_id", "booking_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_promo_code_redemptions_org_booking", table_name="promo_code_redemptions")
    op.drop_index("ix_promo_code_redemptions_org_client", table_name="promo_code_redemptions")
    op.drop_index("ix_promo_code_redemptions_org_code", table_name="promo_code_redemptions")
    op.drop_table("promo_code_redemptions")
    op.drop_index("ix_promo_codes_org_active", table_name="promo_codes")
    op.drop_table("promo_codes")
