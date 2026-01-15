"""Add org feature configs and user UI preferences.

Revision ID: 0084_feature_modules_visibility
Revises: 0083_dispatcher_alert_state
Create Date: 2026-01-15 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0084_feature_modules_visibility"
down_revision = "0083_dispatcher_alert_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_feature_configs",
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("feature_overrides", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
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
        "user_ui_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_key", sa.String(length=255), nullable=False),
        sa.Column("hidden_keys", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "user_key", name="uq_user_ui_prefs_org_user"),
    )


def downgrade() -> None:
    op.drop_table("user_ui_preferences")
    op.drop_table("org_feature_configs")
