"""merge all heads into one

Revision ID: 0091_merge_all_heads
Revises: 0088_client_users_rls_from_bookings, a2b3c4d5e6f7, a7c3b9d2e1f0, b9c8d7e6f5a4, c1a2b3c4d5e6, c2a1b3d4e5f6, c4d5e6f7a8b9, c7d8e9f0a1b2, c8d2e4f6a1b3, e2b1c4d5f6a7
Create Date: 2026-01-21
"""

from __future__ import annotations

revision = "0091_merge_all_heads"
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
    pass


def downgrade() -> None:
    pass
