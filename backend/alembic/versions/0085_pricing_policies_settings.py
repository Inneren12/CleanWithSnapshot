"""Add service catalog and booking policy settings.

Revision ID: 0085_pricing_policies_settings
Revises: 0084_feature_modules_visibility
Create Date: 2026-01-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0085_pricing_policies_settings"
down_revision = "0084_feature_modules_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_types",
        sa.Column("service_type_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("default_duration_minutes", sa.Integer(), server_default=sa.text("180"), nullable=False),
        sa.Column("pricing_model", sa.String(length=32), server_default=sa.text("'flat'"), nullable=False),
        sa.Column("base_price_cents", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("hourly_rate_cents", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'CAD'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("service_type_id"),
        sa.UniqueConstraint("org_id", "name", name="uq_service_types_org_name"),
    )
    op.create_index("ix_service_types_org_id", "service_types", ["org_id"], unique=False)

    op.create_table(
        "service_addons",
        sa.Column("addon_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("service_type_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("price_cents", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["service_type_id"],
            ["service_types.service_type_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("addon_id"),
        sa.UniqueConstraint("service_type_id", "name", name="uq_service_addons_service_name"),
    )
    op.create_index(
        "ix_service_addons_service_type",
        "service_addons",
        ["service_type_id"],
        unique=False,
    )

    op.create_table(
        "pricing_settings",
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("gst_rate", sa.Numeric(6, 4), server_default=sa.text("0"), nullable=False),
        sa.Column("discounts", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("surcharges", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("promo_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id"),
    )

    op.create_table(
        "booking_policies",
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("deposit_policy", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("cancellation_policy", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("reschedule_policy", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("payment_terms", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("scheduling", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id"),
    )


def downgrade() -> None:
    op.drop_table("booking_policies")
    op.drop_table("pricing_settings")
    op.drop_index("ix_service_addons_service_type", table_name="service_addons")
    op.drop_table("service_addons")
    op.drop_index("ix_service_types_org_id", table_name="service_types")
    op.drop_table("service_types")
