"""Merge alembic heads 0048 and 0080

Revision ID: 0081_merge_heads_0048_and_0080
Revises: 0048_dispatcher_comm_audits, 0080_booking_address_usage_and_address_defaults
Create Date: 2026-03-20
"""

from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "0081_merge_heads_0048_and_0080"
down_revision = ("0048_dispatcher_comm_audits", "0080_booking_address_usage_and_address_defaults")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
