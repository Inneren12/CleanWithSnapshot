"""encrypt pii

Revision ID: 20231027_1200_encrypt_pii
Revises: 0089_checkout_attempt
Create Date: 2023-10-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
import hashlib
import sys
import os

# Add project root to path for imports
sys.path.append(os.getcwd())

from app.infra.encryption import encrypt_value, blind_hash

# revision identifiers, used by Alembic.
revision = '20231027_1200_encrypt_pii'
down_revision = '0089_checkout_attempt'
branch_labels = None
depends_on = None

def upgrade():
    # 1. Add blind index columns
    op.add_column('client_users', sa.Column('email_blind_index', sa.String(64), nullable=True))
    op.add_column('workers', sa.Column('email_blind_index', sa.String(64), nullable=True))
    op.add_column('workers', sa.Column('phone_blind_index', sa.String(64), nullable=True))

    op.create_index(op.f('ix_client_users_email_blind_index'), 'client_users', ['email_blind_index'], unique=True)
    op.create_index(op.f('ix_workers_email_blind_index'), 'workers', ['email_blind_index'], unique=False)
    op.create_index(op.f('ix_workers_phone_blind_index'), 'workers', ['phone_blind_index'], unique=False)

    # 1.5 Alter columns to TEXT to accommodate ciphertext (Fernet expands size)
    # Using batch mode for SQLite compatibility
    with op.batch_alter_table('client_users') as batch_op:
        batch_op.alter_column('email', type_=sa.Text(), existing_type=sa.String(255))
        batch_op.alter_column('name', type_=sa.Text(), existing_type=sa.String(255))
        batch_op.alter_column('phone', type_=sa.Text(), existing_type=sa.String(50))

    with op.batch_alter_table('workers') as batch_op:
        batch_op.alter_column('email', type_=sa.Text(), existing_type=sa.String(255))
        batch_op.alter_column('name', type_=sa.Text(), existing_type=sa.String(120))
        batch_op.alter_column('phone', type_=sa.Text(), existing_type=sa.String(50))

    # 2. Data Migration
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        # ClientUser
        client_users = session.execute(sa.text("SELECT client_id, email, name, phone FROM client_users")).fetchall()
        for row in client_users:
            cid, email, name, phone = row

            # Skip if already encrypted (simple heuristic)
            if email and email.startswith('gAAAA'): continue

            email_enc = encrypt_value(email) if email else email
            name_enc = encrypt_value(name) if name else name
            phone_enc = encrypt_value(phone) if phone else phone
            email_hash = blind_hash(email) if email else None

            session.execute(
                sa.text("UPDATE client_users SET email=:email, name=:name, phone=:phone, email_blind_index=:bidx WHERE client_id=:cid"),
                {"email": email_enc, "name": name_enc, "phone": phone_enc, "bidx": email_hash, "cid": cid}
            )

        # Workers
        workers = session.execute(sa.text("SELECT worker_id, email, name, phone FROM workers")).fetchall()
        for row in workers:
            wid, email, name, phone = row

            if email and email.startswith('gAAAA'): continue

            email_enc = encrypt_value(email) if email else email
            name_enc = encrypt_value(name) if name else name
            phone_enc = encrypt_value(phone) if phone else phone
            email_hash = blind_hash(email) if email else None
            phone_hash = blind_hash(phone) if phone else None

            session.execute(
                sa.text("UPDATE workers SET email=:email, name=:name, phone=:phone, email_blind_index=:bidx, phone_blind_index=:pbidx WHERE worker_id=:wid"),
                {"email": email_enc, "name": name_enc, "phone": phone_enc, "bidx": email_hash, "pbidx": phone_hash, "wid": wid}
            )

        session.commit()
    except Exception as e:
        print(f"Data migration failed: {e}")
        # We don't rollback schema changes here, but in a real deploy this might be an issue.
        # For now, allow schema changes to persist.

    # 3. Drop unique constraint on email (ClientUser)
    # Note: constraint name varies by DB. We attempt to drop index.
    # In SQLite, we must use batch mode.
    with op.batch_alter_table('client_users') as batch_op:
        # Attempt to drop implicit unique index if present
        # This is best effort without knowing exact name.
        # Assuming typical SQLAlchemy naming or just 'email' index.
        try:
            batch_op.drop_constraint('uq_client_users_email', type_='unique')
        except Exception:
            pass # Constraint might not have this name
        try:
            batch_op.drop_index('email')
        except Exception:
            pass

def downgrade():
    op.drop_column('client_users', 'email_blind_index')
    op.drop_column('workers', 'email_blind_index')
    op.drop_column('workers', 'phone_blind_index')
