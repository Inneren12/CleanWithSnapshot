import pytest
from unittest.mock import patch
from app.infra.encryption import EncryptedString, _CIPHER_SUITE
from app.settings import settings
import logging

def test_decrypt_fail_dev_returns_none(caplog):
    """
    In dev/test, a decryption failure should return None and log a warning.
    """
    enc_type = EncryptedString()
    bad_ciphertext = "gAAAA_this_is_bad_and_will_fail_decryption"

    with patch.object(settings, "app_env", "dev"):
        with caplog.at_level(logging.WARNING):
            result = enc_type.process_result_value(bad_ciphertext, dialect=None)

        # Verify result is None
        assert result is None

        # Verify log message
        assert "Decryption failed in non-secure environment" in caplog.text
        assert "Returning None instead of ciphertext" in caplog.text

def test_decrypt_fail_prod_raises():
    """
    In prod, a decryption failure should raise exception (fail-closed).
    """
    enc_type = EncryptedString()
    bad_ciphertext = "gAAAA_this_is_bad_and_will_fail_decryption"

    with patch.object(settings, "app_env", "prod"):
        with pytest.raises(ValueError, match="Decryption failed in secure environment"):
            enc_type.process_result_value(bad_ciphertext, dialect=None)

def test_round_trip():
    """
    Verify that valid plaintext is encrypted and decrypted correctly.
    """
    enc_type = EncryptedString()
    plaintext = "sensitive_secret_data"
    dialect = None

    # Encrypt
    ciphertext = enc_type.process_bind_param(plaintext, dialect)
    assert ciphertext != plaintext
    assert ciphertext.startswith("gAAAA")

    # Decrypt
    decrypted = enc_type.process_result_value(ciphertext, dialect)
    assert decrypted == plaintext

def test_plaintext_passthrough():
    """
    Verify that non-encrypted values (no prefix) are returned as-is.
    """
    enc_type = EncryptedString()
    plaintext = "not_encrypted_string"
    dialect = None

    # Should just return the value as is because it doesn't start with gAAAA
    result = enc_type.process_result_value(plaintext, dialect)
    assert result == plaintext
