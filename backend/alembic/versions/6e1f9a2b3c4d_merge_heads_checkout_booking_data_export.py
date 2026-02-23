"""merge checkout, booking overlap, and data export heads

Revision ID: 6e1f9a2b3c4d
Revises: 0089_checkout_attempt, 9d3e4f5a6b7c, 2b4c6d8e0f1a
Create Date: 2026-03-03 00:00:00.000000
"""

from __future__ import annotations


revision = "6e1f9a2b3c4d"
down_revision = ("0089_checkout_attempt", "9d3e4f5a6b7c", "2b4c6d8e0f1a")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
