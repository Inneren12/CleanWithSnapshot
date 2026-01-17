"""add notifications rules presets

Revision ID: 5d8c3a1b9e21
Revises: 4c2b1c9e7d8a
Create Date: 2026-01-22 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

UUID_TYPE = sa.Uuid(as_uuid=True)

# revision identifiers, used by Alembic.
revision = "5d8c3a1b9e21"
down_revision = "4c2b1c9e7d8a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications_rules_presets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            UUID_TYPE,
            sa.ForeignKey("organizations.org_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("preset_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("notify_roles", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("notify_user_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("escalation_delay_min", sa.Integer(), nullable=True),
        sa.UniqueConstraint("org_id", "preset_key", name="uq_notifications_rules_presets_org_key"),
    )
    op.create_index(
        "ix_notifications_rules_presets_org_id",
        "notifications_rules_presets",
        ["org_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_rules_presets_org_id", table_name="notifications_rules_presets")
    op.drop_table("notifications_rules_presets")
