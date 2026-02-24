import pytest
import pytest_asyncio
import uuid
from unittest.mock import MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.domain.saas import service as saas_service
from app.domain.saas.db_models import User
from app.infra.db import Base
from app.settings import settings
from app.infra.encryption import blind_hash

# Setup in-memory sqlite db
@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session

    await engine.dispose()

@pytest.mark.asyncio
async def test_backup_codes_hashing(db_session):
    # Create user
    user = User(
        user_id=uuid.uuid4(),
        email="test@example.com",
        is_active=True
    )
    db_session.add(user)
    await db_session.flush()

    # Enroll TOTP
    secret, uri, plaintext_codes = await saas_service.enroll_totp(db_session, user)

    # Verify return values
    assert len(plaintext_codes) > 0
    assert len(plaintext_codes[0]) == 10 # Default length

    # Verify storage
    await db_session.refresh(user)
    stored_hashes = user.backup_codes
    assert len(stored_hashes) == len(plaintext_codes)
    assert plaintext_codes[0] not in stored_hashes # Plaintext not stored

    # Verify hashing logic matches
    expected_hash = blind_hash(plaintext_codes[0], org_id=user.user_id)
    assert expected_hash in stored_hashes

    # Verify usage (Success)
    # We mock _check_totp_replay to allow (return False) just in case verify_totp calls it,
    # though verifying backup code should bypass TOTP check?
    # Let's check implementation: Yes, verifies backup code first and returns True immediately.

    valid = await saas_service.verify_totp(db_session, user, plaintext_codes[0])
    assert valid is True

    # Verify consumption
    await db_session.refresh(user)
    assert len(user.backup_codes) == len(plaintext_codes) - 1
    assert expected_hash not in user.backup_codes

    # Verify reuse (Fail)
    valid_reuse = await saas_service.verify_totp(db_session, user, plaintext_codes[0])
    assert valid_reuse is False

@pytest.mark.asyncio
async def test_totp_replay_fail_closed():
    # Mock redis client returning None
    with patch("app.domain.saas.service.get_redis_client", return_value=None):
        # Case 1: Secure Env -> Fail Closed (Return True = Replay Detected/Denied)
        with patch.object(settings, "app_env", "prod"):
            is_replay = await saas_service._check_totp_replay(uuid.uuid4(), 123)
            assert is_replay is True

        # Case 2: Dev Env -> Fail Open (Return False = Fresh/Allowed)
        with patch.object(settings, "app_env", "dev"):
            is_replay = await saas_service._check_totp_replay(uuid.uuid4(), 123)
            assert is_replay is False

@pytest.mark.asyncio
async def test_totp_replay_redis_flow():
    # Mock redis client
    mock_redis = MagicMock()
    mock_redis.set = MagicMock()

    # Setup async mock for set
    async def async_set(*args, **kwargs):
        return True # success (fresh)
    mock_redis.set.side_effect = async_set

    with patch("app.domain.saas.service.get_redis_client", return_value=mock_redis):
        # Fresh token
        is_replay = await saas_service._check_totp_replay(uuid.uuid4(), 123)
        assert is_replay is False

        # Used token (redis returns False for nx set)
        async def async_set_fail(*args, **kwargs):
            return False # key exists
        mock_redis.set.side_effect = async_set_fail

        is_replay = await saas_service._check_totp_replay(uuid.uuid4(), 123)
        assert is_replay is True

@pytest.mark.asyncio
async def test_backup_codes_constant_time_comparison(db_session):
    user = User(user_id=uuid.uuid4(), email="test-time@example.com", is_active=True)
    db_session.add(user)
    await db_session.flush()

    _, _, codes = await saas_service.enroll_totp(db_session, user)
    valid_code = codes[0]

    # Patch hmac.compare_digest in app.domain.saas.service
    # Since we imported hmac in service.py, we patch where it is used
    with patch("app.domain.saas.service.hmac.compare_digest", side_effect=lambda a, b: a == b) as mock_compare:
        await saas_service.verify_totp(db_session, user, valid_code)

        # It should be called for each backup code (10) to ensure constant time
        assert mock_compare.call_count == len(codes)

@pytest.mark.asyncio
async def test_regenerate_backup_codes(db_session):
    user = User(user_id=uuid.uuid4(), email="test-regen@example.com", is_active=True)
    db_session.add(user)
    await db_session.flush()

    # Enroll
    _, _, old_codes = await saas_service.enroll_totp(db_session, user)

    # Verify an old code works
    assert await saas_service.verify_totp(db_session, user, old_codes[0]) is True

    # Regenerate
    # Note: verify_totp consumed old_codes[0]
    new_codes = await saas_service.regenerate_backup_codes(db_session, user)

    # Verify different
    assert set(new_codes) != set(old_codes)

    # Verify old codes don't work (try second one which wasn't used)
    assert await saas_service.verify_totp(db_session, user, old_codes[1]) is False

    # Verify new codes work
    assert await saas_service.verify_totp(db_session, user, new_codes[0]) is True
