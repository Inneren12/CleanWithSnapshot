"""add_org_settings_rate_limits

Revision ID: fe3680762eb0
Revises: 437e5518ba99
Create Date: 2026-02-13 01:00:43.552158

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fe3680762eb0'
down_revision = '437e5518ba99'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('organization_settings', sa.Column('data_export_request_rate_limit_per_minute', sa.Integer(), nullable=True))
    op.add_column('organization_settings', sa.Column('data_export_request_rate_limit_per_hour', sa.Integer(), nullable=True))
    op.add_column('organization_settings', sa.Column('data_export_download_rate_limit_per_minute', sa.Integer(), nullable=True))
    op.add_column('organization_settings', sa.Column('data_export_download_failure_limit_per_window', sa.Integer(), nullable=True))
    op.add_column('organization_settings', sa.Column('data_export_download_lockout_limit_per_window', sa.Integer(), nullable=True))
    op.add_column('organization_settings', sa.Column('data_export_cooldown_minutes', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('organization_settings', 'data_export_cooldown_minutes')
    op.drop_column('organization_settings', 'data_export_download_lockout_limit_per_window')
    op.drop_column('organization_settings', 'data_export_download_failure_limit_per_window')
    op.drop_column('organization_settings', 'data_export_download_rate_limit_per_minute')
    op.drop_column('organization_settings', 'data_export_request_rate_limit_per_hour')
    op.drop_column('organization_settings', 'data_export_request_rate_limit_per_minute')
