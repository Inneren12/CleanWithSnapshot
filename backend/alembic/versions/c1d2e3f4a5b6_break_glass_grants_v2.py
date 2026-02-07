"""Add break-glass grant metadata and review fields."""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "fedcba987654"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE breakglassscope AS ENUM ('org', 'global')")
    op.execute("CREATE TYPE breakglassstatus AS ENUM ('active', 'expired', 'revoked')")
    op.add_column("break_glass_sessions", sa.Column("actor_id", sa.String(length=128), nullable=True))
    op.add_column(
        "break_glass_sessions", sa.Column("incident_ref", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "break_glass_sessions",
        sa.Column(
            "scope",
            sa.Enum("org", "global", name="breakglassscope"),
            nullable=False,
            server_default="org",
        ),
    )
    op.add_column(
        "break_glass_sessions",
        sa.Column(
            "status",
            sa.Enum("active", "expired", "revoked", name="breakglassstatus"),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "break_glass_sessions",
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("break_glass_sessions", sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.add_column("break_glass_sessions", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("break_glass_sessions", sa.Column("reviewed_by", sa.String(length=128)))
    op.add_column("break_glass_sessions", sa.Column("review_notes", sa.Text()))

    op.execute(
        """
        UPDATE break_glass_sessions
        SET actor_id = actor
        WHERE actor_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE break_glass_sessions
        SET incident_ref = 'legacy-migration'
        WHERE incident_ref IS NULL
        """
    )
    op.execute(
        """
        UPDATE break_glass_sessions
        SET granted_at = created_at
        WHERE granted_at IS NULL
        """
    )

    op.alter_column("break_glass_sessions", "actor_id", nullable=False)
    op.alter_column("break_glass_sessions", "incident_ref", nullable=False)
    op.create_index(
        "ix_break_glass_sessions_status", "break_glass_sessions", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_break_glass_sessions_status", table_name="break_glass_sessions")
    op.drop_column("break_glass_sessions", "review_notes")
    op.drop_column("break_glass_sessions", "reviewed_by")
    op.drop_column("break_glass_sessions", "reviewed_at")
    op.drop_column("break_glass_sessions", "revoked_at")
    op.drop_column("break_glass_sessions", "granted_at")
    op.drop_column("break_glass_sessions", "status")
    op.drop_column("break_glass_sessions", "scope")
    op.drop_column("break_glass_sessions", "incident_ref")
    op.drop_column("break_glass_sessions", "actor_id")
    op.execute("DROP TYPE IF EXISTS breakglassstatus")
    op.execute("DROP TYPE IF EXISTS breakglassscope")
