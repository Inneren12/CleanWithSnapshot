"""Tests for Stripe-outside-DB-transaction boundary correctness.

Covers:
- Happy path: Stripe succeeds, DB write succeeds → booking created with checkout_url.
- Stripe fails: no DB changes committed, deposit downgraded, booking still created.
- DB fails after Stripe: Stripe session is cancelled (compensation), no booking in DB.
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select

from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import LOCAL_TZ
from app.domain.leads.db_models import Lead
from app.main import app
from app.settings import settings


# ── Helpers ──────────────────────────────────────────────────────────────────

def _future_slot() -> str:
    """Return an ISO datetime for a booking slot during working hours tomorrow."""
    from datetime import timedelta

    now = datetime.now(tz=LOCAL_TZ)
    tomorrow = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    return tomorrow.astimezone(timezone.utc).isoformat()


def _seed_lead_with_estimate(async_session_maker) -> str:
    """Insert a Lead with all required contact fields and return its lead_id."""

    async def _insert() -> str:
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

    return asyncio.run(_insert())


def _count_bookings(async_session_maker) -> int:
    async def _count() -> int:
        async with async_session_maker() as session:
            result = await session.execute(select(func.count()).select_from(Booking))
            return int(result.scalar_one() or 0)

    return asyncio.run(_count())


def _get_booking_by_id(async_session_maker, booking_id: str) -> Booking | None:
    async def _fetch() -> Booking | None:
        async with async_session_maker() as session:
            return await session.get(Booking, booking_id)

    return asyncio.run(_fetch())


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_happy_path_stripe_and_db_succeed(client, async_session_maker):
    """Booking is created and checkout_url returned when both Stripe and DB succeed."""
    settings.stripe_secret_key = "sk_test_happy"
    settings.deposits_enabled = True
    settings.stripe_success_url = "https://example.com/success?booking={BOOKING_ID}"
    settings.stripe_cancel_url = "https://example.com/cancel?booking={BOOKING_ID}"

    lead_id = _seed_lead_with_estimate(async_session_maker)

    cancel_calls: list = []

    mock_checkout = SimpleNamespace(
        id="cs_test_happy",
        url="https://stripe.test/checkout/happy",
        payment_intent="pi_test_happy",
    )

    with (
        patch(
            "app.api.routes_bookings.stripe_infra.create_checkout_session",
            new=AsyncMock(return_value=mock_checkout),
        ),
        patch(
            "app.api.routes_bookings.stripe_infra.cancel_checkout_session",
            new=AsyncMock(side_effect=lambda **kw: cancel_calls.append(kw)),
        ),
    ):
        response = client.post(
            "/v1/bookings",
            json={
                "starts_at": _future_slot(),
                "time_on_site_hours": 2.0,
                "lead_id": lead_id,
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["checkout_url"] == "https://stripe.test/checkout/happy"
    assert body["deposit_required"] is True

    # Verify booking persisted with checkout session attached
    booking = _get_booking_by_id(async_session_maker, body["booking_id"])
    assert booking is not None
    assert booking.stripe_checkout_session_id == "cs_test_happy"
    assert booking.stripe_payment_intent_id == "pi_test_happy"

    # No compensation should have been triggered
    assert cancel_calls == []


def test_stripe_fails_deposit_downgraded_booking_still_created(client, async_session_maker):
    """When Stripe raises before any DB work, the deposit is downgraded but
    the booking is still created (without deposit) and no cancellation is attempted."""
    settings.stripe_secret_key = "sk_test_stripe_fail"
    settings.deposits_enabled = True
    settings.stripe_success_url = "https://example.com/success?booking={BOOKING_ID}"
    settings.stripe_cancel_url = "https://example.com/cancel?booking={BOOKING_ID}"

    lead_id = _seed_lead_with_estimate(async_session_maker)
    cancel_calls: list = []

    with (
        patch(
            "app.api.routes_bookings.stripe_infra.create_checkout_session",
            new=AsyncMock(side_effect=RuntimeError("Stripe connection timeout")),
        ),
        patch(
            "app.api.routes_bookings.stripe_infra.cancel_checkout_session",
            new=AsyncMock(side_effect=lambda **kw: cancel_calls.append(kw)),
        ),
    ):
        response = client.post(
            "/v1/bookings",
            json={
                "starts_at": _future_slot(),
                "time_on_site_hours": 2.0,
                "lead_id": lead_id,
            },
        )

    # Booking should still be created – deposit downgraded to not-required
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["checkout_url"] is None
    assert body["deposit_required"] is False

    # DB write committed (booking exists)
    booking = _get_booking_by_id(async_session_maker, body["booking_id"])
    assert booking is not None
    assert booking.stripe_checkout_session_id is None

    # No Stripe session was created so no cancellation needed
    assert cancel_calls == []


def test_db_fails_after_stripe_succeeds_compensation_called(client, async_session_maker):
    """When the DB transaction fails after Stripe already created a checkout
    session, the Stripe session must be expired (compensated) and no booking
    should be persisted."""
    settings.stripe_secret_key = "sk_test_db_fail"
    settings.deposits_enabled = True
    settings.stripe_success_url = "https://example.com/success?booking={BOOKING_ID}"
    settings.stripe_cancel_url = "https://example.com/cancel?booking={BOOKING_ID}"

    lead_id = _seed_lead_with_estimate(async_session_maker)

    cancelled_sessions: list[str] = []

    mock_checkout = SimpleNamespace(
        id="cs_test_db_fail",
        url="https://stripe.test/checkout/will_be_cancelled",
        payment_intent="pi_test_db_fail",
    )

    async def _fake_cancel(*, stripe_client, secret_key, session_id):
        cancelled_sessions.append(session_id)

    bookings_before = _count_bookings(async_session_maker)

    with (
        patch(
            "app.api.routes_bookings.stripe_infra.create_checkout_session",
            new=AsyncMock(return_value=mock_checkout),
        ),
        patch(
            "app.api.routes_bookings.stripe_infra.cancel_checkout_session",
            new=AsyncMock(side_effect=_fake_cancel),
        ),
        # Force the DB write to fail by making create_booking raise ValueError
        # (simulates a slot-conflict / integrity failure inside the transaction).
        patch(
            "app.api.routes_bookings.booking_service.create_booking",
            new=AsyncMock(side_effect=ValueError("Requested slot is no longer available")),
        ),
    ):
        response = client.post(
            "/v1/bookings",
            json={
                "starts_at": _future_slot(),
                "time_on_site_hours": 2.0,
                "lead_id": lead_id,
            },
        )

    # The endpoint should return 409 Conflict (slot unavailable)
    assert response.status_code == 409, response.text

    # Stripe session must have been expired as compensation
    assert cancelled_sessions == ["cs_test_db_fail"], (
        f"Expected Stripe cancel for cs_test_db_fail, got: {cancelled_sessions}"
    )

    # No new booking should have been committed to the DB
    bookings_after = _count_bookings(async_session_maker)
    assert bookings_after == bookings_before


def test_db_fails_stripe_cancel_also_fails_warning_logged(client, async_session_maker):
    """When both the DB write and the Stripe compensation call fail, the endpoint
    still returns 409 and a structured warning is emitted (no exception leaks)."""
    settings.stripe_secret_key = "sk_test_double_fail"
    settings.deposits_enabled = True
    settings.stripe_success_url = "https://example.com/success?booking={BOOKING_ID}"
    settings.stripe_cancel_url = "https://example.com/cancel?booking={BOOKING_ID}"

    lead_id = _seed_lead_with_estimate(async_session_maker)

    mock_checkout = SimpleNamespace(
        id="cs_test_double_fail",
        url="https://stripe.test/checkout/double_fail",
        payment_intent="pi_test_double_fail",
    )

    warning_messages: list[str] = []

    import logging

    class _CapturingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            warning_messages.append(record.getMessage())

    handler = _CapturingHandler()
    booking_logger = logging.getLogger("app.api.routes_bookings")
    booking_logger.addHandler(handler)

    try:
        with (
            patch(
                "app.api.routes_bookings.stripe_infra.create_checkout_session",
                new=AsyncMock(return_value=mock_checkout),
            ),
            patch(
                "app.api.routes_bookings.stripe_infra.cancel_checkout_session",
                new=AsyncMock(side_effect=RuntimeError("Stripe also down")),
            ),
            patch(
                "app.api.routes_bookings.booking_service.create_booking",
                new=AsyncMock(side_effect=ValueError("Requested slot is no longer available")),
            ),
        ):
            response = client.post(
                "/v1/bookings",
                json={
                    "starts_at": _future_slot(),
                    "time_on_site_hours": 2.0,
                    "lead_id": lead_id,
                },
            )
    finally:
        booking_logger.removeHandler(handler)

    assert response.status_code == 409, response.text

    # A structured warning about the cancel failure must have been emitted
    cancel_fail_warnings = [m for m in warning_messages if "stripe_session_cancel_failed" in m]
    assert cancel_fail_warnings, (
        f"Expected stripe_session_cancel_failed warning, got: {warning_messages}"
    )
