"""Org settings core

Revision ID: 0085_org_settings_core
Revises: 0084_feature_modules_visibility
Create Date: 2025-02-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0085_org_settings_core"
down_revision = "0084_feature_modules_visibility"
branch_labels = None
depends_on = None


def _json_default(value: str):
    return sa.text(value)


def upgrade():
    op.create_table(
        "organization_settings",
        sa.Column(
            "org_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("timezone", sa.String(length=128), nullable=False, server_default="America/Edmonton"),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default="CAD"),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="en"),
        sa.Column("business_hours", sa.JSON(), nullable=False, server_default=_json_default("'{}'")),
        sa.Column("holidays", sa.JSON(), nullable=False, server_default=_json_default("'[]'")),
        sa.Column("legal_name", sa.String(length=255), nullable=True),
        sa.Column("legal_bn", sa.String(length=64), nullable=True),
        sa.Column("legal_gst_hst", sa.String(length=64), nullable=True),
        sa.Column("legal_address", sa.Text(), nullable=True),
        sa.Column("legal_phone", sa.String(length=64), nullable=True),
        sa.Column("legal_email", sa.String(length=255), nullable=True),
        sa.Column("legal_website", sa.String(length=255), nullable=True),
        sa.Column("branding", sa.JSON(), nullable=False, server_default=_json_default("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_table("organization_settings")
