from __future__ import annotations

import base64
import hashlib
import os
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import String, TypeDecorator

from app.settings import settings


def _derive_key() -> bytes:
    # Use a static salt to ensure key consistency across restarts.
    # In a real production scenario, this salt should probably be secret too or managed carefully.
    # Using the auth_secret_key as the source material.
    salt = b"cleaning-bot-static-salt"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    secret = settings.auth_secret_key.get_secret_value()
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


_CIPHER_SUITE = Fernet(_derive_key())


class EncryptedString(TypeDecorator):
    """Encrypts string values using Fernet (symmetric encryption)."""

    impl = String
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
        try:
            return _CIPHER_SUITE.decrypt(value.encode("utf-8")).decode("utf-8")
        except Exception:
            # Fallback if decryption fails (e.g. data was not encrypted yet)
            # This helps during migration or if key rotates without re-encryption
            return value


def encrypt_value(value: str) -> str:
    return _CIPHER_SUITE.encrypt(value.encode()).decode("utf-8")


def decrypt_value(token: str) -> str:
    return _CIPHER_SUITE.decrypt(token.encode("utf-8")).decode("utf-8")


def blind_hash(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
