import pytest
from sqlalchemy import Column, Integer, Text, select
from sqlalchemy.orm import declarative_base
from app.infra.encryption import EncryptedString
from app.settings import settings

Base = declarative_base()

class EncryptedModel(Base):
    __tablename__ = 'test_encrypted_model'
    id = Column(Integer, primary_key=True)
    secret_data = Column(EncryptedString)

def test_encryption_decryption():
    # Setup
    key = settings.auth_secret_key.get_secret_value()
    assert key is not None

    # Instantiate type
    enc_type = EncryptedString()
    bind = None
    dialect = None

    # Test process_bind_param (Encryption)
    plaintext = "sensitive_info"
    ciphertext = enc_type.process_bind_param(plaintext, dialect)
    assert ciphertext != plaintext
    assert ciphertext.startswith("gAAAA") # Fernet token prefix

    # Test process_result_value (Decryption)
    decrypted = enc_type.process_result_value(ciphertext, dialect)
    assert decrypted == plaintext

def test_none_handling():
    enc_type = EncryptedString()
    assert enc_type.process_bind_param(None, None) is None
    assert enc_type.process_result_value(None, None) is None
