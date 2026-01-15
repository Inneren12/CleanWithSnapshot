"""create availability blocks

Revision ID: 6a2b1c6f3c2b
Revises: f8dba77650d4
Create Date: 2025-05-15 00:00:01.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

UUID_TYPE = sa.Uuid(as_uuid=True)

# revision identifiers, used by Alembic.
revision = "6a2b1c6f3c2b"
down_revision = "f8dba77650d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "availability_blocks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("block_type", sa.String(length=20), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_availability_blocks_org", "availability_blocks", ["org_id"], unique=False)
    op.create_index(
        "ix_availability_blocks_scope",
        "availability_blocks",
        ["scope_type", "scope_id"],
        unique=False,
    )
    op.create_index(
        "ix_availability_blocks_window",
        "availability_blocks",
        ["starts_at", "ends_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_availability_blocks_window", table_name="availability_blocks")
    op.drop_index("ix_availability_blocks_scope", table_name="availability_blocks")
    op.drop_index("ix_availability_blocks_org", table_name="availability_blocks")
    op.drop_table("availability_blocks")
