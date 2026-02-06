"""Merge all 41 heads final

Revision ID: 71ae992e9c57
Revises: 0088_client_users_rls_from_bookings, a2b3c4d5e6f7_add_finance_tax_tables, a7c3b9d2e1f0_add_gcal_sync_foundation, b9c8d7e6f5a4_add_inventory_suppliers, c1a2b3c4d5e6_add_rules_and_rule_runs, c2a1b3d4e5f6_add_lead_touchpoints, c4d5e6f7a8b9_add_inventory_consumption, c7d8e9f0a1b2_add_competitor_benchmarking, c8d2e4f6a1b3_add_leads_nurture_foundation, e2b1c4d5f6a7_add_lead_scoring_tables
Create Date: 2026-01-22

"""
from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "71ae992e9c57"
down_revision = (
    "0088_client_users_rls_from_bookings",
    "a2b3c4d5e6f7",
    "a7c3b9d2e1f0",
    "b9c8d7e6f5a4",
    "c1a2b3c4d5e6",
    "c2a1b3d4e5f6",
    "c4d5e6f7a8b9",
    "c7d8e9f0a1b2",
    "c8d2e4f6a1b3",
    "e2b1c4d5f6a7",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge migration - no changes needed."""
    pass


def downgrade() -> None:
    """Merge migration - no changes needed."""
    pass
