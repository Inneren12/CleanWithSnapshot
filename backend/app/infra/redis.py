import logging
import redis.asyncio as redis
from app.settings import settings

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None

def get_redis_client() -> redis.Redis | None:
    global _redis_client
    if not settings.redis_url:
        return None
    if _redis_client is None:
        try:
            # Singleton instance, re-used across calls
            _redis_client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=settings.rate_limit_redis_probe_seconds,
                socket_connect_timeout=settings.rate_limit_redis_probe_seconds,
            )
        except Exception:
            logger.error("redis_connection_failed", exc_info=True)
            return None
    return _redis_client

async def close_redis_client() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
