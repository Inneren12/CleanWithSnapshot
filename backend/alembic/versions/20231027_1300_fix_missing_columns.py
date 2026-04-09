"""fix missing columns backup_codes and hash

Revision ID: 20231027_1300_fix_missing_cols
Revises: 20231027_1200_encrypt_pii
Create Date: 2023-10-27 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20231027_1300_fix_missing_cols'
down_revision = '20231027_1200_encrypt_pii'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Add backup_codes to users
    user_columns = [c["name"] for c in inspector.get_columns("users")]
    if "backup_codes" not in user_columns:
        op.add_column('users', sa.Column('backup_codes', sa.JSON(), server_default=sa.text("'[]'"), nullable=False))

    # Add hash columns to admin_audit_logs
    audit_columns = [c["name"] for c in inspector.get_columns("admin_audit_logs")]
    if "prev_hash" not in audit_columns:
        op.add_column('admin_audit_logs', sa.Column('prev_hash', sa.String(length=64), nullable=True))
    if "hash" not in audit_columns:
        op.add_column('admin_audit_logs', sa.Column('hash', sa.String(length=64), nullable=True))

    # Add unique index on hash
    audit_indexes = [ix["name"] for ix in inspector.get_indexes("admin_audit_logs")]
    if "ix_admin_audit_logs_hash" not in audit_indexes:
        op.create_index('ix_admin_audit_logs_hash', 'admin_audit_logs', ['hash'], unique=True)


def downgrade():
    op.drop_index('ix_admin_audit_logs_hash', table_name='admin_audit_logs')
    op.drop_column('admin_audit_logs', 'hash')
    op.drop_column('admin_audit_logs', 'prev_hash')
    op.drop_column('users', 'backup_codes')
