from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.api.break_glass import BREAK_GLASS_HEADER
from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.break_glass.db_models import BreakGlassSession
from app.infra.metrics import configure_metrics
from app.settings import settings


@pytest.mark.anyio
async def test_break_glass_start_requires_reason_and_audits(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"

    response = client.post(
        "/v1/admin/break-glass/start",
        json={"reason": "incident start", "incident_ref": "INC-100", "ttl_minutes": 15},
        auth=("owner", "secret"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token"]
    assert payload["expires_at"]
    assert payload["session_id"]

    async with async_session_maker() as session:
        result = await session.execute(
            sa.select(AdminAuditLog)
            .where(AdminAuditLog.action == "break_glass_grant_created")
            .order_by(AdminAuditLog.created_at.desc())
        )
        log = result.scalars().first()
        assert log is not None
        assert log.after.get("reason") == "incident start"
        assert log.after.get("incident_ref") == "INC-100"


@pytest.mark.anyio
async def test_break_glass_token_expires(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.admin_read_only = True

    start = client.post(
        "/v1/admin/break-glass/start",
        json={"reason": "expire", "incident_ref": "INC-200", "ttl_minutes": 1},
        auth=("owner", "secret"),
    )
    token = start.json()["token"]

    async with async_session_maker() as session:
        await session.execute(
            sa.update(BreakGlassSession).values(
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
            )
        )
        await session.commit()

    response = client.post(
        "/v1/admin/pricing/reload",
        auth=("owner", "secret"),
        headers={BREAK_GLASS_HEADER: token},
    )

    assert response.status_code == 409
    async with async_session_maker() as session:
        status = await session.scalar(sa.select(BreakGlassSession.status))
        assert status == "expired"
        audit = await session.execute(
            sa.select(AdminAuditLog)
            .where(AdminAuditLog.action == "break_glass_expired")
            .order_by(AdminAuditLog.created_at.desc())
        )
        assert audit.scalars().first() is not None


@pytest.mark.anyio
async def test_read_only_allows_break_glass_write(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.admin_read_only = True

    start = client.post(
        "/v1/admin/break-glass/start",
        json={"reason": "allow write", "incident_ref": "INC-300"},
        auth=("owner", "secret"),
    )
    token = start.json()["token"]

    denied = client.post("/v1/admin/pricing/reload", auth=("owner", "secret"))
    assert denied.status_code == 409

    allowed = client.post(
        "/v1/admin/pricing/reload",
        auth=("owner", "secret"),
        headers={BREAK_GLASS_HEADER: token},
    )
    assert allowed.status_code == 202

    async with async_session_maker() as session:
        result = await session.execute(
            sa.select(AdminAuditLog)
            .where(AdminAuditLog.action == "break_glass_use")
            .order_by(AdminAuditLog.created_at.desc())
        )
        log = result.scalars().first()
        assert log is not None
        assert log.after.get("reason") == "allow write"
        assert log.after.get("incident_ref") == "INC-300"


@pytest.mark.anyio
async def test_break_glass_ttl_is_capped(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.break_glass_max_ttl_minutes = 60
    settings.break_glass_default_ttl_minutes = 30

    response = client.post(
        "/v1/admin/break-glass/start",
        json={"reason": "ttl cap", "incident_ref": "INC-400", "ttl_minutes": 120},
        auth=("owner", "secret"),
    )
    assert response.status_code == 200
    expires_at = datetime.fromisoformat(response.json()["expires_at"])
    assert expires_at <= datetime.now(timezone.utc) + timedelta(minutes=60, seconds=5)


@pytest.mark.anyio
async def test_break_glass_metrics_emitted(client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.metrics_enabled = True
    app_metrics = configure_metrics(True, service_name=settings.app_name)

    response = client.post(
        "/v1/admin/break-glass/start",
        json={"reason": "metrics", "incident_ref": "INC-500"},
        auth=("owner", "secret"),
    )
    assert response.status_code == 200

    collected = list(app_metrics.break_glass_grants_total.collect())
    assert collected


@pytest.mark.anyio
async def test_break_glass_review_requires_closure(async_session_maker, client):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"

    start = client.post(
        "/v1/admin/break-glass/start",
        json={"reason": "review flow", "incident_ref": "INC-600"},
        auth=("owner", "secret"),
    )
    session_id = start.json()["session_id"]

    active_review = client.post(
        f"/v1/admin/break-glass/{session_id}/review",
        json={"review_notes": "premature"},
        auth=("owner", "secret"),
    )
    assert active_review.status_code == 409

    revoke = client.post(
        f"/v1/admin/break-glass/{session_id}/revoke",
        json={"reason": "resolved"},
        auth=("owner", "secret"),
    )
    assert revoke.status_code == 200

    review = client.post(
        f"/v1/admin/break-glass/{session_id}/review",
        json={"review_notes": "reviewed and closed"},
        auth=("owner", "secret"),
    )
    assert review.status_code == 200

    async with async_session_maker() as session:
        record = await session.get(BreakGlassSession, session_id)
        assert record.review_notes == "reviewed and closed"
