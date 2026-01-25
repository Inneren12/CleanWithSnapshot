"""add feature flag lifecycle metadata

Revision ID: ab12cd34ef56
Revises: fe12a3b4c5d6
Create Date: 2026-03-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "ab12cd34ef56"
down_revision = "fe12a3b4c5d6"
branch_labels = None
depends_on = None


FEATURE_KEYS = [
    "module.dashboard",
    "module.schedule",
    "module.invoices",
    "module.quality",
    "module.teams",
    "module.analytics",
    "module.finance",
    "module.pricing",
    "module.marketing",
    "module.leads",
    "module.inventory",
    "module.training",
    "module.notifications_center",
    "module.settings",
    "module.integrations",
    "module.api",
    "dashboard.weather",
    "dashboard.weather_traffic",
    "schedule.optimization_ai",
    "schedule.optimization",
    "quality.photo_evidence",
    "quality.nps",
    "finance.reports",
    "finance.cash_flow",
    "analytics.attribution_multitouch",
    "analytics.competitors",
    "pricing.service_types",
    "pricing.booking_policies",
    "marketing.analytics",
    "marketing.email_campaigns",
    "marketing.email_segments",
    "inventory.usage_analytics",
    "training.library",
    "training.quizzes",
    "training.certs",
    "api.settings",
    "integrations.google_calendar",
    "integrations.accounting.quickbooks",
    "integrations.maps",
    "notifications.rules_builder",
    "leads.nurture",
    "leads.scoring",
]


def upgrade() -> None:
    op.create_table(
        "feature_flags",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "lifecycle_state",
            sa.String(length=32),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    feature_flags = sa.table(
        "feature_flags",
        sa.column("key", sa.String),
        sa.column("owner", sa.String),
        sa.column("purpose", sa.String),
        sa.column("lifecycle_state", sa.String),
    )
    op.bulk_insert(
        feature_flags,
        [
            {
                "key": key,
                "owner": "legacy",
                "purpose": "Legacy feature flag pending metadata backfill.",
                "lifecycle_state": "active",
            }
            for key in FEATURE_KEYS
        ],
    )
    op.execute(
        """
        INSERT INTO feature_flags (key, owner, purpose, lifecycle_state)
        SELECT DISTINCT jsonb_object_keys(feature_overrides) AS key,
            'legacy',
            'Legacy feature flag pending metadata backfill.',
            'active'
        FROM org_feature_configs
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("feature_flags")
