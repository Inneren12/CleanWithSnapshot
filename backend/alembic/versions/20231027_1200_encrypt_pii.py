"""encrypt pii

Revision ID: 20231027_1200_encrypt_pii
Revises: ff1a2b3c4d5e
Create Date: 2023-10-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
import hashlib
import hmac
import base64
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# revision identifiers, used by Alembic.
revision = '20231027_1200_encrypt_pii'
down_revision = 'ff1a2b3c4d5e'
branch_labels = None
depends_on = None

# --- Local Crypto Helpers (No App Imports) ---

def _get_secret_key():
    # Attempt to read from env, similar to app settings but direct
    # Order: AUTH_SECRET_KEY -> dev default if allowed?
    # For migration safety, we should strictly require it if possible,
    # or fallback ONLY if we are sure it matches app logic.
    # App logic uses pydantic settings.
    key = os.getenv("AUTH_SECRET_KEY")
    if not key:
        # Check if we are in a dev environment where defaults are acceptable
        app_env = os.getenv("APP_ENV", "dev")
        if app_env in ("dev", "local", "test"):
            return "dev-auth-secret"
        raise ValueError("AUTH_SECRET_KEY must be set for production migration")
    return key

def _derive_fernet_key(secret: str) -> bytes:
    salt = b"cleaning-bot-static-salt"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))

_CIPHER_SUITE = None

def _get_cipher():
    global _CIPHER_SUITE
    if _CIPHER_SUITE is None:
        secret = _get_secret_key()
        key = _derive_fernet_key(secret)
        _CIPHER_SUITE = Fernet(key)
    return _CIPHER_SUITE

def encrypt_value(value: str) -> str:
    if not value: return value
    return _get_cipher().encrypt(value.encode()).decode("utf-8")

def blind_hash(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    secret = _get_secret_key().encode("utf-8")
    return hmac.new(secret, normalized.encode("utf-8"), hashlib.sha256).hexdigest()

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

    # 2. Data Migration with Batching
    bind = op.get_bind()
    session = Session(bind=bind)

    BATCH_SIZE = 1000

    # ClientUser
    offset = 0
    while True:
        # Select PKs and fields to encrypt
        client_users = session.execute(
            sa.text("SELECT client_id, email, name, phone FROM client_users ORDER BY client_id LIMIT :limit OFFSET :offset"),
            {"limit": BATCH_SIZE, "offset": offset}
        ).fetchall()

        if not client_users:
            break

        for row in client_users:
            cid, email, name, phone = row

            # Skip if already encrypted (heuristic: Fernet output starts with gAAAA)
            if email and email.startswith('gAAAA'): continue

            try:
                email_enc = encrypt_value(email) if email else email
                name_enc = encrypt_value(name) if name else name
                phone_enc = encrypt_value(phone) if phone else phone
                email_hash = blind_hash(email) if email else None

                session.execute(
                    sa.text("UPDATE client_users SET email=:email, name=:name, phone=:phone, email_blind_index=:bidx WHERE client_id=:cid"),
                    {"email": email_enc, "name": name_enc, "phone": phone_enc, "bidx": email_hash, "cid": cid}
                )
            except Exception as e:
                # Fail fast
                print(f"Error encrypting client_user {cid}: {e}")
                raise e

        session.commit() # Commit batch
        offset += BATCH_SIZE

    # Workers
    offset = 0
    while True:
        workers = session.execute(
            sa.text("SELECT worker_id, email, name, phone FROM workers ORDER BY worker_id LIMIT :limit OFFSET :offset"),
            {"limit": BATCH_SIZE, "offset": offset}
        ).fetchall()

        if not workers:
            break

        for row in workers:
            wid, email, name, phone = row

            if email and email.startswith('gAAAA'): continue

            try:
                email_enc = encrypt_value(email) if email else email
                name_enc = encrypt_value(name) if name else name
                phone_enc = encrypt_value(phone) if phone else phone
                email_hash = blind_hash(email) if email else None
                phone_hash = blind_hash(phone) if phone else None

                session.execute(
                    sa.text("UPDATE workers SET email=:email, name=:name, phone=:phone, email_blind_index=:bidx, phone_blind_index=:pbidx WHERE worker_id=:wid"),
                    {"email": email_enc, "name": name_enc, "phone": phone_enc, "bidx": email_hash, "pbidx": phone_hash, "wid": wid}
                )
            except Exception as e:
                print(f"Error encrypting worker {wid}: {e}")
                raise e

        session.commit()
        offset += BATCH_SIZE

    # 3. Drop unique constraint on email (ClientUser)
    with op.batch_alter_table('client_users') as batch_op:
        try:
            batch_op.drop_constraint('uq_client_users_email', type_='unique')
        except Exception:
            pass
        try:
            batch_op.drop_index('email')
        except Exception:
            pass

def downgrade():
    # Drop indexes first
    op.drop_index(op.f('ix_client_users_email_blind_index'), table_name='client_users')
    op.drop_index(op.f('ix_workers_email_blind_index'), table_name='workers')
    op.drop_index(op.f('ix_workers_phone_blind_index'), table_name='workers')

    # Drop columns
    op.drop_column('client_users', 'email_blind_index')
    op.drop_column('workers', 'email_blind_index')
    op.drop_column('workers', 'phone_blind_index')

    # Revert types to String (optional/best-effort, as data is now encrypted text)
    # WARNING: Data is still encrypted. We are NOT decrypting in downgrade
    # because that would require the key and might fail if key changed.
    # Leaving data as TEXT is safer than truncating it by reverting to String(255).
    # If strictly needed, we would need a decryption loop here.
    # For now, leaving types as TEXT to avoid data loss.
