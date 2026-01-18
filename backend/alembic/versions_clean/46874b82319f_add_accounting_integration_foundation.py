"""add accounting integration foundation tables

Revision ID: 46874b82319f
Revises: f2a4b7c8d9e0
Create Date: 2026-02-18 10:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

UUID_TYPE = sa.Uuid(as_uuid=True)

revision = "46874b82319f"
down_revision = "f2a4b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integrations_accounting_accounts",
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("realm_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "provider"),
    )
    op.create_index(
        "ix_integrations_accounting_accounts_org_id",
        "integrations_accounting_accounts",
        ["org_id"],
        unique=False,
    )

    op.create_table(
        "accounting_sync_state",
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "provider"),
    )
    op.create_index(
        "ix_accounting_sync_state_org_id",
        "accounting_sync_state",
        ["org_id"],
        unique=False,
    )

    op.create_table(
        "accounting_invoice_map",
        sa.Column("org_id", UUID_TYPE, nullable=False),
        sa.Column("local_invoice_id", sa.String(length=36), nullable=False),
        sa.Column("remote_invoice_id", sa.Text(), nullable=False),
        sa.Column("last_pushed_hash", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.org_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["local_invoice_id"], ["invoices.invoice_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("org_id", "local_invoice_id"),
        sa.UniqueConstraint(
            "org_id",
            "remote_invoice_id",
            name="uq_accounting_invoice_map_org_remote",
        ),
    )
    op.create_index(
        "ix_accounting_invoice_map_org_id",
        "accounting_invoice_map",
        ["org_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_accounting_invoice_map_org_id", table_name="accounting_invoice_map")
    op.drop_table("accounting_invoice_map")

    op.drop_index("ix_accounting_sync_state_org_id", table_name="accounting_sync_state")
    op.drop_table("accounting_sync_state")

    op.drop_index(
        "ix_integrations_accounting_accounts_org_id",
        table_name="integrations_accounting_accounts",
    )
    op.drop_table("integrations_accounting_accounts")
