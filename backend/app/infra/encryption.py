from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import Text, TypeDecorator

from app.settings import settings


def _derive_key() -> bytes:
    # Use a static salt to ensure key consistency across restarts.
    # In a real production scenario, this salt should probably be secret too or managed carefully.
    # Using the pii_encryption_key as the source material.
    salt = b"cleaning-bot-static-salt"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    secret = settings.pii_encryption_key.get_secret_value()
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


_CIPHER_SUITE = Fernet(_derive_key())


class EncryptedString(TypeDecorator):
    """Encrypts string values using Fernet (symmetric encryption)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        return _CIPHER_SUITE.encrypt(value.encode()).decode("utf-8")

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None

        # Heuristic: Fernet tokens are URL-safe base64 and start with gAAAA
        # If it doesn't look like a token, assume plaintext (transitional support)
        if not str(value).startswith("gAAAA"):
            return value

        try:
            return _CIPHER_SUITE.decrypt(value.encode("utf-8")).decode("utf-8")
        except Exception as exc:
            from app.infra.environment import SECURE_ENVIRONMENTS
            # In secure environments, we must fail closed to prevent data corruption or leaks.
            # In dev/test, we allow fallback for ease of debugging or partial migrations.
            if settings.app_env in SECURE_ENVIRONMENTS:
                raise ValueError("Decryption failed in secure environment") from exc

            # Fallback for dev/test
            return value


def encrypt_value(value: str) -> str:
    return _CIPHER_SUITE.encrypt(value.encode()).decode("utf-8")


def decrypt_value(token: str) -> str:
    return _CIPHER_SUITE.decrypt(token.encode("utf-8")).decode("utf-8")


def blind_hash(value: str | None, org_id: str | uuid.UUID | None = None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    secret = settings.pii_blind_index_key.get_secret_value().encode("utf-8")

    # Mix in org_id if provided to enforce isolation
    payload = normalized.encode("utf-8")
    if org_id:
        payload = f"{str(org_id)}:{normalized}".encode("utf-8")

    return hmac.new(secret, payload, hashlib.sha256).hexdigest()
