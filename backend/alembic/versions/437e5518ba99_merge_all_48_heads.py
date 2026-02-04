"""merge all 48 migration heads

Revision ID: 437e5518ba99
Revises: 0011_jobs_and_export_replay, 0018_subscriptions, 0025_admin_audit_logs, 0042_photo_review_and_signing, 0048_dispatcher_comm_audits, 0049_invoice_tax_snapshots, 0049_stripe_event_metadata, 0065, 0067, 0080_booking_address_usage_and_address_defaults, 0081_merge_heads_0048_and_0080, 0085_iam_roles_permissions, 0085_org_settings_core, 0085_pricing_policies_settings, 0086_merge_0085_heads, 0088_client_users_rls_from_bookings, 1a2b3c4d5e6f, 1a6b6e3f2c2c, 2c3b4b9a1e9a, 2f3a4b5c6d7e, 34d313a57aa7, 5d8c3a1b9e21, 6a2b1c6f3c2b, 7a4c2d1f8e3b, 7f871a8d46f5, 9a5e2c8c64c0, 9f2b7c4d1a0e, a12b3c4d5e6f, a2b3c4d5e6f7, a7c3b9d2e1f0, a9b8c7d6e5f4, ab12cd34ef56, b8e1c2d3f4a5, b9c8d7e6f5a4, c0e1f2a3b4c5, c1a2b3c4d5e6, c1d2e3f4a5b6, c2a1b3d4e5f6, c4d5e6f7a8b9, c7d8e9f0a1b2, c8d2e4f6a1b3, c9f0a1b2c3d4, cf72c4eb59bc, d2f1c0a9b7e4, d4e5f6a7b8c9, e1f2a3b4c5d6, e2b1c4d5f6a7, f83f22a8223b
Create Date: 2026-02-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "437e5518ba99"
down_revision = (
    "0011_jobs_and_export_replay",
    "0018_subscriptions",
    "0025_admin_audit_logs",
    "0042_photo_review_and_signing",
    "0048_dispatcher_comm_audits",
    "0049_invoice_tax_snapshots",
    "0049_stripe_event_metadata",
    "0065",
    "0067",
    "0080_booking_address_usage_and_address_defaults",
    "0081_merge_heads_0048_and_0080",
    "0085_iam_roles_permissions",
    "0085_org_settings_core",
    "0085_pricing_policies_settings",
    "0086_merge_0085_heads",
    "0088_client_users_rls_from_bookings",
    "1a2b3c4d5e6f",
    "1a6b6e3f2c2c",
    "2c3b4b9a1e9a",
    "2f3a4b5c6d7e",
    "34d313a57aa7",
    "5d8c3a1b9e21",
    "6a2b1c6f3c2b",
    "7a4c2d1f8e3b",
    "7f871a8d46f5",
    "9a5e2c8c64c0",
    "9f2b7c4d1a0e",
    "a12b3c4d5e6f",
    "a2b3c4d5e6f7",
    "a7c3b9d2e1f0",
    "a9b8c7d6e5f4",
    "ab12cd34ef56",
    "b8e1c2d3f4a5",
    "b9c8d7e6f5a4",
    "c0e1f2a3b4c5",
    "c1a2b3c4d5e6",
    "c1d2e3f4a5b6",
    "c2a1b3d4e5f6",
    "c4d5e6f7a8b9",
    "c7d8e9f0a1b2",
    "c8d2e4f6a1b3",
    "c9f0a1b2c3d4",
    "cf72c4eb59bc",
    "d2f1c0a9b7e4",
    "d4e5f6a7b8c9",
    "e1f2a3b4c5d6",
    "e2b1c4d5f6a7",
    "f83f22a8223b",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
