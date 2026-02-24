import pytest
from sqlalchemy import Column, Integer, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.infra.encryption import encrypt_value, decrypt_value, EncryptedString

def test_encryption_roundtrip():
    original = "test@example.com"
    encrypted = encrypt_value(original)
    assert original != encrypted
    assert decrypt_value(encrypted) == original

def test_long_value_encryption():
    # Fernet base64 overhead is approx 1.33x + header
    original = "a" * 100
    encrypted = encrypt_value(original)
    # verify it is long
    assert len(encrypted) > 100
    assert decrypt_value(encrypted) == original

# Use a local base for testing to avoid app model circular deps
TestBase = declarative_base()

class TestModel(TestBase):
    __tablename__ = 'test_encrypted_table'
    id = Column(Integer, primary_key=True)
    # EncryptedString with no length (should use Text)
    secret = Column(EncryptedString())

@pytest.mark.asyncio
async def test_text_column_capability():
    # We use sqlite for this test, but it validates that SA maps it to something that holds data.
    # In SQLite, everything is dynamic, but we can check the type mapping in SQLAlchemy at least.

    # Verify impl is Text
    assert isinstance(TestModel.secret.type.impl, Text) or TestModel.secret.type.impl is Text

    # We can't easily spin up a real DB here without resolving all app deps,
    # but the unit tests above confirm encryption produces long strings,
    # and the assertion above confirms we are using Text type in SA.
