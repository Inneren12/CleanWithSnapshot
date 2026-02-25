import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.infra import redis
from app.settings import settings

@pytest.mark.anyio
async def test_redis_client_singleton_behavior():
    # Reset the global variable to ensure a clean state
    redis._redis_client = None

    # Mock settings to ensure redis_url is set
    with patch.object(settings, "redis_url", "redis://localhost:6379/0"):
        # Mock redis.from_url to avoid actual connection
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_client = AsyncMock()
            mock_from_url.return_value = mock_client

            # First call should create a new client
            client1 = redis.get_redis_client()
            assert client1 is mock_client
            mock_from_url.assert_called_once_with(
                "redis://localhost:6379/0",
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=settings.rate_limit_redis_probe_seconds,
                socket_connect_timeout=settings.rate_limit_redis_probe_seconds,
            )

            # Second call should return the same client
            client2 = redis.get_redis_client()
            assert client2 is mock_client
            mock_from_url.assert_called_once()  # Still called only once

@pytest.mark.anyio
async def test_close_redis_client():
    # Reset the global variable
    redis._redis_client = None

    # Mock settings to ensure redis_url is set
    with patch.object(settings, "redis_url", "redis://localhost:6379/0"):
        # Mock redis.from_url with distinct clients across calls
        with patch("redis.asyncio.from_url") as mock_from_url:
            client1 = AsyncMock()
            client2 = AsyncMock()
            mock_from_url.side_effect = [client1, client2]

            # First call creates first client
            client = redis.get_redis_client()
            assert client is client1

            # Closing should close first client and clear singleton
            await redis.close_redis_client()
            client1.aclose.assert_awaited_once()
            assert redis._redis_client is None

            # Second call creates and returns a new client
            client_new = redis.get_redis_client()
            assert client_new is client2
            assert client_new is not client1
            assert mock_from_url.call_count == 2


@pytest.mark.anyio
async def test_close_redis_client_noop_when_none():
    # Ensure no client exists before closing
    redis._redis_client = None

    # Should be a no-op and not raise
    await redis.close_redis_client()
    assert redis._redis_client is None

@pytest.mark.anyio
async def test_get_redis_client_no_url():
    # Reset the global variable
    redis._redis_client = None

    # Mock settings to ensure redis_url is None
    with patch.object(settings, "redis_url", None):
        client = redis.get_redis_client()
        assert client is None
