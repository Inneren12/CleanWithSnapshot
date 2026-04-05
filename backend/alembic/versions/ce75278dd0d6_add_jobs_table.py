"""add_jobs_table

Revision ID: ce75278dd0d6
Revises: merge_20260224_01
Create Date: 2026-04-05 15:33:29.077748

"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision = 'ce75278dd0d6'
down_revision = 'merge_20260224_01'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        'jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_type', sa.String(length=50), nullable=False),
        sa.Column('status', sa.Enum('queued', 'running', 'success', 'failed', 'cancelled', name='job_status'), server_default='queued', nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('result_json', sa.Text(), nullable=True),
        sa.Column('error_code', sa.String(length=100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_attempts', sa.Integer(), server_default='3', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('dedupe_key', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_jobs_created_at', 'jobs', ['created_at'], unique=False)
    op.create_index('ix_jobs_dedupe_key', 'jobs', ['dedupe_key'], unique=False)
    op.create_index('ix_jobs_type_status', 'jobs', ['job_type', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_jobs_type_status', table_name='jobs')
    op.drop_index('ix_jobs_dedupe_key', table_name='jobs')
    op.drop_index('ix_jobs_created_at', table_name='jobs')
    op.drop_table('jobs')
    op.execute("DROP TYPE IF EXISTS job_status")
