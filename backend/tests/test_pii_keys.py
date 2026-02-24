import importlib
import pytest
from app.settings import settings, Settings
from pydantic import SecretStr
from cryptography.fernet import InvalidToken

def test_pii_keys_defaults():
    # Test that defaults are set to auth_secret_key
    # We create a new Settings instance to test validator logic
    # We need to provide required fields
    # We must set testing=False because APP_ENV=prod conflicts with implicit TESTING=true from env
    s = Settings(
        auth_secret_key="secret",
        app_env="prod",
        admin_proxy_auth_secret="a" * 32,
        client_portal_secret="client" * 10,
        worker_portal_secret="worker" * 10,
        metrics_token="metrics",
        testing=False,
    )
    assert s.pii_encryption_key.get_secret_value() == "secret"
    assert s.pii_blind_index_key.get_secret_value() == "secret"

def test_pii_keys_explicit():
    s = Settings(
        auth_secret_key="secret",
        pii_encryption_key="enc-key",
        pii_blind_index_key="blind-key",
        app_env="prod",
        admin_proxy_auth_secret="a" * 32,
        client_portal_secret="client" * 10,
        worker_portal_secret="worker" * 10,
        metrics_token="metrics",
        testing=False,
    )
    assert s.pii_encryption_key.get_secret_value() == "enc-key"
    assert s.pii_blind_index_key.get_secret_value() == "blind-key"

def test_encryption_uses_pii_key():
    from app.infra import encryption

    # Save original key
    original_enc_key = settings.pii_encryption_key

    try:
        # Set new key
        new_key = "new-encryption-key-that-is-different"
        settings.pii_encryption_key = SecretStr(new_key)

        # Reload module to re-derive key
        importlib.reload(encryption)

        # Encrypt something
        plaintext = "test-plaintext"
        ciphertext = encryption.encrypt_value(plaintext)

        # Check that we can decrypt it with the same key
        decrypted = encryption.decrypt_value(ciphertext)
        assert decrypted == plaintext

        # Change key again
        settings.pii_encryption_key = SecretStr("another-key")
        importlib.reload(encryption)

        # Decryption should fail
        with pytest.raises(InvalidToken):
            encryption.decrypt_value(ciphertext)

    finally:
        # Restore
        settings.pii_encryption_key = original_enc_key
        importlib.reload(encryption)

def test_blind_hash_uses_pii_key():
    from app.infra import encryption

    original_blind_key = settings.pii_blind_index_key

    try:
        key1 = "blind-key-1"
        settings.pii_blind_index_key = SecretStr(key1)
        hash1 = encryption.blind_hash("test")

        key2 = "blind-key-2"
        settings.pii_blind_index_key = SecretStr(key2)
        hash2 = encryption.blind_hash("test")

        assert hash1 != hash2

        # Verify it differs from auth_secret_key based hash
        # Assuming auth_secret_key is different from key1/key2
        settings.pii_blind_index_key = settings.auth_secret_key
        hash_auth = encryption.blind_hash("test")

        assert hash1 != hash_auth

    finally:
        settings.pii_blind_index_key = original_blind_key
