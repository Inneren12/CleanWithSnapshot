"""merge all 51 migration heads

Revision ID: 437e5518ba99
Revises: 1a2b3c4d5e6f, 1a2b3c4d5e70, 2f3a4b5c6d7e, a12b3c4d5e6f, a2b3c4d5e6f8, a9b8c7d6e5f4, c1d2e3f4a5b6, c1d2e3f4a5b7
Create Date: 2026-02-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "437e5518ba99"
down_revision = (
    "1a2b3c4d5e6f",
    "1a2b3c4d5e70",
    "2f3a4b5c6d7e",
    "a12b3c4d5e6f",
    "a2b3c4d5e6f8",
    "a9b8c7d6e5f4",
    "c1d2e3f4a5b6",
    "c1d2e3f4a5b7",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
