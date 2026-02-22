from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import LOCAL_TZ
from app.domain.leads.db_models import Lead
from app.settings import settings


pytestmark = pytest.mark.anyio


def _future_slot() -> str:
    now = datetime.now(tz=LOCAL_TZ)
    tomorrow = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    return tomorrow.astimezone(timezone.utc).isoformat()


async def _seed_lead_with_estimate(async_session_maker) -> str:
    async with async_session_maker() as session:
        lead = Lead(
            name="Jane Doe",
            phone="780-555-0001",
            address="99 Test Street",
            email="jane@example.com",
            preferred_dates=["Mon morning"],
            structured_inputs={"beds": 2, "baths": 1, "cleaning_type": "standard"},
            estimate_snapshot={
                "pricing_config_version": "v1",
                "config_hash": "testhash",
                "total_before_tax": 150.0,
            },
            pricing_config_version="v1",
            config_hash="testhash",
            status="NEW",
            org_id=settings.default_org_id,
        )
        session.add(lead)
        await session.commit()
        return lead.lead_id


async def _get_booking(async_session_maker, booking_id: str) -> Booking | None:
    async with async_session_maker() as session:
        return await session.get(Booking, booking_id)


async def _booking_exists_with_checkout(async_session_maker, session_id: str) -> bool:
    async with async_session_maker() as session:
        row = await session.scalar(
            select(Booking).where(Booking.stripe_checkout_session_id == session_id)
        )
        return row is not None


def _stripe_method_dispatch(create_mock: AsyncMock, cancel_mock: AsyncMock, *, in_txn_ref: dict[str, bool] | None = None):
    async def _call(_client, method_name: str, /, *args, **kwargs):
        if method_name == "create_checkout_session":
            if in_txn_ref is not None:
                assert in_txn_ref["value"] is False
            return await create_mock(*args, **kwargs)
        if method_name == "cancel_checkout_session":
            return await cancel_mock(*args, **kwargs)
        raise AssertionError(f"Unexpected stripe method: {method_name}")

    return _call


def _set_payment_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_boundaries")
    monkeypatch.setattr(settings, "deposits_enabled", True)
    monkeypatch.setattr(settings, "stripe_success_url", "https://example.com/success?booking={BOOKING_ID}")
    monkeypatch.setattr(settings, "stripe_cancel_url", "https://example.com/cancel?booking={BOOKING_ID}")
    monkeypatch.setattr(settings, "deposit_currency", "cad")


async def test_happy_path_stripe_and_db_succeed(client, async_session_maker, monkeypatch):
    _set_payment_settings(monkeypatch)
    lead_id = await _seed_lead_with_estimate(async_session_maker)

    checkout_session = SimpleNamespace(
        id="cs_test_happy",
        url="https://stripe.test/checkout/happy",
        payment_intent="pi_test_happy",
    )
    create_mock = AsyncMock(return_value=checkout_session)
    cancel_mock = AsyncMock()
    in_txn = {"value": False}

    from app.api import routes_bookings

    original_create_booking = routes_bookings.booking_service.create_booking

    async def _wrapped_create_booking(*args, **kwargs):
        in_txn["value"] = True
        try:
            return await original_create_booking(*args, **kwargs)
        finally:
            in_txn["value"] = False

    monkeypatch.setattr(
        "app.api.routes_bookings.booking_service.create_booking",
        _wrapped_create_booking,
    )
    monkeypatch.setattr(
        "app.api.routes_bookings.stripe_infra.call_stripe_client_method",
        _stripe_method_dispatch(create_mock, cancel_mock, in_txn_ref=in_txn),
    )

    response = client.post(
        "/v1/bookings",
        json={"starts_at": _future_slot(), "time_on_site_hours": 2.0, "lead_id": lead_id},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["checkout_url"] == "https://stripe.test/checkout/happy"
    assert payload["deposit_required"] is True

    booking = await _get_booking(async_session_maker, payload["booking_id"])
    assert booking is not None
    assert booking.stripe_checkout_session_id == "cs_test_happy"
    assert booking.stripe_payment_intent_id == "pi_test_happy"
    cancel_mock.assert_not_called()


async def test_stripe_create_fails_booking_created_without_deposit(client, async_session_maker, monkeypatch):
    _set_payment_settings(monkeypatch)
    lead_id = await _seed_lead_with_estimate(async_session_maker)

    create_mock = AsyncMock(side_effect=RuntimeError("stripe create failed"))
    cancel_mock = AsyncMock()
    monkeypatch.setattr(
        "app.api.routes_bookings.stripe_infra.call_stripe_client_method",
        _stripe_method_dispatch(create_mock, cancel_mock),
    )

    response = client.post(
        "/v1/bookings",
        json={"starts_at": _future_slot(), "time_on_site_hours": 2.0, "lead_id": lead_id},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["checkout_url"] is None
    assert payload["deposit_required"] is False

    booking = await _get_booking(async_session_maker, payload["booking_id"])
    assert booking is not None
    assert booking.stripe_checkout_session_id is None
    assert booking.stripe_payment_intent_id is None
    cancel_mock.assert_not_called()


async def test_db_failure_after_stripe_success_triggers_compensation(
    client_no_raise, async_session_maker, monkeypatch
):
    _set_payment_settings(monkeypatch)
    lead_id = await _seed_lead_with_estimate(async_session_maker)

    checkout_session = SimpleNamespace(
        id="cs_test_db_fail",
        url="https://stripe.test/checkout/dbfail",
        payment_intent="pi_test_db_fail",
    )
    create_mock = AsyncMock(return_value=checkout_session)
    cancel_mock = AsyncMock()
    monkeypatch.setattr(
        "app.api.routes_bookings.stripe_infra.call_stripe_client_method",
        _stripe_method_dispatch(create_mock, cancel_mock),
    )
    monkeypatch.setattr(
        "app.api.routes_bookings.booking_service.attach_checkout_session",
        AsyncMock(side_effect=RuntimeError("db fail")),
    )

    response = client_no_raise.post(
        "/v1/bookings",
        json={"starts_at": _future_slot(), "time_on_site_hours": 2.0, "lead_id": lead_id},
    )

    assert response.status_code == 500, response.text
    create_mock.assert_awaited_once()
    cancel_mock.assert_awaited_once()
    assert cancel_mock.await_args.args == ()
    assert cancel_mock.await_args.kwargs == {"session_id": "cs_test_db_fail"}
    assert not await _booking_exists_with_checkout(async_session_maker, "cs_test_db_fail")
