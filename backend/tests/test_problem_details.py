import asyncio

from app.main import app
from app.settings import settings


def test_rate_limit_returns_problem_details(client):
    limiter = app.state.rate_limiter
    previous_limit = limiter.requests_per_minute
    previous_disable_exempt = settings.rate_limit_disable_exempt_paths
    asyncio.run(limiter.reset())
    limiter.requests_per_minute = 1
    settings.rate_limit_disable_exempt_paths = True
    try:
        first = client.get("/healthz")
        assert first.status_code == 200
        second = client.get("/healthz")
        assert second.status_code == 429
        body = second.json()
        assert body["title"] == "Too Many Requests"
        assert body["type"].endswith("rate-limit")
        assert body["request_id"]
    finally:
        limiter.requests_per_minute = previous_limit
        settings.rate_limit_disable_exempt_paths = previous_disable_exempt
        asyncio.run(limiter.reset())
