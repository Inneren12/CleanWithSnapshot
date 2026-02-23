import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import anyio
import httpx
import pytest

from app.domain.bookings import service as booking_service
from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import (
    BUFFER_MINUTES,
    SLOT_STEP_MINUTES,
    generate_slots,
    round_duration_minutes,
)
from app.domain.clients import service as client_service
from app.main import app
from app.settings import settings


def _authenticate_client(client, async_session_maker, email: str = "client@example.com") -> None:
    async def _issue_token() -> str:
        async with async_session_maker() as session:
            user = await client_service.get_or_create_client(session, email, commit=True)
            return client_service.issue_magic_token(
                email=user.email,
                client_id=user.client_id,
                secret=settings.client_portal_secret,
                ttl_minutes=settings.client_portal_token_ttl_minutes,
            )

    token = asyncio.run(_issue_token())
    client.cookies.set("client_session", token)


async def _insert_booking(session, starts_at: datetime, duration_minutes: int, status: str = "CONFIRMED") -> Booking:
    booking = Booking(
        team_id=1,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        status=status,
    )
    session.add(booking)
    await session.commit()
    await session.refresh(booking)
    return booking


def _parse_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    return datetime.fromisoformat(value)


def test_slots_skip_booked_ranges(async_session_maker):
    async def _run() -> None:
        async with async_session_maker() as session:
            start_local = datetime(2025, 1, 1, 9, 0, tzinfo=ZoneInfo("America/Edmonton"))
            start_utc = start_local.astimezone(timezone.utc)
            await _insert_booking(session, start_utc, 60, status="CONFIRMED")
            slots = await generate_slots(date(2025, 1, 1), 60, session)
            assert start_utc not in slots
            expected_first_open = start_utc + timedelta(minutes=60 + BUFFER_MINUTES)
            assert expected_first_open in slots

    asyncio.run(_run())


def test_slots_block_spanning_booking(async_session_maker):
    async def _run() -> None:
        async with async_session_maker() as session:
            target_date = date(2025, 1, 2)
            start_local = datetime(2025, 1, 1, 18, 0, tzinfo=ZoneInfo("America/Edmonton"))
            start_utc = start_local.astimezone(timezone.utc)
            await _insert_booking(session, start_utc, 16 * 60, status="CONFIRMED")

            slots = await generate_slots(target_date, 60, session)
            day_start_local = datetime(2025, 1, 2, 9, 0, tzinfo=ZoneInfo("America/Edmonton"))
            day_start_utc = day_start_local.astimezone(timezone.utc)
            assert day_start_utc not in slots

    asyncio.run(_run())


def test_generate_slots_with_fixed_datetime(async_session_maker, monkeypatch):
    fixed_now = datetime(2026, 1, 15, 15, 30, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz:
                return fixed_now.astimezone(tz)
            return fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(booking_service, "datetime", FixedDateTime)

    async def _run() -> None:
        async with async_session_maker() as session:
            target_date = date(2026, 1, 15)
            start_local = datetime(2026, 1, 15, 9, 0, tzinfo=ZoneInfo("America/Edmonton"))
            start_utc = start_local.astimezone(timezone.utc)
            await _insert_booking(session, start_utc, 60, status="CONFIRMED")
            slots = await generate_slots(target_date, 60, session)
            assert start_utc not in slots

    asyncio.run(_run())


def test_client_booking_api_blocks_slot(client, async_session_maker):
    start = datetime(2025, 1, 1, 9, 0, tzinfo=ZoneInfo("America/Edmonton"))
    end = start + timedelta(hours=8)

    _authenticate_client(client, async_session_maker)

    response = client.get(
        "/v1/client/slots",
        params={"from": start.isoformat(), "to": end.isoformat(), "duration_minutes": 120},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["slots"], "expected at least one slot"
    chosen_slot = data["slots"][0]

    create_resp = client.post(
        "/v1/client/bookings",
        json={"starts_at": chosen_slot, "duration_minutes": 120},
    )
    assert create_resp.status_code == 201

    follow_up = client.get(
        "/v1/client/slots",
        params={"from": start.isoformat(), "to": end.isoformat(), "duration_minutes": 120},
    )
    assert follow_up.status_code == 200
    next_slots = follow_up.json()["slots"]
    assert chosen_slot not in next_slots


def test_client_reschedule(client, async_session_maker):
    start = datetime(2025, 1, 1, 9, 0, tzinfo=ZoneInfo("America/Edmonton"))
    end = start + timedelta(hours=8)
    _authenticate_client(client, async_session_maker)
    slots_resp = client.get(
        "/v1/client/slots",
        params={"from": start.isoformat(), "to": end.isoformat(), "duration_minutes": 90},
    )
    assert slots_resp.status_code == 200
    slots = slots_resp.json()["slots"]
    assert len(slots) >= 2
    initial_slot, target_slot = slots[:2]

    booking_resp = client.post(
        "/v1/client/bookings",
        json={"starts_at": initial_slot, "duration_minutes": 90},
    )
    assert booking_resp.status_code == 201
    booking_id = booking_resp.json()["booking_id"]

    reschedule_resp = client.post(
        f"/v1/client/bookings/{booking_id}/reschedule",
        json={"starts_at": target_slot, "duration_minutes": 90},
    )
    assert reschedule_resp.status_code == 200
    assert _parse_datetime(reschedule_resp.json()["starts_at"]) == _parse_datetime(target_slot)


def test_client_cannot_modify_other_booking(client, async_session_maker):
    start = datetime(2025, 1, 1, 9, 0, tzinfo=ZoneInfo("America/Edmonton"))
    end = start + timedelta(hours=8)

    _authenticate_client(client, async_session_maker, email="owner@example.com")
    slots_resp = client.get(
        "/v1/client/slots",
        params={"from": start.isoformat(), "to": end.isoformat(), "duration_minutes": 60},
    )
    assert slots_resp.status_code == 200
    slots = slots_resp.json()["slots"]
    assert len(slots) >= 2
    initial_slot, target_slot = slots[:2]

    booking_resp = client.post(
        "/v1/client/bookings",
        json={"starts_at": initial_slot, "duration_minutes": 60},
    )
    assert booking_resp.status_code == 201
    booking_id = booking_resp.json()["booking_id"]

    _authenticate_client(client, async_session_maker, email="other@example.com")

    reschedule_resp = client.post(
        f"/v1/client/bookings/{booking_id}/reschedule",
        json={"starts_at": target_slot, "duration_minutes": 60},
    )
    assert reschedule_resp.status_code == 404

    cancel_resp = client.post(f"/v1/client/bookings/{booking_id}/cancel")
    assert cancel_resp.status_code == 404


def test_round_duration_minutes_uses_slot_step():
    assert round_duration_minutes(1.1) == SLOT_STEP_MINUTES * 3  # 66 minutes => 90 rounded
    assert round_duration_minutes(0.1) == SLOT_STEP_MINUTES
    assert round_duration_minutes(2.5) == SLOT_STEP_MINUTES * 5


@pytest.mark.anyio
async def test_booking_endpoint_prevents_double_booking_under_concurrency(monkeypatch):
    monkeypatch.setattr(settings, "captcha_enabled", False)
    monkeypatch.setattr(settings, "deposits_enabled", False)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        slots_response = await async_client.get(
            "/v1/slots",
            params={"date": "2035-01-02", "time_on_site_hours": 2},
        )
        assert slots_response.status_code == 200
        chosen_slot = slots_response.json()["slots"][0]

        statuses: list[int] = []
        start = anyio.Event()

        async def attempt_booking() -> None:
            await start.wait()
            await anyio.sleep(0)
            response = await async_client.post(
                "/v1/bookings",
                json={"starts_at": chosen_slot, "time_on_site_hours": 2},
            )
            statuses.append(response.status_code)

        async with anyio.create_task_group() as tg:
            for _ in range(5):
                tg.start_soon(attempt_booking)
            start.set()

    assert statuses.count(201) == 1
    assert statuses.count(409) == 4
