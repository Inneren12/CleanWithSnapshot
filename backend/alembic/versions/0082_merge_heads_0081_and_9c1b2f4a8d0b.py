"""Merge heads 0081_merge_heads_0048_and_0080 and 9c1b2f4a8d0b.

Revision ID: 0082_merge_heads_0081_and_9c1b2f4a8d0b
Revises: 0081_merge_heads_0048_and_0080, 9c1b2f4a8d0b
Create Date: 2026-01-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op  # noqa: F401

revision = "0082_merge_heads_0081_and_9c1b2f4a8d0b"
down_revision = ("0081_merge_heads_0048_and_0080", "9c1b2f4a8d0b")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
