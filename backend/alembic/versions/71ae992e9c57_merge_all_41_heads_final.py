"""Merge all 41 heads final

Revision ID: 71ae992e9c57
Revises: 0011_jobs_and_export_replay, 0042_photo_review_and_signing, 0048_dispatcher_comm_audits, 0049_invoice_tax_snapshots, 0049_stripe_event_metadata, 0052_stripe_events_processed, 0065_add_client_users_org_id, 0067_event_logs_booking_fk_cascade, 0080_booking_address_usage_and_address_defaults, 0081_merge_heads_0048_and_0080, 0085_iam_roles_permissions, 0085_org_settings_core, 0085_pricing_policies_settings, 0086_merge_0085_heads, 0088_client_users_rls_from_bookings, 1a6b6e3f2c2c_add_billing_pause_fields, 2c3b4b9a1e9a_add_client_users_is_active, 34d313a57aa7_merge_heads_iam_prior_merge, 5d8c3a1b9e21_notifications_rules_presets, 6a2b1c6f3c2b_availability_blocks, 7a4c2d1f8e3b_notifications_digest_settings, 7f871a8d46f5_merge_alembic_heads, 9a5e2c8c64c0_perf_queue_indexes, 9f2b7c4d1a0e_team_settings_fields, a1b2c3d4e5f6_placeholder_head, a2b3c4d5e6f7_add_finance_tax_tables, a7c3b9d2e1f0_add_gcal_sync_foundation, b1c2d3e4f5a6_placeholder_head, b8e1c2d3f4a5_merge_heads_34d313a57aa7_6a2b1c6f3c2b, b9c8d7e6f5a4_add_inventory_suppliers, c1a2b3c4d5e6_add_rules_and_rule_runs, c2a1b3d4e5f6_add_lead_touchpoints, c4d5e6f7a8b9_add_inventory_consumption, c7d8e9f0a1b2_add_competitor_benchmarking, c8d2e4f6a1b3_add_leads_nurture_foundation, c9f0a1b2c3d4_merge_heads_b1c2d3e4f5a6_b7f4d2e9c1a0, cf72c4eb59bc_placeholder_head, d4e5f6a7b8c9_merge_heads_a1b2_b1c2_c9f0_cf72, e1f2a3b4c5d6_merge_heads_a1b2_b1c2_cf72_d4e5, e2b1c4d5f6a7_add_lead_scoring_tables, f83f22a8223b_merge_alembic_heads
Create Date: 2026-01-22

"""
from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "71ae992e9c57"
down_revision = (
    "0011_jobs_and_export_replay",
    "0042_photo_review_and_signing",
    "0048_dispatcher_comm_audits",
    "0049_invoice_tax_snapshots",
    "0049_stripe_event_metadata",
    "0052_stripe_events_processed",
    "0065",
    "0067",
    "0080_booking_address_usage_and_address_defaults",
    "0081_merge_heads_0048_and_0080",
    "0085_iam_roles_permissions",
    "0085_org_settings_core",
    "0085_pricing_policies_settings",
    "0086_merge_0085_heads",
    "0088_client_users_rls_from_bookings",
    "1a6b6e3f2c2c",
    "2c3b4b9a1e9a",
    "34d313a57aa7",
    "5d8c3a1b9e21",
    "6a2b1c6f3c2b",
    "7a4c2d1f8e3b",
    "7f871a8d46f5",
    "9a5e2c8c64c0",
    "9f2b7c4d1a0e",
    "a1b2c3d4e5f6",
    "a2b3c4d5e6f7",
    "a7c3b9d2e1f0",
    "b1c2d3e4f5a6",
    "b8e1c2d3f4a5",
    "b9c8d7e6f5a4",
    "c1a2b3c4d5e6",
    "c2a1b3d4e5f6",
    "c4d5e6f7a8b9",
    "c7d8e9f0a1b2",
    "c8d2e4f6a1b3",
    "c9f0a1b2c3d4",
    "cf72c4eb59bc",
    "d4e5f6a7b8c9",
    "e1f2a3b4c5d6",
    "e2b1c4d5f6a7",
    "f83f22a8223b",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge migration - no changes needed."""
    pass


def downgrade() -> None:
    """Merge migration - no changes needed."""
    pass
