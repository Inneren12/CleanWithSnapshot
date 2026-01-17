"""add digest state and referral credit trigger

Revision ID: f0b1c2d3e4f5
Revises: e6b1c2d3f4a5
Create Date: 2026-02-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f0b1c2d3e4f5"
down_revision = "e6b1c2d3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications_digest_state",
        sa.Column(
            "org_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("digest_key", sa.String(length=64), primary_key=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_period_key", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_notifications_digest_state_org_id",
        "notifications_digest_state",
        ["org_id"],
    )
    op.add_column(
        "organization_settings",
        sa.Column(
            "referral_credit_trigger",
            sa.String(length=32),
            nullable=False,
            server_default="booking_confirmed",
        ),
    )


def downgrade() -> None:
    op.drop_column("organization_settings", "referral_credit_trigger")
    op.drop_index(
        "ix_notifications_digest_state_org_id",
        table_name="notifications_digest_state",
    )
    op.drop_table("notifications_digest_state")
