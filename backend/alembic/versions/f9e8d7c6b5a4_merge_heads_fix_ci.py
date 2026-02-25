"""merge heads fix ci

Revision ID: f9e8d7c6b5a4
Revises: 0090_harden_legacy_passwords, 20231027_1400_rekey_blind_indexes, d9e8f7a6b5c4, d1e2f3a4b5c6
Create Date: 2026-02-24 14:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f9e8d7c6b5a4"
down_revision = (
    "0090_harden_legacy_passwords",
    "20231027_1400_rekey_blind_indexes",
    "d9e8f7a6b5c4",
    "d1e2f3a4b5c6",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
