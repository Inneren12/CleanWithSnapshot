import base64
import datetime as dt

import pytest
from sqlalchemy import select

from app.domain.bookings.db_models import AvailabilityBlock, Booking
from app.domain.bookings.service import ensure_default_team
from app.domain.org_settings import service as org_settings_service
from app.domain.training import service as training_service
from app.domain.workers.db_models import Worker
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def _set_admin_creds():
    original = {
        "owner_basic_username": settings.owner_basic_username,
        "owner_basic_password": settings.owner_basic_password,
    }
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    yield
    for key, value in original.items():
        setattr(settings, key, value)


@pytest.mark.anyio
async def test_training_session_creates_availability_blocks(client, async_session_maker):
    start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=2)
    end = start + dt.timedelta(hours=2)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        worker = Worker(name="Session Worker", phone="+1555", team_id=team.team_id, is_active=True)
        session.add(worker)
        await session.commit()

    payload = {
        "title": "Onboarding training",
        "starts_at": start.isoformat(),
        "ends_at": end.isoformat(),
        "location": "HQ",
        "worker_ids": [worker.worker_id],
    }
    response = client.post(
        "/v1/admin/training/sessions",
        headers=_basic_auth("owner", "secret"),
        json=payload,
    )
    assert response.status_code == 200

    async with async_session_maker() as session:
        blocks = (
            await session.execute(
                select(AvailabilityBlock).where(
                    AvailabilityBlock.org_id == team.org_id,
                    AvailabilityBlock.scope_type == "worker",
                    AvailabilityBlock.scope_id == worker.worker_id,
                    AvailabilityBlock.block_type == "training",
                )
            )
        ).scalars().all()
        assert len(blocks) == 1
        assert "Onboarding training" in (blocks[0].reason or "")


@pytest.mark.anyio
async def test_training_block_rejects_booking_assignment(client, async_session_maker):
    start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=3)
    end = start + dt.timedelta(hours=2)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        worker = Worker(name="Blocked Worker", phone="+1556", team_id=team.team_id, is_active=True)
        booking = Booking(team_id=team.team_id, starts_at=start, duration_minutes=90, status="PENDING")
        session.add_all([worker, booking])
        await session.commit()

    payload = {
        "title": "Safety training",
        "starts_at": start.isoformat(),
        "ends_at": end.isoformat(),
        "worker_ids": [worker.worker_id],
    }
    create_response = client.post(
        "/v1/admin/training/sessions",
        headers=_basic_auth("owner", "secret"),
        json=payload,
    )
    assert create_response.status_code == 200

    response = client.patch(
        f"/v1/admin/bookings/{booking.booking_id}",
        headers=_basic_auth("owner", "secret"),
        json={"worker_id": worker.worker_id},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["message"] == "conflict_with_existing_booking"


@pytest.mark.anyio
async def test_training_sessions_list_uses_org_timezone(client, async_session_maker):
    start = dt.datetime(2026, 1, 2, 2, 0, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(hours=1)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        worker = Worker(name="TZ Worker", phone="+1557", team_id=team.team_id, is_active=True)
        session.add(worker)
        org_settings = await org_settings_service.get_or_create_org_settings(session, team.org_id)
        org_settings.timezone = "America/New_York"
        await session.commit()
        await training_service.create_training_session(
            session,
            org_id=team.org_id,
            title="Timezone training",
            starts_at=start,
            ends_at=end,
            location=None,
            instructor_user_id=None,
            notes=None,
            worker_ids=[worker.worker_id],
            created_by="owner",
        )
        await session.commit()

    response = client.get(
        "/v1/admin/training/sessions",
        headers=_basic_auth("owner", "secret"),
        params={"from": "2026-01-01", "to": "2026-01-01"},
    )
    assert response.status_code == 200
    payload = response.json()
    session_ids = {item["session_id"] for item in payload["items"]}
    assert len(session_ids) == 1
