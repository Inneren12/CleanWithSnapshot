import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.leads.db_models import Lead
from app.domain.workers.db_models import Worker
from app.domain.bookings.service import LOCAL_TZ
from app.settings import settings


def test_admin_leads_requires_auth(anon_client_no_raise, admin_client):
    response = anon_client_no_raise.get("/v1/admin/leads")
    assert response.status_code == 401

    authorized = admin_client.get("/v1/admin/leads")
    assert authorized.status_code == 200
    payload = authorized.json()
    assert isinstance(payload, dict)
    assert "items" in payload


def test_admin_cleanup_removes_old_pending_bookings(admin_client, async_session_maker):
    async def _seed() -> None:
        from datetime import datetime, timedelta, timezone

        from app.domain.bookings.db_models import Booking

        async with async_session_maker() as session:
            old_booking = Booking(
                team_id=1,
                starts_at=datetime.now(tz=timezone.utc) - timedelta(days=1),
                duration_minutes=60,
                status="PENDING",
                created_at=datetime.now(tz=timezone.utc) - timedelta(hours=2),
            )
            fresh_booking = Booking(
                team_id=1,
                starts_at=datetime.now(tz=timezone.utc) + timedelta(hours=2),
                duration_minutes=60,
                status="PENDING",
                created_at=datetime.now(tz=timezone.utc),
            )
            session.add_all([old_booking, fresh_booking])
            await session.commit()

    import asyncio

    asyncio.run(_seed())

    response = admin_client.post("/v1/admin/cleanup")
    assert response.status_code == 202
    assert response.json()["deleted"] == 1


def test_admin_auth_missing_config_returns_401(anon_client_no_raise):
    response = anon_client_no_raise.get("/v1/admin/leads")
    assert response.status_code == 401


def _create_lead(client) -> str:
    estimate_response = client.post(
        "/v1/estimate",
        json={
            "beds": 1,
            "baths": 1,
            "cleaning_type": "standard",
            "heavy_grease": False,
            "multi_floor": False,
            "frequency": "one_time",
            "add_ons": {},
        },
    )
    assert estimate_response.status_code == 200
    payload = {
        "name": "Admin Test",
        "phone": "780-555-0101",
        "address": "100 Admin Road",
        "preferred_dates": ["Tue afternoon"],
        "structured_inputs": {"beds": 1, "baths": 1, "cleaning_type": "standard"},
        "estimate_snapshot": estimate_response.json(),
    }
    lead_response = client.post("/v1/leads", json=payload)
    assert lead_response.status_code == 201
    return lead_response.json()["lead_id"]


def _create_booking(client, lead_id: str | None = None, days_ahead: int = 1) -> str:
    starts_at_local = (
        datetime.now(tz=LOCAL_TZ)
        .replace(hour=10, minute=0, second=0, microsecond=0)
        + timedelta(days=days_ahead)
    )
    if starts_at_local.weekday() >= 5:
        starts_at_local += timedelta(days=(7 - starts_at_local.weekday()))
    payload = {
        "starts_at": starts_at_local.astimezone(timezone.utc).isoformat(),
        "time_on_site_hours": 1,
        "lead_id": lead_id,
    }
    response = client.post("/v1/bookings", json=payload)
    assert response.status_code == 201
    return response.json()["booking_id"]


def test_admin_updates_lead_status_with_valid_transition(admin_client, async_session_maker):
    lead_id = _create_lead(admin_client)

    transition = admin_client.patch(
        f"/v1/admin/leads/{lead_id}",
        json={"status": "CONTACTED"},
    )
    assert transition.status_code == 200
    assert transition.json()["status"] == "CONTACTED"

    filtered = admin_client.get("/v1/admin/leads", params={"status": "CONTACTED"})
    assert filtered.status_code == 200
    assert any(lead["lead_id"] == lead_id for lead in filtered.json()["items"])

    async def _fetch_status() -> str:
        async with async_session_maker() as session:
            lead = await session.get(Lead, lead_id)
            assert lead
            return lead.status

    assert asyncio.run(_fetch_status()) == "CONTACTED"

    invalid = admin_client.patch(
        f"/v1/admin/leads/{lead_id}",
        json={"status": "NEW"},
    )
    assert invalid.status_code == 400


def test_viewer_cannot_update_leads(admin_client, viewer_client):
    lead_id = _create_lead(admin_client)

    list_response = viewer_client.get("/v1/admin/leads")
    assert list_response.status_code == 200

    update = viewer_client.patch(
        f"/v1/admin/leads/{lead_id}",
        json={"status": "CONTACTED"},
    )
    assert update.status_code == 403


def test_dispatcher_can_manage_bookings_but_not_pricing(
    admin_client, dispatcher_client, async_session_maker
):
    original_stripe_key = settings.stripe_secret_key
    settings.stripe_secret_key = "sk_test_key"
    original_deposit_percent = settings.deposit_percent
    settings.deposit_percent = 0

    try:
        lead_id = _create_lead(admin_client)
        booking_id = _create_booking(admin_client, lead_id=lead_id)

        leads_response = dispatcher_client.get("/v1/admin/leads")
        assert leads_response.status_code == 200

        update = dispatcher_client.patch(
            f"/v1/admin/leads/{lead_id}",
            json={"status": "CONTACTED"},
        )
        assert update.status_code == 200

        confirm = dispatcher_client.post(f"/v1/admin/bookings/{booking_id}/confirm")
        assert confirm.status_code == 200
        assert confirm.json()["status"] == "CONFIRMED"

        reschedule_payload = {
            "starts_at": (
                datetime.now(tz=LOCAL_TZ)
                .replace(hour=11, minute=0, second=0, microsecond=0)
                .astimezone(timezone.utc)
                .isoformat()
            ),
            "time_on_site_hours": 1.5,
        }
        reschedule = dispatcher_client.post(
            f"/v1/admin/bookings/{booking_id}/reschedule", json=reschedule_payload
        )
        assert reschedule.status_code == 200

        cancel = dispatcher_client.post(f"/v1/admin/bookings/{booking_id}/cancel")
        assert cancel.status_code == 200
        assert cancel.json()["status"] == "CANCELLED"

        pricing_attempt = dispatcher_client.post("/v1/admin/pricing/reload")
        assert pricing_attempt.status_code == 403

        admin_pricing = admin_client.post("/v1/admin/pricing/reload")
        assert admin_pricing.status_code == 202
    finally:
        settings.stripe_secret_key = original_stripe_key
        settings.deposit_percent = original_deposit_percent


def test_dispatcher_reassign_and_reschedule_validation(
    dispatcher_client, async_session_maker
):
    async def _seed_data() -> tuple[str, int]:
        async with async_session_maker() as session:
            from app.domain.bookings.db_models import Booking

            booking = Booking(
                team_id=1,
                starts_at=datetime.now(tz=timezone.utc) + timedelta(days=1),
                duration_minutes=60,
                status="PLANNED",
            )
            worker = Worker(team_id=1, name="Dispatch Worker", phone="780-555-0102")
            session.add_all([booking, worker])
            await session.commit()
            await session.refresh(booking)
            await session.refresh(worker)
            return booking.booking_id, worker.worker_id

    booking_id, worker_id = asyncio.run(_seed_data())
    response = dispatcher_client.post(
        f"/v1/admin/dispatcher/bookings/{booking_id}/reassign",
        json={"worker_id": worker_id},
    )
    assert response.status_code == 200
    assert response.json()["assigned_worker"]["id"] == worker_id

    invalid_worker = dispatcher_client.post(
        f"/v1/admin/dispatcher/bookings/{booking_id}/reassign",
        json={"worker_id": 99999},
    )
    assert invalid_worker.status_code == 404

    invalid_reschedule = dispatcher_client.post(
        f"/v1/admin/dispatcher/bookings/{booking_id}/reschedule",
        json={
            "starts_at": datetime.now(tz=timezone.utc).isoformat(),
            "ends_at": datetime.now(tz=timezone.utc).isoformat(),
        },
    )
    assert invalid_reschedule.status_code == 422
