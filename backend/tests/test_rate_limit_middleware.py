from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infra.security import InMemoryRateLimiter
from app.main import RateLimitMiddleware


class TestSettings:
    trust_proxy_headers = False
    trusted_proxy_ips: list[str] = []
    trusted_proxy_cidrs: list[str] = []
    rate_limit_per_minute = 1


def _build_app(limiter: InMemoryRateLimiter) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter, app_settings=TestSettings)

    @app.get("/limited")
    def limited_route():
        return {"ok": True}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


def test_rate_limit_skips_options_requests():
    limiter = InMemoryRateLimiter(requests_per_minute=1)
    app = _build_app(limiter)
    client = TestClient(app)

    first = client.options("/limited")
    second = client.options("/limited")

    assert first.status_code != 429
    assert second.status_code != 429


def test_rate_limit_skips_health_endpoints():
    limiter = InMemoryRateLimiter(requests_per_minute=1)
    app = _build_app(limiter)
    client = TestClient(app)

    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz").status_code == 200


def test_rate_limit_blocks_after_limit():
    limiter = InMemoryRateLimiter(requests_per_minute=1)
    app = _build_app(limiter)
    client = TestClient(app)

    assert client.get("/limited").status_code == 200
    assert client.get("/limited").status_code == 429
