"""Tests for Stripe idempotency key generation and Stripe mutation safeguards."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.infra.stripe_client import call_stripe_client_method
from app.infra.stripe_idempotency import make_stripe_idempotency_key


class TestMakeStripeIdempotencyKey:
    def test_same_inputs_produce_same_key(self):
        key_a = make_stripe_idempotency_key(
            "deposit_checkout", booking_id="book-123", amount_cents=5000, currency="CAD"
        )
        key_b = make_stripe_idempotency_key(
            "deposit_checkout", booking_id="book-123", amount_cents=5000, currency="CAD"
        )
        assert key_a == key_b

    def test_currency_is_case_insensitive(self):
        key_lower = make_stripe_idempotency_key(
            "deposit_checkout", booking_id="book-abc", amount_cents=1000, currency="cad"
        )
        key_upper = make_stripe_idempotency_key(
            "deposit_checkout", booking_id="book-abc", amount_cents=1000, currency="CAD"
        )
        assert key_lower == key_upper

    def test_different_booking_id_different_key(self):
        key_a = make_stripe_idempotency_key(
            "deposit_checkout", booking_id="book-aaa", amount_cents=5000, currency="CAD"
        )
        key_b = make_stripe_idempotency_key(
            "deposit_checkout", booking_id="book-bbb", amount_cents=5000, currency="CAD"
        )
        assert key_a != key_b

    def test_different_amount_different_key(self):
        key_a = make_stripe_idempotency_key(
            "deposit_checkout", booking_id="book-123", amount_cents=5000, currency="CAD"
        )
        key_b = make_stripe_idempotency_key(
            "deposit_checkout", booking_id="book-123", amount_cents=9999, currency="CAD"
        )
        assert key_a != key_b

    def test_different_purpose_different_key(self):
        key_deposit = make_stripe_idempotency_key(
            "deposit_checkout", booking_id="book-123", amount_cents=5000, currency="CAD"
        )
        key_invoice = make_stripe_idempotency_key(
            "invoice_checkout", booking_id="book-123", amount_cents=5000, currency="CAD"
        )
        assert key_deposit != key_invoice

    def test_key_format_has_prefix_and_digest(self):
        key = make_stripe_idempotency_key(
            "deposit_checkout", booking_id="book-xyz", amount_cents=500, currency="USD"
        )
        assert "-" in key
        digest = key[-32:]
        assert len(digest) == 32
        assert all(c in "0123456789abcdef" for c in digest)
        prefix = key[: -(32 + 1)]
        assert prefix

    def test_key_length_within_stripe_limit(self):
        key = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id="a" * 36,
            amount_cents=99999999,
            currency="USD",
            org_id="o" * 36,
            extra={"invoice_id": "i" * 36},
        )
        assert len(key) <= 255

    def test_extra_dict_key_order_is_stable(self):
        key_a = make_stripe_idempotency_key("invoice_checkout", extra={"b": "2", "a": "1"})
        key_b = make_stripe_idempotency_key("invoice_checkout", extra={"a": "1", "b": "2"})
        assert key_a == key_b

    def test_extra_nested_values_are_deterministic(self):
        key_a = make_stripe_idempotency_key(
            "invoice_checkout",
            extra={"payload": {"b": [2, 1], "a": "x"}},
        )
        key_b = make_stripe_idempotency_key(
            "invoice_checkout",
            extra={"payload": {"a": "x", "b": [2, 1]}},
        )
        assert key_a == key_b

    def test_org_id_included_in_key(self):
        key_with_org = make_stripe_idempotency_key("sub_checkout", org_id="org-abc")
        key_without_org = make_stripe_idempotency_key("sub_checkout")
        assert key_with_org != key_without_org


class TestCallStripeClientMethodGuards:
    @pytest.mark.anyio
    async def test_mutation_without_idempotency_key_raises(self):
        class MockClient:
            async def create_checkout_session(self, **kwargs):
                return kwargs

        with pytest.raises(ValueError, match="requires idempotency_key"):
            await call_stripe_client_method(
                MockClient(),
                "create_checkout_session",
                amount_cents=1000,
                currency="USD",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )

    @pytest.mark.anyio
    async def test_mutation_with_idempotency_key_passes(self):
        observed: list[dict] = []

        class MockClient:
            async def create_checkout_session(self, **kwargs):
                observed.append(kwargs)
                return SimpleNamespace(id="cs_test")

        result = await call_stripe_client_method(
            MockClient(),
            "create_checkout_session",
            amount_cents=1000,
            currency="USD",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            idempotency_key="dep-test-key",
        )

        assert result.id == "cs_test"
        assert observed[0]["idempotency_key"] == "dep-test-key"

    @pytest.mark.anyio
    async def test_read_method_without_idempotency_key_allowed(self):
        class MockClient:
            async def retrieve_checkout_session(self, *, session_id: str):
                return SimpleNamespace(id=session_id)

        result = await call_stripe_client_method(
            MockClient(),
            "retrieve_checkout_session",
            session_id="cs_existing_001",
        )
        assert result.id == "cs_existing_001"


class TestDepositCheckoutDuplicatePrevention:
    @pytest.mark.anyio
    async def test_existing_pending_session_returns_without_creating_new(
        self,
        client,
        async_session_maker,
        monkeypatch,
    ):
        from app.api import routes_payments
        from app.domain.bookings.db_models import Booking
        from app.settings import settings

        settings.stripe_secret_key = "sk_test"

        async with async_session_maker() as session:
            booking = Booking(
                team_id=1,
                starts_at=datetime.now(tz=timezone.utc),
                duration_minutes=60,
                status="PENDING",
                deposit_required=True,
                deposit_cents=5000,
                deposit_policy=["test"],
                deposit_status="pending",
                stripe_checkout_session_id="cs_existing_001",
            )
            session.add(booking)
            await session.commit()
            booking_id = booking.booking_id

        created: list[dict] = []
        retrieved: list[str] = []

        class MockStripeClient:
            async def create_checkout_session(self, **kwargs):
                created.append(kwargs)
                return SimpleNamespace(id="cs_new", url="https://stripe.test/new", payment_intent="pi_new")

            async def retrieve_checkout_session(self, *, session_id: str):
                retrieved.append(session_id)
                return SimpleNamespace(id=session_id, url="https://stripe.test/existing")

        monkeypatch.setattr(routes_payments, "_stripe_client", lambda _request: MockStripeClient())

        response = client.post(f"/v1/payments/deposit/checkout?booking_id={booking_id}")
        assert response.status_code == 200, response.text
        assert response.json()["checkout_url"] == "https://stripe.test/existing"
        assert created == []
        assert retrieved == ["cs_existing_001"]

    @pytest.mark.anyio
    async def test_new_booking_passes_idempotency_key_to_stripe(
        self,
        client,
        async_session_maker,
        monkeypatch,
    ):
        from app.api import routes_payments
        from app.domain.bookings.db_models import Booking
        from app.settings import settings

        settings.stripe_secret_key = "sk_test"

        async with async_session_maker() as session:
            booking = Booking(
                team_id=1,
                starts_at=datetime.now(tz=timezone.utc),
                duration_minutes=60,
                status="PENDING",
                deposit_required=True,
                deposit_cents=5000,
                deposit_policy=["test"],
                deposit_status=None,
            )
            session.add(booking)
            await session.commit()
            booking_id = booking.booking_id

        created_kwargs: list[dict] = []

        class MockStripeClient:
            async def create_checkout_session(self, **kwargs):
                created_kwargs.append(kwargs)
                return SimpleNamespace(id="cs_fresh", url="https://stripe.test/fresh", payment_intent="pi_fresh")

        monkeypatch.setattr(routes_payments, "_stripe_client", lambda _request: MockStripeClient())

        response = client.post(f"/v1/payments/deposit/checkout?booking_id={booking_id}")
        assert response.status_code == 201, response.text
        assert len(created_kwargs) == 1

        expected_key = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id=booking_id,
            amount_cents=5000,
            currency=settings.deposit_currency,
        )
        assert created_kwargs[0]["idempotency_key"] == expected_key

    def test_retry_with_same_booking_uses_same_idempotency_key(self):
        booking_id = "book-retry-test-unique-id"
        key_first = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id=booking_id,
            amount_cents=4200,
            currency="cad",
        )
        key_second = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id=booking_id,
            amount_cents=4200,
            currency="CAD",
        )
        assert key_first == key_second
