import base64
import datetime as dt

import pytest

from app.domain.bookings.db_models import AvailabilityBlock, Booking
from app.domain.bookings.service import ensure_default_team
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
        "dispatcher_basic_username": settings.dispatcher_basic_username,
        "dispatcher_basic_password": settings.dispatcher_basic_password,
    }
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.dispatcher_basic_username = "dispatch"
    settings.dispatcher_basic_password = "secret"
    yield
    for key, value in original.items():
        setattr(settings, key, value)


@pytest.mark.anyio
async def test_assignment_rejected_for_blocked_worker(client, async_session_maker):
    start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=2)
    end = start + dt.timedelta(hours=2)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        worker = Worker(name="Blocked Worker", phone="+1 555", team_id=team.team_id, is_active=True)
        booking = Booking(team_id=team.team_id, starts_at=start, duration_minutes=90, status="PENDING")
        session.add_all([worker, booking])
        await session.flush()
        session.add(
            AvailabilityBlock(
                org_id=team.org_id,
                scope_type="worker",
                scope_id=worker.worker_id,
                block_type="vacation",
                starts_at=start - dt.timedelta(minutes=30),
                ends_at=end,
                reason="Time off",
            )
        )
        await session.commit()

    headers = _basic_auth("owner", "secret")
    response = client.patch(
        f"/v1/admin/bookings/{booking.booking_id}",
        headers=headers,
        json={"worker_id": worker.worker_id},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["message"] == "conflict_with_existing_booking"


@pytest.mark.anyio
async def test_holiday_block_applies_to_all_workers(client, async_session_maker):
    start = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=3)
    end = start + dt.timedelta(hours=4)
    async with async_session_maker() as session:
        team = await ensure_default_team(session)
        session.add(
            AvailabilityBlock(
                org_id=team.org_id,
                scope_type="org",
                scope_id=None,
                block_type="holiday",
                starts_at=start,
                ends_at=end,
                reason="Company holiday",
            )
        )
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    params = {
        "starts_at": start.isoformat(),
        "ends_at": end.isoformat(),
        "team_id": team.team_id,
    }
    resp = client.get("/v1/admin/schedule/conflicts", headers=headers, params=params)
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_conflict"] is True
    kinds = {item["kind"] for item in body["conflicts"]}
    assert "availability_block" in kinds


@pytest.mark.anyio
async def test_availability_block_requires_manage_permission(client):
    headers = _basic_auth("dispatch", "secret")
    payload = {
        "scope_type": "org",
        "scope_id": None,
        "block_type": "holiday",
        "starts_at": (dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=1)).isoformat(),
        "ends_at": (dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(days=1, hours=2)).isoformat(),
        "reason": "Stat holiday",
    }
    forbidden = client.post("/v1/admin/availability-blocks", headers=headers, json=payload)
    assert forbidden.status_code == 403

    owner_headers = _basic_auth("owner", "secret")
    created = client.post("/v1/admin/availability-blocks", headers=owner_headers, json=payload)
    assert created.status_code == 200
