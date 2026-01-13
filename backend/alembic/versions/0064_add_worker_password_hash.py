"""add worker password_hash and phone index

Revision ID: 0064
Revises: bc6a9a9f5c2b
Create Date: 2026-01-13 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0064"
down_revision = "bc6a9a9f5c2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add password_hash column to workers table
    op.add_column(
        "workers",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )

    # Add index on phone for faster worker login lookups
    op.create_index(
        "ix_workers_phone",
        "workers",
        ["phone"],
        unique=False,
    )


def downgrade() -> None:
    # Drop index on phone
    op.drop_index("ix_workers_phone", table_name="workers")

    # Drop password_hash column
    op.drop_column("workers", "password_hash")
