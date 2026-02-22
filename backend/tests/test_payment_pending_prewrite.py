"""Tests for Epic 2 / PR-02: pre-write payment state (PENDING) before Stripe call.

Acceptance criteria verified here:
  1. A PENDING CheckoutAttempt row exists in the DB *before* the Stripe API call.
  2. A crash between Phase 1 (Stripe call) and Phase 2 (DB attach) marks the
     attempt FAILED with a non-PII error_type for auditability.
  3. A Stripe failure marks the attempt FAILED (non-PII error_type preserved).
  4. Retry after failure reuses the same idempotency key (no duplicate attempt rows).
  5. Tests are green.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.domain.bookings.db_models import Booking, CheckoutAttempt
from app.infra.stripe_idempotency import make_stripe_idempotency_key
from app.settings import settings


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_stripe_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_prewrite")
    monkeypatch.setattr(settings, "deposits_enabled", True)
    monkeypatch.setattr(settings, "stripe_success_url", "https://example.com/success")
    monkeypatch.setattr(settings, "stripe_cancel_url", "https://example.com/cancel")
    monkeypatch.setattr(settings, "deposit_currency", "cad")


async def _seed_deposit_booking(async_session_maker) -> str:
    """Insert a booking that requires a deposit and return its booking_id."""
    async with async_session_maker() as session:
        booking = Booking(
            team_id=1,
            starts_at=datetime.now(tz=timezone.utc),
            duration_minutes=120,
            status="PENDING",
            deposit_required=True,
            deposit_cents=5000,
            deposit_policy=["first_time_client"],
            deposit_status=None,
        )
        session.add(booking)
        await session.commit()
        return booking.booking_id


async def _get_attempt(async_session_maker, booking_id: str) -> CheckoutAttempt | None:
    async with async_session_maker() as session:
        return await session.scalar(
            select(CheckoutAttempt).where(CheckoutAttempt.booking_id == booking_id)
        )


async def _count_attempts(async_session_maker, booking_id: str) -> int:
    async with async_session_maker() as session:
        result = await session.scalar(
            select(func.count(CheckoutAttempt.attempt_id)).where(
                CheckoutAttempt.booking_id == booking_id
            )
        )
        return int(result or 0)


def _ok_stripe_call(checkout_session_id: str = "cs_prewrite_ok"):
    """Return a mock for call_stripe_client_method that always succeeds."""

    async def _dispatch(stripe_client, method_name, /, *args, **kwargs):
        if method_name == "create_checkout_session":
            return SimpleNamespace(
                id=checkout_session_id,
                url=f"https://stripe.test/{checkout_session_id}",
                payment_intent="pi_prewrite_ok",
            )
        if method_name == "retrieve_checkout_session":
            session_id = kwargs.get("session_id", checkout_session_id)
            return SimpleNamespace(
                id=session_id,
                url=f"https://stripe.test/{session_id}",
            )
        raise AssertionError(f"Unexpected Stripe method: {method_name}")

    return _dispatch


# ---------------------------------------------------------------------------
# Test 1 – PENDING attempt committed before Stripe API call
# ---------------------------------------------------------------------------


async def test_pending_attempt_exists_before_stripe_call(
    client, async_session_maker, monkeypatch
):
    """Phase 0 must commit the PENDING attempt row *before* Phase 1 (Stripe call)."""
    _set_stripe_settings(monkeypatch)
    booking_id = await _seed_deposit_booking(async_session_maker)

    attempt_status_when_stripe_called: list[str | None] = []

    async def _intercept(stripe_client, method_name, /, *args, **kwargs):
        if method_name == "create_checkout_session":
            # Query DB in a fresh session — the Phase 0 commit must be visible here.
            attempt = await _get_attempt(async_session_maker, booking_id)
            attempt_status_when_stripe_called.append(attempt.status if attempt else None)
            return SimpleNamespace(
                id="cs_intercept",
                url="https://stripe.test/intercept",
                payment_intent="pi_intercept",
            )
        if method_name == "retrieve_checkout_session":
            return SimpleNamespace(id=kwargs.get("session_id"), url="https://stripe.test/intercept")
        raise AssertionError(f"Unexpected: {method_name}")

    monkeypatch.setattr(
        "app.api.routes_payments.stripe_infra.call_stripe_client_method", _intercept
    )

    response = client.post(f"/v1/payments/deposit/checkout?booking_id={booking_id}")
    assert response.status_code == 201, response.text

    assert attempt_status_when_stripe_called == ["PENDING"], (
        "CheckoutAttempt must be PENDING in DB when Stripe is called, "
        f"got {attempt_status_when_stripe_called}"
    )


# ---------------------------------------------------------------------------
# Test 2 – Crash window: process dies between Phase 1 and Phase 2
# ---------------------------------------------------------------------------


async def test_crash_between_phase1_and_phase2_marks_attempt_failed(
    client_no_raise, async_session_maker, monkeypatch
):
    """If finalize_checkout_attempt raises in Phase 2, attempt is marked FAILED."""
    _set_stripe_settings(monkeypatch)
    booking_id = await _seed_deposit_booking(async_session_maker)

    monkeypatch.setattr(
        "app.api.routes_payments.stripe_infra.call_stripe_client_method",
        _ok_stripe_call("cs_crash_test"),
    )
    # Simulate process crash during Phase 2 by making finalize raise.
    monkeypatch.setattr(
        "app.api.routes_payments.booking_service.finalize_checkout_attempt",
        AsyncMock(side_effect=RuntimeError("simulated Phase-2 crash")),
    )

    response = client_no_raise.post(f"/v1/payments/deposit/checkout?booking_id={booking_id}")
    assert response.status_code == 500, response.text

    attempt = await _get_attempt(async_session_maker, booking_id)
    assert attempt is not None, "CheckoutAttempt must exist even after a crash"
    assert attempt.status == "FAILED", (
        f"Attempt must be FAILED after crash, got {attempt.status}"
    )
    assert attempt.error_type == "RuntimeError"
    assert attempt.purpose == "deposit_checkout"
    assert attempt.amount_cents == 5000


async def test_existing_active_session_finalizes_attempt_before_return(
    client, async_session_maker, monkeypatch
):
    """Early-return path must still finalize the attempt as CREATED."""
    _set_stripe_settings(monkeypatch)
    booking_id = await _seed_deposit_booking(async_session_maker)

    async with async_session_maker() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.deposit_status = "pending"
        booking.stripe_checkout_session_id = "cs_existing_active"
        await session.commit()

    monkeypatch.setattr(
        "app.api.routes_payments.stripe_infra.call_stripe_client_method",
        _ok_stripe_call("cs_existing_active"),
    )

    response = client.post(f"/v1/payments/deposit/checkout?booking_id={booking_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["checkout_url"] == "https://stripe.test/cs_existing_active"

    attempt = await _get_attempt(async_session_maker, booking_id)
    assert attempt is not None
    assert attempt.status == "CREATED"
    assert attempt.stripe_session_id == "cs_existing_active"


# ---------------------------------------------------------------------------
# Test 3 – Stripe failure marks attempt FAILED (no PII)
# ---------------------------------------------------------------------------


async def test_stripe_failure_marks_attempt_failed(
    client_no_raise, async_session_maker, monkeypatch
):
    """On Stripe error the attempt row must be FAILED and carry error_type (no PII)."""
    _set_stripe_settings(monkeypatch)
    booking_id = await _seed_deposit_booking(async_session_maker)

    async def _stripe_fail(stripe_client, method_name, /, *args, **kwargs):
        if method_name == "create_checkout_session":
            raise RuntimeError("stripe network error")
        raise AssertionError(f"Unexpected: {method_name}")

    monkeypatch.setattr(
        "app.api.routes_payments.stripe_infra.call_stripe_client_method", _stripe_fail
    )

    response = client_no_raise.post(f"/v1/payments/deposit/checkout?booking_id={booking_id}")
    assert response.status_code == 502, response.text

    attempt = await _get_attempt(async_session_maker, booking_id)
    assert attempt is not None
    assert attempt.status == "FAILED"
    assert attempt.error_type == "RuntimeError", (
        f"error_type should be the exception class name, got {attempt.error_type!r}"
    )
    # No PII: error_type should only be the class name, not a message
    assert "stripe network error" not in (attempt.error_type or "")
    assert "stripe network error" not in (attempt.error_code or "")


# ---------------------------------------------------------------------------
# Test 4 – Retry after failure reuses same idempotency key; no duplicate rows
# ---------------------------------------------------------------------------


async def test_retry_after_failure_reuses_idempotency_key_no_duplicate_attempt(
    client_no_raise, async_session_maker, monkeypatch
):
    """After a FAILED attempt, a retry must:
    - Pass the same idempotency key to Stripe (so Stripe doesn't duplicate).
    - Not insert a second CheckoutAttempt row.
    - Update the existing attempt to CREATED on success.
    """
    _set_stripe_settings(monkeypatch)
    booking_id = await _seed_deposit_booking(async_session_maker)

    call_count = [0]
    idempotency_keys_seen: list[str] = []

    async def _fail_then_succeed(stripe_client, method_name, /, *args, **kwargs):
        if method_name == "create_checkout_session":
            call_count[0] += 1
            idempotency_keys_seen.append(kwargs.get("idempotency_key"))
            if call_count[0] == 1:
                raise RuntimeError("first attempt fails")
            return SimpleNamespace(
                id="cs_retry_ok",
                url="https://stripe.test/retry",
                payment_intent="pi_retry_ok",
            )
        if method_name == "retrieve_checkout_session":
            return SimpleNamespace(id="cs_retry_ok", url="https://stripe.test/retry")
        raise AssertionError(f"Unexpected: {method_name}")

    monkeypatch.setattr(
        "app.api.routes_payments.stripe_infra.call_stripe_client_method",
        _fail_then_succeed,
    )

    # First call – Stripe fails.
    r1 = client_no_raise.post(f"/v1/payments/deposit/checkout?booking_id={booking_id}")
    assert r1.status_code == 502, r1.text

    attempt_after_fail = await _get_attempt(async_session_maker, booking_id)
    assert attempt_after_fail is not None
    assert attempt_after_fail.status == "FAILED"

    # Second call – Stripe succeeds (retry).
    r2 = client_no_raise.post(f"/v1/payments/deposit/checkout?booking_id={booking_id}")
    assert r2.status_code == 201, r2.text

    # Idempotency key must be identical on both calls.
    assert len(idempotency_keys_seen) == 2
    assert idempotency_keys_seen[0] == idempotency_keys_seen[1], (
        f"Retry must reuse the same idempotency key; "
        f"first={idempotency_keys_seen[0]!r}, second={idempotency_keys_seen[1]!r}"
    )

    # Verify the key matches the independently-computed expected value.
    expected_key = make_stripe_idempotency_key(
        "deposit_checkout",
        booking_id=booking_id,
        amount_cents=5000,
        currency=settings.deposit_currency,
    )
    assert idempotency_keys_seen[0] == expected_key

    # Exactly one attempt row (not two).
    count = await _count_attempts(async_session_maker, booking_id)
    assert count == 1, f"Expected 1 attempt row, got {count}"

    # Attempt is now CREATED.
    final_attempt = await _get_attempt(async_session_maker, booking_id)
    assert final_attempt is not None
    assert final_attempt.status == "CREATED"
    assert final_attempt.stripe_session_id == "cs_retry_ok"


# ---------------------------------------------------------------------------
# Test 5 – Happy path: attempt transitions PENDING → CREATED
# ---------------------------------------------------------------------------


async def test_happy_path_attempt_created_after_success(
    client, async_session_maker, monkeypatch
):
    """On success the attempt must end up CREATED with Stripe IDs populated."""
    _set_stripe_settings(monkeypatch)
    booking_id = await _seed_deposit_booking(async_session_maker)

    monkeypatch.setattr(
        "app.api.routes_payments.stripe_infra.call_stripe_client_method",
        _ok_stripe_call("cs_happy"),
    )

    response = client.post(f"/v1/payments/deposit/checkout?booking_id={booking_id}")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["checkout_url"] == "https://stripe.test/cs_happy"
    assert body["booking_id"] == booking_id

    attempt = await _get_attempt(async_session_maker, booking_id)
    assert attempt is not None
    assert attempt.status == "CREATED"
    assert attempt.stripe_session_id == "cs_happy"
    assert attempt.stripe_payment_intent_id == "pi_prewrite_ok"
    assert attempt.purpose == "deposit_checkout"
    assert attempt.amount_cents == 5000
    assert attempt.currency == "CAD"
