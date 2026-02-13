"""fix outbox events uuid

Revision ID: 53b6a386be3c
Revises: fe3680762eb0
Create Date: 2026-02-13 01:15:51.780002

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '53b6a386be3c'
down_revision = 'fe3680762eb0'
branch_labels = None
depends_on = None


def upgrade():
    # Alter event_id to UUID
    op.alter_column('outbox_events', 'event_id',
               existing_type=sa.VARCHAR(length=36),
               type_=sa.UUID(),
               postgresql_using='event_id::uuid',
               existing_nullable=False)
    
    # Alter org_id to UUID
    op.alter_column('outbox_events', 'org_id',
               existing_type=sa.VARCHAR(length=36),
               type_=sa.UUID(),
               postgresql_using='org_id::uuid',
               existing_nullable=False)


def downgrade():
    op.alter_column('outbox_events', 'org_id',
               existing_type=sa.UUID(),
               type_=sa.VARCHAR(length=36),
               postgresql_using='org_id::text',
               existing_nullable=False)
    
    op.alter_column('outbox_events', 'event_id',
               existing_type=sa.UUID(),
               type_=sa.VARCHAR(length=36),
               postgresql_using='event_id::text',
               existing_nullable=False)
