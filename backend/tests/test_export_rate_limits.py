from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.domain.clients.service import issue_magic_token
from app.domain.data_rights.db_models import DataExportRequest
from app.main import app
from app.settings import settings


def _make_client_token(*, org_id: uuid.UUID, client_id: str, email: str) -> str:
    return issue_magic_token(
        email=email,
        client_id=client_id,
        secret=settings.client_portal_secret,
        ttl_minutes=settings.client_portal_token_ttl_minutes,
        org_id=org_id,
    )


def _reset_export_limiters() -> None:
    if hasattr(app.state, "data_export_rate_limiters"):
        app.state.data_export_rate_limiters = {}


@pytest.mark.anyio
async def test_export_request_rate_limit_enforced(client, async_session_maker):
    org_id = uuid.uuid4()
    client_id = "client-rate-limit"
    token = _make_client_token(
        org_id=org_id,
        client_id=client_id,
        email="rate-limit@example.com",
    )
    client.cookies.set("client_session", token)

    settings.data_export_request_rate_limit_per_minute = 1
    settings.data_export_request_rate_limit_per_hour = 1
    settings.data_export_cooldown_minutes = 0
    _reset_export_limiters()

    first = client.post("/v1/data-rights/export-request")
    assert first.status_code == 200

    second = client.post("/v1/data-rights/export-request")
    assert second.status_code == 429
    assert second.headers.get("Retry-After")
    payload = second.json()
    assert any(error.get("code") == "DATA_EXPORT_RATE_LIMITED" for error in payload.get("errors", []))


@pytest.mark.anyio
async def test_export_request_cooldown_returns_existing(client, async_session_maker):
    org_id = uuid.uuid4()
    client_id = "client-cooldown"
    token = _make_client_token(
        org_id=org_id,
        client_id=client_id,
        email="cooldown@example.com",
    )
    client.cookies.set("client_session", token)

    settings.data_export_request_rate_limit_per_minute = 100
    settings.data_export_request_rate_limit_per_hour = 1000
    settings.data_export_cooldown_minutes = 60
    _reset_export_limiters()

    first = client.post("/v1/data-rights/export-request")
    assert first.status_code == 200
    first_id = first.json()["export_id"]

    second = client.post("/v1/data-rights/export-request")
    assert second.status_code == 200
    assert second.json()["export_id"] == first_id

    async with async_session_maker() as session:
        result = await session.execute(
            select(DataExportRequest).where(DataExportRequest.org_id == org_id)
        )
        exports = list(result.scalars().all())
        assert len(exports) == 1


@pytest.mark.anyio
async def test_download_denied_throttled_after_failures(client, async_session_maker):
    org_id = uuid.uuid4()
    export = DataExportRequest(
        org_id=org_id,
        subject_id="subject-allowed",
        subject_type="client",
        subject_email="subject@example.com",
        status="completed",
        storage_key="data-exports/test.json",
        content_type="application/json",
        size_bytes=12,
        completed_at=datetime.now(timezone.utc),
    )
    async with async_session_maker() as session:
        session.add(export)
        await session.commit()
        await session.refresh(export)

    token = _make_client_token(
        org_id=org_id,
        client_id="client-other",
        email="other@example.com",
    )
    client.cookies.set("client_session", token)

    settings.data_export_download_rate_limit_per_minute = 100
    settings.data_export_download_failure_limit_per_window = 1
    settings.data_export_download_lockout_limit_per_window = 5
    settings.data_export_download_failure_window_seconds = 60
    settings.data_export_download_lockout_window_seconds = 600
    _reset_export_limiters()

    first = client.get(f"/v1/data-rights/exports/{export.export_id}/download")
    assert first.status_code == 403

    second = client.get(f"/v1/data-rights/exports/{export.export_id}/download")
    assert second.status_code == 429
    assert second.headers.get("Retry-After")
