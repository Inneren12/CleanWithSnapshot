"""rekey blind indexes with hmac and org scope

Revision ID: 20231027_1400_rekey_blind_indexes
Revises: 20231027_1300_fix_missing_cols
Create Date: 2023-10-27 14:00:00.000000

REQUIRED ENV VARS:
  AUTH_SECRET_KEY (mandatory)
"""
import base64
import hashlib
import hmac
import os
import uuid
from typing import Optional

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy.orm import Session

# revision identifiers, used by Alembic.
revision = '20231027_1400_rekey_blind_indexes'
down_revision = '20231027_1300_fix_missing_cols'
branch_labels = None
depends_on = None


def get_auth_secret() -> str:
    # 1. Try env var
    secret = os.getenv("AUTH_SECRET_KEY")
    if secret:
        return secret

    raise ValueError("AUTH_SECRET_KEY must be set (env var)")


def get_fernet_key(secret: str) -> bytes:
    # Match app.infra.encryption._derive_key logic
    salt = b"cleaning-bot-static-salt"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


def decrypt_value(value: Optional[str], cipher: Fernet) -> Optional[str]:
    if not value:
        return None

    # Heuristic: Fernet tokens start with gAAAA
    if not value.startswith("gAAAA"):
        return value

    try:
        return cipher.decrypt(value.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        # In migration, we might want to fail fast if decryption fails
        print(f"Decryption failed for value starting with gAAAA: {exc}")
        raise exc


def compute_blind_hash(value: Optional[str], org_id: Optional[uuid.UUID], secret_key: str) -> Optional[str]:
    if not value:
        return None

    normalized = value.strip().lower()
    secret_bytes = secret_key.encode("utf-8")

    # Mix in org_id if provided
    if org_id:
        payload = f"{str(org_id)}:{normalized}".encode("utf-8")
    else:
        # Fallback for global scope if ever needed, but requirement implies org_scope
        payload = normalized.encode("utf-8")

    return hmac.new(secret_bytes, payload, hashlib.sha256).hexdigest()


def upgrade():
    # 0. Setup crypto
    auth_secret = get_auth_secret()
    fernet_key = get_fernet_key(auth_secret)
    cipher = Fernet(fernet_key)

    bind = op.get_bind()
    session = Session(bind=bind)

    # 1. Drop old indexes/constraints if they exist (clean slate)
    # We use try/except to make it idempotent-ish regarding drops
    tables_indexes = [
        ('client_users', 'ix_client_users_email_blind_index'),
        ('workers', 'ix_workers_email_blind_index'),
        ('workers', 'ix_workers_phone_blind_index'),
        ('workers', 'ix_workers_phone_idx'), # Was created in previous version of this file
    ]

    for table, idx in tables_indexes:
        try:
            op.drop_index(idx, table_name=table)
        except Exception:
            pass

    # Drop potential constraints from failed runs
    try:
        op.drop_constraint('uq_client_users_org_email', 'client_users', type_='unique')
    except Exception:
        pass
    try:
        op.drop_constraint('uq_workers_org_phone', 'workers', type_='unique')
    except Exception:
        pass


    # 2. Rekey Client Users
    BATCH_SIZE = 1000
    offset = 0
    while True:
        # Select necessary columns
        rows = session.execute(
            sa.text("SELECT client_id, email, org_id FROM client_users ORDER BY client_id LIMIT :limit OFFSET :offset"),
            {"limit": BATCH_SIZE, "offset": offset}
        ).fetchall()

        if not rows:
            break

        for row in rows:
            cid, email_enc, org_id = row
            if not email_enc:
                continue

            try:
                email = decrypt_value(email_enc, cipher)
                new_hash = compute_blind_hash(email, org_id, auth_secret)

                session.execute(
                    sa.text("UPDATE client_users SET email_blind_index=:bidx WHERE client_id=:cid"),
                    {"bidx": new_hash, "cid": cid}
                )
            except Exception as e:
                print(f"Error rekeying client_user {cid}: {e}")
                raise e

        session.commit()
        offset += BATCH_SIZE

    # 3. Rekey Workers
    offset = 0
    while True:
        rows = session.execute(
            sa.text("SELECT worker_id, email, phone, org_id FROM workers ORDER BY worker_id LIMIT :limit OFFSET :offset"),
            {"limit": BATCH_SIZE, "offset": offset}
        ).fetchall()

        if not rows:
            break

        for row in rows:
            wid, email_enc, phone_enc, org_id = row

            try:
                email = decrypt_value(email_enc, cipher)
                email_hash = compute_blind_hash(email, org_id, auth_secret)

                phone = decrypt_value(phone_enc, cipher)
                phone_hash = compute_blind_hash(phone, org_id, auth_secret)

                session.execute(
                    sa.text("UPDATE workers SET email_blind_index=:bidx, phone_blind_index=:pbidx WHERE worker_id=:wid"),
                    {"bidx": email_hash, "pbidx": phone_hash, "wid": wid}
                )
            except Exception as e:
                print(f"Error rekeying worker {wid}: {e}")
                raise e

        session.commit()
        offset += BATCH_SIZE

    # 4. Check for duplicates BEFORE adding constraints
    # Client Users
    dupes_clients = session.execute(sa.text("""
        SELECT org_id, email_blind_index, COUNT(*)
        FROM client_users
        WHERE email_blind_index IS NOT NULL
        GROUP BY org_id, email_blind_index
        HAVING COUNT(*) > 1
    """)).fetchall()

    if dupes_clients:
        msg = f"Duplicate client emails found in orgs: {dupes_clients}"
        print(msg)
        raise ValueError(msg)

    # Workers
    dupes_workers = session.execute(sa.text("""
        SELECT org_id, phone_blind_index, COUNT(*)
        FROM workers
        WHERE phone_blind_index IS NOT NULL
        GROUP BY org_id, phone_blind_index
        HAVING COUNT(*) > 1
    """)).fetchall()

    if dupes_workers:
        msg = f"Duplicate worker phones found in orgs: {dupes_workers}"
        print(msg)
        raise ValueError(msg)

    # 5. Create Indexes and Constraints
    # client_users
    op.create_index('ix_client_users_email_blind_index', 'client_users', ['email_blind_index'], unique=False)
    op.create_unique_constraint('uq_client_users_org_email', 'client_users', ['org_id', 'email_blind_index'])

    # workers
    op.create_index('ix_workers_email_blind_index', 'workers', ['email_blind_index'], unique=False)
    op.create_index('ix_workers_phone_blind_index', 'workers', ['phone_blind_index'], unique=False)
    op.create_unique_constraint('uq_workers_org_phone', 'workers', ['org_id', 'phone_blind_index'])


def downgrade():
    # Drop constraints
    try:
        op.drop_constraint('uq_client_users_org_email', 'client_users', type_='unique')
    except Exception:
        pass

    try:
        op.drop_constraint('uq_workers_org_phone', 'workers', type_='unique')
    except Exception:
        pass

    # Drop indexes
    try:
        op.drop_index('ix_client_users_email_blind_index', table_name='client_users')
    except Exception:
        pass

    try:
        op.drop_index('ix_workers_email_blind_index', table_name='workers')
    except Exception:
        pass

    try:
        op.drop_index('ix_workers_phone_blind_index', table_name='workers')
    except Exception:
        pass
