import asyncio
import logging
import time
from collections import defaultdict, deque
from ipaddress import ip_address, ip_network
from typing import Deque, Dict, Protocol

import redis.asyncio as redis
from redis.exceptions import RedisError, ResponseError

from starlette.requests import Request


logger = logging.getLogger("app.rate_limit")


class RateLimiter(Protocol):
    async def allow(self, key: str) -> bool: ...

    async def reset(self) -> None: ...

    async def close(self) -> None: ...


class InMemoryRateLimiter:
    def __init__(
        self,
        requests_per_minute: int,
        cleanup_minutes: int = 10,
        *,
        window_seconds: int = 60,
    ) -> None:
        self.requests_per_minute = requests_per_minute
        self.cleanup_minutes = cleanup_minutes
        self.window_seconds = max(1, int(window_seconds))
        self._requests: Dict[str, Deque[float]] = defaultdict(deque)
        self._last_seen: Dict[str, float] = {}
        self._last_prune: float = 0.0
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        async with self._lock:
            now = time.time()
            self._maybe_prune(now)
            window_start = now - self.window_seconds
            timestamps = self._requests[key]
            while timestamps and timestamps[0] < window_start:
                timestamps.popleft()
            if len(timestamps) >= self.requests_per_minute:
                self._last_seen[key] = now
                return False
            timestamps.append(now)
            self._last_seen[key] = now
            return True

    async def reset(self) -> None:
        self._requests.clear()
        self._last_seen.clear()
        self._last_prune = 0.0

    async def close(self) -> None:
        return None

    def _maybe_prune(self, now: float) -> None:
        if now - self._last_prune < 60:
            return
        expire_before = now - (self.cleanup_minutes * 60)
        for key in list(self._requests.keys()):
            timestamps = self._requests[key]
            if not timestamps or self._last_seen.get(key, 0.0) < expire_before:
                self._requests.pop(key, None)
                self._last_seen.pop(key, None)
        self._last_prune = now


RATE_LIMIT_LUA = r'''
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local ttl_seconds = tonumber(ARGV[3])

local time = redis.call('TIME')
local now_ms = (time[1] * 1000) + math.floor(time[2] / 1000)

redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now_ms - window_ms)
local current = redis.call('ZCARD', KEYS[1])
if current >= limit then
  return 0
end

local seq = redis.call('INCR', KEYS[2])
local member = tostring(now_ms) .. ':' .. tostring(seq)
redis.call('ZADD', KEYS[1], now_ms, member)
redis.call('EXPIRE', KEYS[1], ttl_seconds)
redis.call('EXPIRE', KEYS[2], ttl_seconds)
return 1
'''


class RedisRateLimiter:
    def __init__(
        self,
        redis_url: str,
        requests_per_minute: int,
        cleanup_minutes: int = 10,
        redis_client: redis.Redis | None = None,
        fail_open_seconds: int = 300,
        health_probe_seconds: float = 5.0,
        *,
        window_seconds: int = 60,
    ) -> None:
        self.requests_per_minute = requests_per_minute
        self.cleanup_seconds = max(int(cleanup_minutes * 60), 60)
        self.redis = redis_client or redis.from_url(redis_url, encoding="utf-8", decode_responses=False)
        self._script_sha: str | None = None
        self.window_seconds = max(1, int(window_seconds))
        self.window_ms = self.window_seconds * 1000
        self.ttl_seconds = max(self.window_seconds + 2, self.cleanup_seconds)

        self.fail_open_seconds = max(1, fail_open_seconds)
        self.health_probe_seconds = max(0.5, health_probe_seconds)
        self._fallback = InMemoryRateLimiter(requests_per_minute, cleanup_minutes=cleanup_minutes)
        self._fail_open_until: float = 0.0
        self._last_probe: float = 0.0
        self._fail_open_lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        now = time.monotonic()
        if self._fail_open_until > now:
            return await self._allow_with_fail_open(key, now)
        try:
            set_key = self._key(key)
            seq_key = self._seq_key(key)

            allowed = await self._eval_script(set_key, seq_key)
            return bool(allowed)
        except RedisError:
            await self._enter_fail_open(now)
            logger.warning("redis rate limiter unavailable; using in-memory fallback")
            return await self._allow_with_fail_open(key, now)

    async def reset(self) -> None:
        try:
            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(cursor=cursor, match="rate-limit:*", count=100)
                if keys:
                    await self.redis.delete(*keys)
                if cursor == 0:
                    break
        except RedisError:
            logger.warning("redis rate limiter reset failed")

    async def close(self) -> None:
        try:
            await self.redis.aclose()
        except RedisError:
            logger.warning("redis rate limiter close failed")

    async def _enter_fail_open(self, now: float) -> None:
        async with self._fail_open_lock:
            if now < self._fail_open_until:
                return
            self._fail_open_until = now + self.fail_open_seconds
            self._last_probe = now
            await self._fallback.reset()

    async def _allow_with_fail_open(self, key: str, now: float) -> bool:
        if now - self._last_probe >= self.health_probe_seconds:
            self._last_probe = now
            try:
                await self.redis.ping()
            except RedisError:
                logger.debug("redis rate limiter still unavailable; continuing fallback")
            else:
                async with self._fail_open_lock:
                    self._fail_open_until = 0.0
                    await self._fallback.reset()
                logger.info("redis rate limiter recovered; resuming primary")
                return await self.allow(key)
        return await self._fallback.allow(key)

    def _key(self, key: str) -> str:
        return f"rate-limit:{key}"

    def _seq_key(self, key: str) -> str:
        return f"rate-limit:{key}:seq"

    async def _eval_script(self, set_key: str, seq_key: str) -> int:
        if not self._script_sha:
            self._script_sha = await self.redis.script_load(RATE_LIMIT_LUA)
        try:
            return await self.redis.evalsha(
                self._script_sha,
                2,
                set_key,
                seq_key,
                self.requests_per_minute,
                self.window_ms,
                self.ttl_seconds,
            )
        except ResponseError as exc:
            if "NOSCRIPT" not in str(exc):
                raise

        result = await self.redis.eval(
            RATE_LIMIT_LUA,
            2,
            set_key,
            seq_key,
            self.requests_per_minute,
            self.window_ms,
            self.ttl_seconds,
        )
        try:
            self._script_sha = await self.redis.script_load(RATE_LIMIT_LUA)
        except RedisError:
            logger.debug("rate_limit_script_reload_failed")
        return result


def create_rate_limiter(
    app_settings,
    requests_per_minute: int | None = None,
    *,
    window_seconds: int = 60,
) -> RateLimiter:
    limit = requests_per_minute or app_settings.rate_limit_per_minute
    if getattr(app_settings, "redis_url", None):
        return RedisRateLimiter(
            app_settings.redis_url,
            limit,
            cleanup_minutes=app_settings.rate_limit_cleanup_minutes,
            fail_open_seconds=getattr(app_settings, "rate_limit_fail_open_seconds", 300),
            health_probe_seconds=getattr(app_settings, "rate_limit_redis_probe_seconds", 5.0),
            window_seconds=window_seconds,
        )
    return InMemoryRateLimiter(
        limit,
        cleanup_minutes=app_settings.rate_limit_cleanup_minutes,
        window_seconds=window_seconds,
    )


_MAX_HEADER_LEN = 2048
_MAX_FORWARDED_HOPS = 20


def get_client_ip(request: Request, trusted_cidrs: list[str]) -> str:
    """Resolve the real client IP address.

    If the direct connection source is not in *trusted_cidrs*, return it as-is
    so forwarded headers cannot be spoofed by arbitrary clients.

    When the source IS in *trusted_cidrs* (e.g. a Caddy ingress), inspect
    forwarded headers in priority order:
      1. ``Forwarded`` (RFC 7239) – left-most ``for=`` value
      2. ``X-Forwarded-For`` – left-most IP

    Returns *source_ip* when the header is absent, malformed, or contains an
    invalid IP address.
    """
    source_ip = request.client.host if request.client else "unknown"
    if not trusted_cidrs or not _is_in_cidrs(source_ip, trusted_cidrs):
        return source_ip

    forwarded = request.headers.get("forwarded")
    if forwarded and len(forwarded) <= _MAX_HEADER_LEN:
        extracted = _extract_forwarded_for(forwarded)
        if extracted:
            return extracted

    xff = request.headers.get("x-forwarded-for")
    if xff and len(xff) <= _MAX_HEADER_LEN:
        extracted = _extract_xff(xff)
        if extracted:
            return extracted

    return source_ip


def resolve_client_key(
    request: Request,
    trust_proxy_headers: bool,
    trusted_proxy_ips: list[str],
    trusted_proxy_cidrs: list[str],
) -> str:
    if not trust_proxy_headers:
        return request.client.host if request.client else "unknown"
    # Merge individual trusted IPs (expressed as host CIDRs) with CIDR ranges.
    cidrs: list[str] = list(trusted_proxy_cidrs)
    for ip_str in trusted_proxy_ips:
        try:
            ip_obj = ip_address(ip_str)
            bits = 32 if ip_obj.version == 4 else 128
            cidrs.append(f"{ip_str}/{bits}")
        except ValueError:
            continue
    return get_client_ip(request, cidrs)


def _is_in_cidrs(client_host: str, cidrs: list[str]) -> bool:
    try:
        client_ip = ip_address(client_host)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if client_ip in ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def _extract_forwarded_for(header: str) -> str | None:
    """Parse RFC 7239 ``Forwarded`` header; return left-most ``for=`` IP.

    Handles:
    - ``for=192.0.2.1``
    - ``for="192.0.2.1"``
    - ``for="[2001:db8::1]"`` (quoted IPv6)
    - ``for=[2001:db8::1]`` (unquoted IPv6)
    - ``for=192.0.2.1:4711`` (IPv4 with port)
    """
    element = header.split(",")[0].strip()
    for directive in element.split(";"):
        directive = directive.strip()
        if not directive.lower().startswith("for="):
            continue
        value = directive[4:]
        # Strip surrounding double-quotes.
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        # IPv6 in brackets: [2001:db8::1] or [2001:db8::1]:port
        if value.startswith("["):
            close = value.find("]")
            if close == -1:
                return None
            value = value[1:close]
        else:
            # IPv4 may carry a port (exactly one colon). Strip it.
            if value.count(":") == 1:
                value = value.split(":")[0]
        try:
            ip_address(value)
            return value
        except ValueError:
            return None
    return None


def _extract_xff(header: str) -> str | None:
    """Parse ``X-Forwarded-For`` header; return left-most valid IP."""
    ips = [ip.strip() for ip in header.split(",")]
    if not ips or len(ips) > _MAX_FORWARDED_HOPS:
        return None
    try:
        ip_address(ips[0])
        return ips[0]
    except ValueError:
        return None
