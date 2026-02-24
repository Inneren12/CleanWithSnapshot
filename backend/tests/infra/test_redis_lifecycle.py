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
        # Mock redis.from_url
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_client = AsyncMock()
            mock_from_url.return_value = mock_client

            # Initialize client
            client = redis.get_redis_client()
            assert client is not None

            # Call close_redis_client
            await redis.close_redis_client()

            # Verify aclose was called
            mock_client.aclose.assert_awaited_once()

            # Verify global variable is reset
            assert redis._redis_client is None

            # Verify get_redis_client returns a new client (which would be a new mock call)
            # We need to reset the mock call count or expect a second call
            client_new = redis.get_redis_client()
            assert client_new is mock_client
            assert mock_from_url.call_count == 2

@pytest.mark.anyio
async def test_get_redis_client_no_url():
    # Reset the global variable
    redis._redis_client = None

    # Mock settings to ensure redis_url is None
    with patch.object(settings, "redis_url", None):
        client = redis.get_redis_client()
        assert client is None
