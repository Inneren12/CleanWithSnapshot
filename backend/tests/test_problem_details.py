import asyncio
import json

from starlette.requests import Request

from app.api.problem_details import PROBLEM_TYPE_DOMAIN, PROBLEM_TYPE_VALIDATION, problem_details
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


def _build_request() -> Request:
    scope = {"type": "http", "headers": [], "path": "/test", "method": "GET"}
    return Request(scope)


def test_problem_details_422_maps_to_validation_type():
    request = _build_request()
    response = problem_details(
        request=request,
        status=422,
        title=None,
        detail="Validation failed",
    )
    payload = json.loads(response.body)
    assert payload["type"] == PROBLEM_TYPE_VALIDATION
    assert payload["status"] == 422
    assert payload["request_id"]


def test_problem_details_non_422_maps_to_domain_type():
    request = _build_request()
    response = problem_details(
        request=request,
        status=400,
        title=None,
        detail="Bad request",
    )
    payload = json.loads(response.body)
    assert payload["type"] == PROBLEM_TYPE_DOMAIN
    assert payload["status"] == 400
