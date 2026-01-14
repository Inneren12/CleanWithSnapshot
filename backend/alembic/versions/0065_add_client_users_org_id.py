"""add org_id to client_users for multi-tenancy

Revision ID: 0065
Revises: 0064
Create Date: 2026-01-13 10:05:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Determine if we're using PostgreSQL or SQLite
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"

    # Add org_id column to client_users table (nullable initially to allow data migration)
    if is_postgres:
        op.add_column(
            "client_users",
            sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    else:
        op.add_column(
            "client_users",
            sa.Column("org_id", sa.String(length=36), nullable=True),
        )

    # Set org_id to default_org_id for existing records
    # This SQL works for both PostgreSQL and SQLite
    conn.execute(
        sa.text(
            """
            UPDATE client_users
            SET org_id = (SELECT org_id FROM organizations LIMIT 1)
            WHERE org_id IS NULL
            """
        )
    )

    # Make org_id NOT NULL after backfilling and add foreign key constraint
    if is_postgres:
        op.alter_column("client_users", "org_id", nullable=False)
        op.create_foreign_key(
            "fk_client_users_org_id",
            "client_users",
            "organizations",
            ["org_id"],
            ["org_id"],
            ondelete="CASCADE",
        )
    else:
        with op.batch_alter_table("client_users") as batch_op:
            batch_op.alter_column("org_id", nullable=False)
            batch_op.create_foreign_key(
                "fk_client_users_org_id",
                "organizations",
                ["org_id"],
                ["org_id"],
                ondelete="CASCADE",
            )

    # Add index on org_id for faster queries
    op.create_index(
        "ix_client_users_org_id",
        "client_users",
        ["org_id"],
        unique=False,
    )

    # Add additional fields for client management
    op.add_column(
        "client_users",
        sa.Column("phone", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "client_users",
        sa.Column("address", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "client_users",
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.add_column(
        "client_users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"

    if is_sqlite:
        inspector = sa.inspect(conn)
        has_named_fk = any(
            fk.get("name") == "fk_client_users_org_id"
            for fk in inspector.get_foreign_keys("client_users")
        )
        with op.batch_alter_table("client_users", recreate="always") as batch_op:
            if has_named_fk:
                batch_op.drop_constraint("fk_client_users_org_id", type_="foreignkey")
            batch_op.drop_index("ix_client_users_org_id")
            batch_op.drop_column("updated_at")
            batch_op.drop_column("notes")
            batch_op.drop_column("address")
            batch_op.drop_column("phone")
            batch_op.drop_column("org_id")
        return

    # Drop additional columns
    op.drop_column("client_users", "updated_at")
    op.drop_column("client_users", "notes")
    op.drop_column("client_users", "address")
    op.drop_column("client_users", "phone")

    # Drop index
    op.drop_index("ix_client_users_org_id", table_name="client_users")

    # Drop foreign key
    op.drop_constraint("fk_client_users_org_id", "client_users", type_="foreignkey")

    # Drop org_id column
    op.drop_column("client_users", "org_id")
