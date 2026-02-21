"""Tests for get_client_ip() – trusted-proxy chain IP resolution.

Covers:
- Untrusted source: spoofed XFF / Forwarded headers are ignored.
- Trusted proxy: forwarded headers are honored and the real client IP
  is extracted.
- RFC 7239 Forwarded header parsing (IPv4, IPv6 brackets, with port).
- Rate-limiter key behaviour (spoof ignored vs. honored) via ASGI
  middleware integration.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.infra.security import InMemoryRateLimiter, get_client_ip
from app.main import RateLimitMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    client_host: str,
    xff: str | None = None,
    forwarded: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    if forwarded is not None:
        headers.append((b"forwarded", forwarded.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": headers,
        "client": (client_host, 1234),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    }
    return Request(scope)


class _ForceClientIPMiddleware(BaseHTTPMiddleware):
    """Override the ASGI scope client address for testing."""

    def __init__(self, app, client_ip: str) -> None:
        super().__init__(app)
        self.client_ip = client_ip

    async def dispatch(self, request: Request, call_next):
        request.scope["client"] = (self.client_ip, 1234)
        return await call_next(request)


class _RateLimitTestSettings:
    trust_proxy_headers = True
    trusted_proxy_ips: list[str] = []
    rate_limit_disable_exempt_paths = False

    def __init__(self, trusted_cidrs: list[str], rate_limit_per_minute: int = 1) -> None:
        self.trusted_proxy_cidrs = trusted_cidrs
        self.rate_limit_per_minute = rate_limit_per_minute


def _build_test_app(
    limiter: InMemoryRateLimiter,
    trusted_cidrs: list[str],
    client_ip: str,
) -> FastAPI:
    """Build a minimal app with RateLimitMiddleware and a forced client IP."""
    app_settings = _RateLimitTestSettings(trusted_cidrs)
    app = FastAPI()
    # Middleware added later runs first; _ForceClientIPMiddleware must be
    # outermost so that RateLimitMiddleware sees the overridden client IP.
    app.add_middleware(RateLimitMiddleware, limiter=limiter, app_settings=app_settings)
    app.add_middleware(_ForceClientIPMiddleware, client_ip=client_ip)

    @app.get("/test")
    def test_route():
        return {"ok": True}

    return app


# ---------------------------------------------------------------------------
# Unit tests – get_client_ip()
# ---------------------------------------------------------------------------


class TestUntrustedSource:
    """Forwarded headers MUST be ignored when the source IP is not trusted."""

    def test_xff_ignored(self):
        request = _make_request("1.2.3.4", xff="9.8.7.6")
        assert get_client_ip(request, ["10.0.0.0/8"]) == "1.2.3.4"

    def test_forwarded_ignored(self):
        request = _make_request("1.2.3.4", forwarded="for=9.8.7.6")
        assert get_client_ip(request, ["10.0.0.0/8"]) == "1.2.3.4"

    def test_empty_cidrs_never_trusts_any_header(self):
        request = _make_request("10.0.0.1", xff="203.0.113.5")
        assert get_client_ip(request, []) == "10.0.0.1"

    def test_source_ip_not_matching_cidr(self):
        # 1.2.3.4 is not in 10.0.0.0/8
        request = _make_request("1.2.3.4", xff="203.0.113.5")
        assert get_client_ip(request, ["10.0.0.0/8"]) == "1.2.3.4"


class TestTrustedProxy:
    """Forwarded headers MUST be honored when the source is a trusted proxy."""

    def test_xff_honored_ipv4(self):
        request = _make_request("10.0.0.1", xff="203.0.113.5")
        assert get_client_ip(request, ["10.0.0.0/8"]) == "203.0.113.5"

    def test_forwarded_honored_ipv4(self):
        request = _make_request("10.0.0.1", forwarded="for=203.0.113.5")
        assert get_client_ip(request, ["10.0.0.0/8"]) == "203.0.113.5"

    def test_forwarded_honored_ipv6_quoted_brackets(self):
        """RFC 7239 §6: IPv6 MUST be enclosed in brackets and MAY be quoted."""
        request = _make_request("10.0.0.1", forwarded='for="[2001:db8::1]"')
        assert get_client_ip(request, ["10.0.0.0/8"]) == "2001:db8::1"

    def test_forwarded_honored_ipv6_unquoted_brackets(self):
        request = _make_request("10.0.0.1", forwarded="for=[2001:db8::cafe]")
        assert get_client_ip(request, ["10.0.0.0/8"]) == "2001:db8::cafe"

    def test_forwarded_with_ipv4_port_stripped(self):
        """``for=192.0.2.1:4711`` → ``192.0.2.1``."""
        request = _make_request("10.0.0.1", forwarded="for=203.0.113.5:4711")
        assert get_client_ip(request, ["10.0.0.0/8"]) == "203.0.113.5"

    def test_forwarded_with_other_directives(self):
        """Forwarded element may contain proto=/host= alongside for=."""
        request = _make_request(
            "10.0.0.1",
            forwarded="for=203.0.113.5;proto=https;host=example.com",
        )
        assert get_client_ip(request, ["10.0.0.0/8"]) == "203.0.113.5"

    def test_forwarded_preferred_over_xff(self):
        """RFC 7239 Forwarded takes priority over X-Forwarded-For."""
        request = _make_request(
            "10.0.0.1",
            forwarded="for=203.0.113.5",
            xff="1.1.1.1",
        )
        assert get_client_ip(request, ["10.0.0.0/8"]) == "203.0.113.5"

    def test_xff_leftmost_ip_taken(self):
        """With multiple hops in XFF the left-most (original client) is used."""
        request = _make_request("10.0.0.1", xff="203.0.113.5, 10.0.0.2, 10.0.0.3")
        assert get_client_ip(request, ["10.0.0.0/8"]) == "203.0.113.5"

    def test_trusted_by_cidr(self):
        request = _make_request("192.168.10.5", xff="203.0.113.5")
        assert get_client_ip(request, ["192.168.0.0/16"]) == "203.0.113.5"

    def test_trusted_exact_host_cidr(self):
        """A /32 CIDR matches the exact host."""
        request = _make_request("10.0.0.2", xff="203.0.113.5")
        assert get_client_ip(request, ["10.0.0.2/32"]) == "203.0.113.5"


class TestFallbackBehavior:
    """Invalid or oversized headers fall back to the source IP."""

    def test_invalid_xff_falls_back_to_source(self):
        request = _make_request("10.0.0.1", xff="not-an-ip")
        assert get_client_ip(request, ["10.0.0.0/8"]) == "10.0.0.1"

    def test_invalid_forwarded_falls_back_to_xff(self):
        """Bad Forwarded → try XFF instead."""
        request = _make_request("10.0.0.1", forwarded="for=bad-ip", xff="203.0.113.5")
        assert get_client_ip(request, ["10.0.0.0/8"]) == "203.0.113.5"

    def test_invalid_forwarded_and_invalid_xff_falls_back_to_source(self):
        request = _make_request("10.0.0.1", forwarded="for=bad", xff="also-bad")
        assert get_client_ip(request, ["10.0.0.0/8"]) == "10.0.0.1"

    def test_oversized_xff_ignored(self):
        big_xff = ",".join(["1.2.3.4"] * 2100)
        request = _make_request("10.0.0.1", xff=big_xff)
        # Header exceeds _MAX_HEADER_LEN so it should fall back.
        assert get_client_ip(request, ["10.0.0.0/8"]) == "10.0.0.1"

    def test_too_many_xff_hops_ignored(self):
        """More than _MAX_FORWARDED_HOPS entries → return source IP."""
        ips = [f"1.2.3.{i % 256}" for i in range(25)]
        request = _make_request("10.0.0.1", xff=", ".join(ips))
        assert get_client_ip(request, ["10.0.0.0/8"]) == "10.0.0.1"

    def test_forwarded_only_leftmost_element_used(self):
        """Multiple comma-separated elements → only the first is considered."""
        # Second element has the real "for=" but should be ignored.
        request = _make_request(
            "10.0.0.1",
            forwarded="for=203.0.113.5, for=1.1.1.1",
        )
        assert get_client_ip(request, ["10.0.0.0/8"]) == "203.0.113.5"


# ---------------------------------------------------------------------------
# ASGI integration tests – rate-limiter key behaviour
# ---------------------------------------------------------------------------


class TestRateLimiterKeyBehavior:
    """Verify that rate-limit buckets reflect the correct resolved IP."""

    def test_spoof_ignored_when_source_untrusted(self):
        """Attacker sending spoofed XFF from outside trusted CIDRs is keyed
        on their real IP, so changing the spoofed value does not bypass
        the rate limit."""
        limiter = InMemoryRateLimiter(requests_per_minute=1)
        # Attacker's real IP (5.5.5.5) is NOT in 10.0.0.0/8
        app = _build_test_app(limiter, trusted_cidrs=["10.0.0.0/8"], client_ip="5.5.5.5")
        client = TestClient(app)

        r1 = client.get("/test", headers={"x-forwarded-for": "1.1.1.1"})
        assert r1.status_code == 200

        # Different spoofed IP, same real source → still limited
        r2 = client.get("/test", headers={"x-forwarded-for": "2.2.2.2"})
        assert r2.status_code == 429

    def test_xff_honored_when_source_trusted(self):
        """Trusted proxy: the client IP from XFF is used as the rate-limit key.
        Two requests with the same XFF client IP share the same bucket."""
        limiter = InMemoryRateLimiter(requests_per_minute=1)
        # Caddy proxy at 10.0.0.1 IS in 10.0.0.0/8
        app = _build_test_app(limiter, trusted_cidrs=["10.0.0.0/8"], client_ip="10.0.0.1")
        client = TestClient(app)

        r1 = client.get("/test", headers={"x-forwarded-for": "203.0.113.5"})
        assert r1.status_code == 200

        r2 = client.get("/test", headers={"x-forwarded-for": "203.0.113.5"})
        assert r2.status_code == 429

    def test_different_xff_clients_use_separate_buckets(self):
        """Trusted proxy: different client IPs in XFF get independent buckets."""
        limiter = InMemoryRateLimiter(requests_per_minute=1)
        app = _build_test_app(limiter, trusted_cidrs=["10.0.0.0/8"], client_ip="10.0.0.1")
        client = TestClient(app)

        r1 = client.get("/test", headers={"x-forwarded-for": "203.0.113.5"})
        assert r1.status_code == 200

        # Different client IP → different bucket → not rate-limited yet
        r2 = client.get("/test", headers={"x-forwarded-for": "198.51.100.1"})
        assert r2.status_code == 200

    def test_no_trusted_cidrs_always_uses_direct_ip(self):
        """Empty trusted CIDRs: rate-limit always keyed on direct source IP
        regardless of what headers are sent."""
        limiter = InMemoryRateLimiter(requests_per_minute=1)
        # No CIDRs trusted; proxy IP is 10.0.0.1 but still not trusted
        app = _build_test_app(limiter, trusted_cidrs=[], client_ip="10.0.0.1")
        client = TestClient(app)

        r1 = client.get("/test", headers={"x-forwarded-for": "1.1.1.1"})
        assert r1.status_code == 200

        # Same source IP (10.0.0.1), different XFF → same bucket → limited
        r2 = client.get("/test", headers={"x-forwarded-for": "2.2.2.2"})
        assert r2.status_code == 429
