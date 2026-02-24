"""fix ci heads

Revision ID: merge_20260224_02
Revises: d1e2f3a4b5c6, f9e8d7c6b5a4, merge_20260224_01
Create Date: 2026-02-24 19:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'merge_20260224_02'
down_revision: Union[str, None] = ('d1e2f3a4b5c6', 'f9e8d7c6b5a4', 'merge_20260224_01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
# force ci
