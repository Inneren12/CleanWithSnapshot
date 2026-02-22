"""Tests for Stripe idempotency key generation and booking deposit duplicate prevention."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from app.infra.stripe_idempotency import make_stripe_idempotency_key


# ---------------------------------------------------------------------------
# Unit tests: make_stripe_idempotency_key
# ---------------------------------------------------------------------------


class TestMakeStripeIdempotencyKey:
    """Stability and uniqueness tests for make_stripe_idempotency_key."""

    def test_same_inputs_produce_same_key(self):
        key_a = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id="book-123",
            amount_cents=5000,
            currency="CAD",
        )
        key_b = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id="book-123",
            amount_cents=5000,
            currency="CAD",
        )
        assert key_a == key_b

    def test_currency_is_case_insensitive(self):
        key_lower = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id="book-abc",
            amount_cents=1000,
            currency="cad",
        )
        key_upper = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id="book-abc",
            amount_cents=1000,
            currency="CAD",
        )
        assert key_lower == key_upper

    def test_different_booking_id_different_key(self):
        key_a = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id="book-aaa",
            amount_cents=5000,
            currency="CAD",
        )
        key_b = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id="book-bbb",
            amount_cents=5000,
            currency="CAD",
        )
        assert key_a != key_b

    def test_different_amount_different_key(self):
        key_a = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id="book-123",
            amount_cents=5000,
            currency="CAD",
        )
        key_b = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id="book-123",
            amount_cents=9999,
            currency="CAD",
        )
        assert key_a != key_b

    def test_different_purpose_different_key(self):
        key_deposit = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id="book-123",
            amount_cents=5000,
            currency="CAD",
        )
        key_invoice = make_stripe_idempotency_key(
            "invoice_checkout",
            booking_id="book-123",
            amount_cents=5000,
            currency="CAD",
        )
        assert key_deposit != key_invoice

    def test_key_format_has_prefix_and_digest(self):
        key = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id="book-xyz",
            amount_cents=500,
            currency="USD",
        )
        # Format: <prefix>-<32-hex-digest>
        # The digest is always the last 32 hex characters; prefix is everything before the last "-".
        assert "-" in key
        digest = key[-32:]
        assert len(digest) == 32, f"digest should be 32 chars, got {len(digest)}: {key}"
        assert all(c in "0123456789abcdef" for c in digest), f"non-hex digest: {digest}"
        prefix = key[: -(32 + 1)]  # strip "-" + digest
        assert len(prefix) > 0, "prefix must not be empty"

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
        key_a = make_stripe_idempotency_key(
            "invoice_checkout",
            extra={"b": "2", "a": "1"},
        )
        key_b = make_stripe_idempotency_key(
            "invoice_checkout",
            extra={"a": "1", "b": "2"},
        )
        assert key_a == key_b

    def test_org_id_included_in_key(self):
        key_with_org = make_stripe_idempotency_key(
            "sub_checkout",
            org_id="org-abc",
        )
        key_without_org = make_stripe_idempotency_key(
            "sub_checkout",
        )
        assert key_with_org != key_without_org

    def test_none_fields_excluded_from_hash(self):
        # All None optional args → stable key based only on purpose
        key_a = make_stripe_idempotency_key("portal")
        key_b = make_stripe_idempotency_key("portal")
        assert key_a == key_b


# ---------------------------------------------------------------------------
# Integration-style tests: booking deposit duplicate prevention
# ---------------------------------------------------------------------------


def _make_booking(
    booking_id: str,
    deposit_cents: int = 5000,
    deposit_status: str | None = None,
    stripe_checkout_session_id: str | None = None,
):
    """Build a minimal booking-like SimpleNamespace for tests."""
    return SimpleNamespace(
        booking_id=booking_id,
        deposit_required=True,
        deposit_cents=deposit_cents,
        deposit_status=deposit_status,
        stripe_checkout_session_id=stripe_checkout_session_id,
        org_id=None,
    )


class TestDepositCheckoutIdempotencyKeys:
    """Verify that create_checkout_session receives the deterministic idempotency key."""

    def test_idempotency_key_passed_to_stripe_client(self):
        """The idempotency key kwarg must reach the underlying StripeClient method."""
        from app.infra.stripe_client import StripeClient

        captured_calls: list[dict] = []

        class MockStripeSDK:
            api_key = None

            class checkout:
                class Session:
                    @staticmethod
                    def create(**kwargs):
                        captured_calls.append(kwargs)
                        return SimpleNamespace(id="cs_test", url="https://stripe.test", payment_intent="pi_test")

        import anyio

        sdk = MockStripeSDK()
        client = StripeClient(secret_key="sk_test", webhook_secret="whsec_test", stripe_sdk=sdk)

        key = make_stripe_idempotency_key(
            "deposit_checkout", booking_id="book-001", amount_cents=5000, currency="CAD"
        )

        async def _run():
            return await client.create_checkout_session(
                amount_cents=5000,
                currency="CAD",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                idempotency_key=key,
            )

        anyio.from_thread.run_sync(lambda: None)  # touch anyio so imports work
        result = asyncio.run(_run())
        assert result.id == "cs_test"
        assert len(captured_calls) == 1
        assert captured_calls[0]["idempotency_key"] == key

    def test_idempotency_key_stable_across_calls(self):
        """Two calls with the same booking produce the same key."""
        booking_id = "book-stable-001"
        amount = 7500
        currency = "CAD"

        key1 = make_stripe_idempotency_key(
            "deposit_checkout", booking_id=booking_id, amount_cents=amount, currency=currency
        )
        key2 = make_stripe_idempotency_key(
            "deposit_checkout", booking_id=booking_id, amount_cents=amount, currency=currency
        )
        assert key1 == key2

    def test_no_idempotency_key_when_not_provided(self):
        """Without an idempotency_key, no extra kwarg is passed to the Stripe SDK."""
        from app.infra.stripe_client import StripeClient

        captured_calls: list[dict] = []

        class MockStripeSDK:
            api_key = None

            class checkout:
                class Session:
                    @staticmethod
                    def create(**kwargs):
                        captured_calls.append(kwargs)
                        return SimpleNamespace(id="cs_noidempotency", url="https://stripe.test", payment_intent=None)

        sdk = MockStripeSDK()
        client = StripeClient(secret_key="sk_test", webhook_secret="whsec_test", stripe_sdk=sdk)

        async def _run():
            return await client.create_checkout_session(
                amount_cents=1000,
                currency="USD",
                success_url="https://example.com/s",
                cancel_url="https://example.com/c",
            )

        asyncio.run(_run())
        assert "idempotency_key" not in captured_calls[0]


class TestDepositCheckoutDuplicatePrevention:
    """Verify that the /v1/payments/deposit/checkout endpoint skips Stripe when a
    session already exists in the DB and the deposit is in an active state."""

    def _build_client_with_retrieve(self, existing_url: str = "https://stripe.test/existing"):
        """Return a mock stripe client that tracks create/retrieve calls."""
        created: list[dict] = []
        retrieved: list[str] = []

        class MockClient:
            async def create_checkout_session(self, **kwargs):
                created.append(kwargs)
                return SimpleNamespace(
                    id="cs_new", url="https://stripe.test/new", payment_intent="pi_new"
                )

            async def retrieve_checkout_session(self, *, session_id: str):
                retrieved.append(session_id)
                return SimpleNamespace(id=session_id, url=existing_url)

            async def attach_checkout_session(self, *args, **kwargs):
                pass

        return MockClient(), created, retrieved

    def test_existing_pending_session_returns_without_creating_new(self, client, async_session_maker):
        """If booking.stripe_checkout_session_id is set and deposit is pending,
        the endpoint retrieves the existing session and returns its URL without
        calling create_checkout_session."""
        from app.domain.bookings.db_models import Booking
        from app.main import app
        from app.settings import settings

        settings.stripe_secret_key = "sk_test"

        booking_id: str = ""

        async def _seed():
            nonlocal booking_id
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

        asyncio.run(_seed())

        created: list[dict] = []
        retrieved: list[str] = []

        class MockStripeClient:
            def create_checkout_session(self, **kwargs):
                created.append(kwargs)
                return SimpleNamespace(id="cs_new", url="https://stripe.test/new", payment_intent="pi_new")

            def retrieve_checkout_session(self, *, session_id: str):
                retrieved.append(session_id)
                return SimpleNamespace(id=session_id, url="https://stripe.test/existing")

        app.state.stripe_client = MockStripeClient()

        response = client.post(f"/v1/payments/deposit/checkout?booking_id={booking_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["checkout_url"] == "https://stripe.test/existing"
        assert body["booking_id"] == booking_id
        # create must NOT have been called
        assert created == [], "create_checkout_session must not be called for existing session"
        # retrieve must have been called with the existing session id
        assert retrieved == ["cs_existing_001"]

    def test_new_booking_passes_idempotency_key_to_stripe(self, client, async_session_maker):
        """A booking without an existing session triggers create_checkout_session
        with a deterministic idempotency_key kwarg."""
        from app.domain.bookings.db_models import Booking
        from app.main import app
        from app.settings import settings

        settings.stripe_secret_key = "sk_test"

        booking_id: str = ""

        async def _seed():
            nonlocal booking_id
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

        asyncio.run(_seed())

        created_kwargs: list[dict] = []

        class MockStripeClient:
            def create_checkout_session(self, **kwargs):
                created_kwargs.append(kwargs)
                return SimpleNamespace(id="cs_fresh", url="https://stripe.test/fresh", payment_intent="pi_fresh")

        app.state.stripe_client = MockStripeClient()

        response = client.post(f"/v1/payments/deposit/checkout?booking_id={booking_id}")
        assert response.status_code == 201, response.text
        assert len(created_kwargs) == 1
        assert "idempotency_key" in created_kwargs[0], "idempotency_key must be passed to Stripe SDK"

        # Verify the key is deterministic by computing it independently
        expected_key = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id=booking_id,
            amount_cents=5000,
            currency=settings.deposit_currency,
        )
        assert created_kwargs[0]["idempotency_key"] == expected_key

    def test_retry_with_same_booking_uses_same_idempotency_key(self, async_session_maker):
        """Two calls for the same booking produce the same idempotency key, which
        is the mechanism Stripe uses to de-duplicate the request."""
        from app.settings import settings

        booking_id = "book-retry-test-unique-id"
        amount = 4200

        key_first = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id=booking_id,
            amount_cents=amount,
            currency=settings.deposit_currency,
        )
        key_second = make_stripe_idempotency_key(
            "deposit_checkout",
            booking_id=booking_id,
            amount_cents=amount,
            currency=settings.deposit_currency,
        )
        assert key_first == key_second, "Idempotency key must be stable for retries"
