"""encrypt pii

Revision ID: 20231027_1200_encrypt_pii
Revises: ff1a2b3c4d5e
Create Date: 2023-10-27 12:00:00.000000

REQUIRED ENV VARS:
  AUTH_SECRET_KEY (mandatory)
"""

import base64
import hashlib
import hmac
import os

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy.orm import Session

# revision identifiers, used by Alembic.
revision = "20231027_1200_encrypt_pii"
down_revision = "ff1a2b3c4d5e"
branch_labels = None
depends_on = None


def _get_auth_secret() -> str:
    key = os.getenv("AUTH_SECRET_KEY")
    if not key:
        raise ValueError(
            "AUTH_SECRET_KEY must be set to run this migration. "
            "This migration encrypts/decrypts PII and recomputes blind indexes. "
            "Ensure AUTH_SECRET_KEY matches the application configuration."
        )
    return key


def _get_encryption_key() -> str:
    return os.getenv("PII_ENCRYPTION_KEY") or _get_auth_secret()


def _get_blind_index_key() -> str:
    return os.getenv("PII_BLIND_INDEX_KEY") or _get_auth_secret()


def _derive_fernet_key(secret: str) -> bytes:
    salt = b"cleaning-bot-static-salt"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


_CIPHER_SUITE = None


def _get_cipher() -> Fernet:
    global _CIPHER_SUITE
    if _CIPHER_SUITE is None:
        key = _derive_fernet_key(_get_encryption_key())
        _CIPHER_SUITE = Fernet(key)
    return _CIPHER_SUITE


def encrypt_value(value: str) -> str:
    if not value:
        return value
    return _get_cipher().encrypt(value.encode()).decode("utf-8")


def blind_hash(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    secret = _get_blind_index_key().encode("utf-8")
    return hmac.new(secret, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def _backfill_client_users(session: Session, batch_size: int) -> None:
    offset = 0
    while True:
        rows = session.execute(
            sa.text(
                "SELECT client_id, email, name, phone FROM client_users "
                "ORDER BY client_id LIMIT :limit OFFSET :offset"
            ),
            {"limit": batch_size, "offset": offset},
        ).fetchall()
        if not rows:
            break

        for cid, email, name, phone in rows:
            if email and email.startswith("gAAAA"):
                continue
            session.execute(
                sa.text(
                    "UPDATE client_users "
                    "SET email=:email, name=:name, phone=:phone, email_blind_index=:bidx "
                    "WHERE client_id=:cid"
                ),
                {
                    "email": encrypt_value(email) if email else email,
                    "name": encrypt_value(name) if name else name,
                    "phone": encrypt_value(phone) if phone else phone,
                    "bidx": blind_hash(email) if email else None,
                    "cid": cid,
                },
            )

        session.commit()
        offset += batch_size


def _backfill_workers(session: Session, batch_size: int) -> None:
    offset = 0
    while True:
        rows = session.execute(
            sa.text(
                "SELECT worker_id, email, name, phone FROM workers "
                "ORDER BY worker_id LIMIT :limit OFFSET :offset"
            ),
            {"limit": batch_size, "offset": offset},
        ).fetchall()
        if not rows:
            break

        for wid, email, name, phone in rows:
            if email and email.startswith("gAAAA"):
                continue
            session.execute(
                sa.text(
                    "UPDATE workers "
                    "SET email=:email, name=:name, phone=:phone, "
                    "email_blind_index=:bidx, phone_blind_index=:pbidx "
                    "WHERE worker_id=:wid"
                ),
                {
                    "email": encrypt_value(email) if email else email,
                    "name": encrypt_value(name) if name else name,
                    "phone": encrypt_value(phone) if phone else phone,
                    "bidx": blind_hash(email) if email else None,
                    "pbidx": blind_hash(phone) if phone else None,
                    "wid": wid,
                },
            )

        session.commit()
        offset += batch_size


def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        op.add_column("client_users", sa.Column("email_blind_index", sa.String(64), nullable=True))
        op.add_column("workers", sa.Column("email_blind_index", sa.String(64), nullable=True))
        op.add_column("workers", sa.Column("phone_blind_index", sa.String(64), nullable=True))

        op.create_index(op.f("ix_client_users_email_blind_index"), "client_users", ["email_blind_index"], unique=True)
        op.create_index(op.f("ix_workers_email_blind_index"), "workers", ["email_blind_index"], unique=False)
        op.create_index(op.f("ix_workers_phone_blind_index"), "workers", ["phone_blind_index"], unique=False)

        with op.batch_alter_table("client_users") as batch_op:
            batch_op.alter_column("email", type_=sa.Text(), existing_type=sa.String(255))
            batch_op.alter_column("name", type_=sa.Text(), existing_type=sa.String(255))
            batch_op.alter_column("phone", type_=sa.Text(), existing_type=sa.String(50))

        with op.batch_alter_table("workers") as batch_op:
            batch_op.alter_column("email", type_=sa.Text(), existing_type=sa.String(255))
            batch_op.alter_column("name", type_=sa.Text(), existing_type=sa.String(120))
            batch_op.alter_column("phone", type_=sa.Text(), existing_type=sa.String(50))

        _backfill_client_users(session, batch_size=1000)
        _backfill_workers(session, batch_size=1000)

        try:
            with op.batch_alter_table("client_users") as batch_op:
                batch_op.drop_constraint("uq_client_users_email", type_="unique")
        except Exception:
            pass

        try:
            with op.batch_alter_table("client_users") as batch_op:
                batch_op.drop_index("email")
        except Exception:
            pass
    except Exception:
        session.rollback()
        raise


def downgrade() -> None:
    op.drop_index(op.f("ix_client_users_email_blind_index"), table_name="client_users")
    op.drop_index(op.f("ix_workers_email_blind_index"), table_name="workers")
    op.drop_index(op.f("ix_workers_phone_blind_index"), table_name="workers")

    op.drop_column("client_users", "email_blind_index")
    op.drop_column("workers", "email_blind_index")
    op.drop_column("workers", "phone_blind_index")
