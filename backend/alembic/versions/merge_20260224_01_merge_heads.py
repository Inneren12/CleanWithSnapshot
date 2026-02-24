"""merge heads

Revision ID: merge_20260224_01
Revises: 0090_harden_legacy_passwords, 20231027_1400_rekey_blind_indexes
Create Date: 2026-02-24 15:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'merge_20260224_01'
down_revision: Union[str, None] = ('0090_harden_legacy_passwords', '20231027_1400_rekey_blind_indexes')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
