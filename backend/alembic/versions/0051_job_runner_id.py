"""Add runner_id to job heartbeats

Revision ID: 0051_job_runner_id
Revises: 0050_data_rights
Create Date: 2025-02-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0051_job_runner_id"
down_revision: Union[str, None] = "0050_data_rights"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_heartbeats",
        sa.Column("runner_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("job_heartbeats", "runner_id")
