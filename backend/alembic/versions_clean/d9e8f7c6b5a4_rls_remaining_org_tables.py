"""add RLS policies for remaining org-scoped tables

Revision ID: d9e8f7c6b5a4
Revises: c3e9a1b2d4f5
Create Date: 2026-04-21 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d9e8f7c6b5a4"
down_revision = "c3e9a1b2d4f5"
branch_labels = None
depends_on = None

SCHEMA = "public"
TABLES = (
    "access_review_runs",
    "accounting_invoice_map",
    "accounting_sync_state",
    "admin_audit_logs",
    "admin_idempotency",
    "api_tokens",
    "audit_legal_holds",
    "availability_blocks",
    "booking_photos",
    "booking_policies",
    "break_glass_sessions",
    "client_addresses",
    "client_feedback",
    "client_notes",
    "competitors",
    "config_audit_logs",
    "data_deletion_requests",
    "data_export_requests",
    "dispatcher_alert_state",
    "dispatcher_communication_audits",
    "email_campaigns",
    "email_failures",
    "email_segments",
    "feature_flag_audit_logs",
    "finance_cash_snapshots",
    "finance_tax_exports",
    "finance_tax_instalments",
    "iam_roles",
    "integration_audit_logs",
    "integrations_accounting_accounts",
    "integrations_gcal_calendars",
    "integrations_gcal_event_map",
    "integrations_gcal_sync_state",
    "integrations_google_accounts",
    "inventory_categories",
    "inventory_consumption",
    "inventory_items",
    "inventory_suppliers",
    "lead_quote_followups",
    "lead_quotes",
    "lead_scores_snapshot",
    "lead_scoring_rules",
    "lead_touchpoints",
    "maps_usage",
    "memberships",
    "notifications_digest_settings",
    "notifications_digest_state",
    "notifications_events",
    "notifications_reads",
    "notifications_rules_presets",
    "nps_responses",
    "nps_tokens",
    "nurture_campaigns",
    "nurture_enrollments",
    "nurture_step_log",
    "nurture_steps",
    "order_photo_tombstones",
    "org_feature_configs",
    "org_storage_reservations",
    "organization_billing",
    "organization_settings",
    "organization_usage_events",
    "organizations",
    "outbox_events",
    "password_reset_events",
    "pricing_settings",
    "purchase_orders",
    "quality_issue_responses",
    "quality_issue_tags",
    "quality_issues",
    "quality_review_replies",
    "rule_escalations",
    "rule_runs",
    "rules",
    "saas_sessions",
    "schedule_external_blocks",
    "service_types",
    "stripe_events",
    "subscriptions",
    "token_events",
    "unsubscribe",
    "user_ui_preferences",
    "worker_certificates",
    "worker_notes",
    "worker_onboarding",
    "worker_reviews",
)
TENANT_EXPR = "org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid"


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _policy_sql(table: str) -> str:
    qualified_table = f"{SCHEMA}.{table}"
    policy_name = f"{table}_org_isolation"
    return f"""
DO $$
BEGIN
    IF to_regclass('{SCHEMA}.{table}') IS NULL THEN
        RAISE NOTICE 'Skipping RLS policy setup for %.% (table missing)', '{SCHEMA}', '{table}';
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = '{SCHEMA}'
          AND c.relname = '{table}'
          AND c.relrowsecurity
    ) THEN
        EXECUTE 'ALTER TABLE IF EXISTS {qualified_table} ENABLE ROW LEVEL SECURITY';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = '{SCHEMA}'
          AND c.relname = '{table}'
          AND c.relforcerowsecurity
    ) THEN
        EXECUTE 'ALTER TABLE IF EXISTS {qualified_table} FORCE ROW LEVEL SECURITY';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = '{SCHEMA}'
          AND tablename = '{table}'
          AND policyname = '{policy_name}'
    ) THEN
        EXECUTE $sql$
            CREATE POLICY {policy_name} ON {qualified_table}
            USING ({TENANT_EXPR})
            WITH CHECK ({TENANT_EXPR})
        $sql$;
    END IF;
END
$$;
"""


def _downgrade_sql(table: str) -> str:
    qualified_table = f"{SCHEMA}.{table}"
    policy_name = f"{table}_org_isolation"
    return f"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = '{SCHEMA}'
          AND tablename = '{table}'
          AND policyname = '{policy_name}'
    ) THEN
        EXECUTE 'DROP POLICY {policy_name} ON {qualified_table}';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = '{SCHEMA}'
          AND c.relname = '{table}'
          AND (c.relforcerowsecurity OR c.relrowsecurity)
    ) THEN
        EXECUTE 'ALTER TABLE {qualified_table} NO FORCE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE {qualified_table} DISABLE ROW LEVEL SECURITY';
    END IF;
END
$$;
"""


def upgrade() -> None:
    if not _is_postgres():
        return

    for table in TABLES:
        op.execute(sa.text(_policy_sql(table)))


def downgrade() -> None:
    if not _is_postgres():
        return

    for table in TABLES:
        op.execute(sa.text(_downgrade_sql(table)))
