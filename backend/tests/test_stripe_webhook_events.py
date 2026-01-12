import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import sqlalchemy as sa

from app.domain.bookings.db_models import Booking
from app.domain.disputes import schemas as dispute_schemas
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice, Payment
from app.domain.disputes.db_models import Dispute
from app.main import app
from app.settings import settings


async def _seed_invoice(async_session_maker, *, status: str = invoice_statuses.INVOICE_STATUS_DRAFT) -> str:
    async with async_session_maker() as session:
        invoice = Invoice(
            invoice_number=f"INV-STRIPE-{uuid.uuid4()}",
            order_id=None,
            customer_id=None,
            status=status,
            issue_date=date.today(),
            currency="CAD",
            subtotal_cents=5000,
            tax_cents=0,
            total_cents=5000,
        )
        session.add(invoice)
        await session.commit()
        return invoice.invoice_id


async def _seed_booking(async_session_maker) -> str:
    async with async_session_maker() as session:
        booking = Booking(
            org_id=settings.default_org_id,
            team_id=1,
            starts_at=datetime.now(tz=timezone.utc),
            duration_minutes=120,
            status="NEW",
            deposit_required=True,
            deposit_cents=5000,
        )
        session.add(booking)
        await session.commit()
        return booking.booking_id


def test_invoice_finalized_marks_sent(client, async_session_maker, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    invoice_id = asyncio.run(_seed_invoice(async_session_maker))
    event = {
        "id": "evt_invoice_finalized",
        "type": "invoice.finalized",
        "created": int(datetime.now(tz=timezone.utc).timestamp()),
        "data": {"object": {"id": "in_test", "metadata": {"invoice_id": invoice_id}}},
    }
    app.state.stripe_client = SimpleNamespace(verify_webhook=lambda payload, signature: event)

    response = client.post("/v1/payments/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1"})
    assert response.status_code == 200
    assert response.json()["processed"] is True

    async def _fetch_status() -> str:
        async with async_session_maker() as session:
            invoice = await session.get(Invoice, invoice_id)
            assert invoice is not None
            return invoice.status

    assert asyncio.run(_fetch_status()) == invoice_statuses.INVOICE_STATUS_SENT


def test_invoice_payment_failed_records_payment(client, async_session_maker, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    invoice_id = asyncio.run(
        _seed_invoice(async_session_maker, status=invoice_statuses.INVOICE_STATUS_SENT)
    )
    event = {
        "id": "evt_invoice_failed",
        "type": "invoice.payment_failed",
        "created": int(datetime.now(tz=timezone.utc).timestamp()),
        "data": {
            "object": {
                "id": "in_failed",
                "payment_intent": "pi_failed",
                "amount_due": 5000,
                "currency": "CAD",
                "metadata": {"invoice_id": invoice_id},
            }
        },
    }
    app.state.stripe_client = SimpleNamespace(verify_webhook=lambda payload, signature: event)

    response = client.post("/v1/payments/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1"})
    assert response.status_code == 200
    assert response.json()["processed"] is True

    async def _fetch_payment() -> tuple[str, int]:
        async with async_session_maker() as session:
            payment = await session.scalar(
                sa.select(Payment).where(Payment.invoice_id == invoice_id)
            )
            assert payment is not None
            invoice = await session.get(Invoice, invoice_id)
            assert invoice is not None
            return payment.status, invoice.status

    payment_status, invoice_status = asyncio.run(_fetch_payment())
    assert payment_status == invoice_statuses.PAYMENT_STATUS_FAILED
    assert invoice_status == invoice_statuses.INVOICE_STATUS_SENT


def test_charge_refund_adjusts_invoice_payment(client, async_session_maker, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    invoice_id = asyncio.run(
        _seed_invoice(async_session_maker, status=invoice_statuses.INVOICE_STATUS_SENT)
    )

    async def _seed_payment() -> None:
        async with async_session_maker() as session:
            payment = Payment(
                invoice_id=invoice_id,
                provider="stripe",
                provider_ref="pi_refund",
                payment_intent_id="pi_refund",
                method=invoice_statuses.PAYMENT_METHOD_CARD,
                amount_cents=5000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                reference="ch_refund",
            )
            session.add(payment)
            await session.commit()

    asyncio.run(_seed_payment())

    event = {
        "id": "evt_charge_refund",
        "type": "charge.refunded",
        "created": int(datetime.now(tz=timezone.utc).timestamp()),
        "data": {
            "object": {
                "id": "ch_refund",
                "payment_intent": "pi_refund",
                "amount": 5000,
                "amount_refunded": 2000,
            }
        },
    }
    app.state.stripe_client = SimpleNamespace(verify_webhook=lambda payload, signature: event)

    response = client.post("/v1/payments/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1"})
    assert response.status_code == 200
    assert response.json()["processed"] is True

    async def _fetch_payment() -> tuple[int, str]:
        async with async_session_maker() as session:
            payment = await session.scalar(
                sa.select(Payment).where(Payment.invoice_id == invoice_id)
            )
            invoice = await session.get(Invoice, invoice_id)
            assert payment is not None
            assert invoice is not None
            return payment.amount_cents, invoice.status

    amount_cents, invoice_status = asyncio.run(_fetch_payment())
    assert amount_cents == 3000
    assert invoice_status == invoice_statuses.INVOICE_STATUS_PARTIAL


def test_charge_refund_downgrades_paid_invoice_on_full_refund(
    client, async_session_maker, monkeypatch
):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    invoice_id = asyncio.run(
        _seed_invoice(async_session_maker, status=invoice_statuses.INVOICE_STATUS_PAID)
    )

    async def _seed_payment() -> None:
        async with async_session_maker() as session:
            payment = Payment(
                invoice_id=invoice_id,
                provider="stripe",
                provider_ref="pi_full_refund",
                payment_intent_id="pi_full_refund",
                method=invoice_statuses.PAYMENT_METHOD_CARD,
                amount_cents=5000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                reference="ch_full_refund",
            )
            session.add(payment)
            await session.commit()

    asyncio.run(_seed_payment())

    event = {
        "id": "evt_charge_full_refund",
        "type": "charge.refunded",
        "created": int(datetime.now(tz=timezone.utc).timestamp()),
        "data": {
            "object": {
                "id": "ch_full_refund",
                "payment_intent": "pi_full_refund",
                "amount": 5000,
                "amount_refunded": 5000,
            }
        },
    }
    app.state.stripe_client = SimpleNamespace(verify_webhook=lambda payload, signature: event)

    response = client.post("/v1/payments/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1"})
    assert response.status_code == 200
    assert response.json()["processed"] is True

    async def _fetch_payment() -> tuple[int, str, str]:
        async with async_session_maker() as session:
            payment = await session.scalar(
                sa.select(Payment).where(Payment.invoice_id == invoice_id)
            )
            invoice = await session.get(Invoice, invoice_id)
            assert payment is not None
            assert invoice is not None
            return payment.amount_cents, payment.status, invoice.status

    amount_cents, payment_status, invoice_status = asyncio.run(_fetch_payment())
    assert amount_cents == 0
    assert payment_status == invoice_statuses.PAYMENT_STATUS_FAILED
    assert invoice_status == invoice_statuses.INVOICE_STATUS_SENT


def test_charge_refund_keeps_invoice_paid_when_overpaid(
    client, async_session_maker, monkeypatch
):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    invoice_id = asyncio.run(
        _seed_invoice(async_session_maker, status=invoice_statuses.INVOICE_STATUS_PAID)
    )

    async def _seed_payment() -> None:
        async with async_session_maker() as session:
            payment = Payment(
                invoice_id=invoice_id,
                provider="stripe",
                provider_ref="pi_overpay",
                payment_intent_id="pi_overpay",
                method=invoice_statuses.PAYMENT_METHOD_CARD,
                amount_cents=7000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                reference="ch_overpay",
            )
            session.add(payment)
            await session.commit()

    asyncio.run(_seed_payment())

    event = {
        "id": "evt_charge_partial_refund",
        "type": "charge.refunded",
        "created": int(datetime.now(tz=timezone.utc).timestamp()),
        "data": {
            "object": {
                "id": "ch_overpay",
                "payment_intent": "pi_overpay",
                "amount": 7000,
                "amount_refunded": 1000,
            }
        },
    }
    app.state.stripe_client = SimpleNamespace(verify_webhook=lambda payload, signature: event)

    response = client.post("/v1/payments/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1"})
    assert response.status_code == 200
    assert response.json()["processed"] is True

    async def _fetch_payment() -> tuple[int, str]:
        async with async_session_maker() as session:
            payment = await session.scalar(
                sa.select(Payment).where(Payment.invoice_id == invoice_id)
            )
            invoice = await session.get(Invoice, invoice_id)
            assert payment is not None
            assert invoice is not None
            return payment.amount_cents, invoice.status

    amount_cents, invoice_status = asyncio.run(_fetch_payment())
    assert amount_cents == 6000
    assert invoice_status == invoice_statuses.INVOICE_STATUS_PAID


def test_charge_refund_recalculates_invoice_with_multiple_payments(
    client, async_session_maker, monkeypatch
):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    invoice_id = asyncio.run(
        _seed_invoice(async_session_maker, status=invoice_statuses.INVOICE_STATUS_PAID)
    )

    async def _seed_payments() -> None:
        async with async_session_maker() as session:
            payments = [
                Payment(
                    invoice_id=invoice_id,
                    provider="stripe",
                    provider_ref="pi_partial_cover",
                    payment_intent_id="pi_partial_cover",
                    method=invoice_statuses.PAYMENT_METHOD_CARD,
                    amount_cents=3000,
                    currency="CAD",
                    status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                    reference="ch_partial_cover",
                ),
                Payment(
                    invoice_id=invoice_id,
                    provider="stripe",
                    provider_ref="pi_multi_refund",
                    payment_intent_id="pi_multi_refund",
                    method=invoice_statuses.PAYMENT_METHOD_CARD,
                    amount_cents=2000,
                    currency="CAD",
                    status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                    reference="ch_multi_refund",
                ),
            ]
            session.add_all(payments)
            await session.commit()

    asyncio.run(_seed_payments())

    event = {
        "id": "evt_charge_multi_refund",
        "type": "charge.refunded",
        "created": int(datetime.now(tz=timezone.utc).timestamp()),
        "data": {
            "object": {
                "id": "ch_multi_refund",
                "payment_intent": "pi_multi_refund",
                "amount": 2000,
                "amount_refunded": 2000,
            }
        },
    }
    app.state.stripe_client = SimpleNamespace(verify_webhook=lambda payload, signature: event)

    response = client.post("/v1/payments/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1"})
    assert response.status_code == 200
    assert response.json()["processed"] is True

    async def _fetch_payment_state() -> tuple[int, str]:
        async with async_session_maker() as session:
            amount_cents = await session.scalar(
                sa.select(sa.func.coalesce(sa.func.sum(Payment.amount_cents), 0)).where(
                    Payment.invoice_id == invoice_id,
                    Payment.status == invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                )
            )
            invoice = await session.get(Invoice, invoice_id)
            assert invoice is not None
            return int(amount_cents or 0), invoice.status

    paid_cents, invoice_status = asyncio.run(_fetch_payment_state())
    assert paid_cents == 3000
    assert invoice_status == invoice_statuses.INVOICE_STATUS_PARTIAL


def test_charge_dispute_creates_and_closes_dispute(client, async_session_maker, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    booking_id = asyncio.run(_seed_booking(async_session_maker))

    async def _seed_payment() -> None:
        async with async_session_maker() as session:
            payment = Payment(
                booking_id=booking_id,
                provider="stripe",
                provider_ref="pi_dispute",
                payment_intent_id="pi_dispute",
                method=invoice_statuses.PAYMENT_METHOD_CARD,
                amount_cents=5000,
                currency="CAD",
                status=invoice_statuses.PAYMENT_STATUS_SUCCEEDED,
                reference="ch_dispute",
            )
            session.add(payment)
            await session.commit()

    asyncio.run(_seed_payment())

    created_event = {
        "id": "evt_dispute_created",
        "type": "charge.dispute.created",
        "created": int(datetime.now(tz=timezone.utc).timestamp()),
        "data": {
            "object": {
                "id": "dp_test",
                "charge": "ch_dispute",
                "reason": "fraudulent",
                "status": "needs_response",
            }
        },
    }
    app.state.stripe_client = SimpleNamespace(verify_webhook=lambda payload, signature: created_event)
    response = client.post("/v1/payments/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1"})
    assert response.status_code == 200
    assert response.json()["processed"] is True

    closed_event = {
        "id": "evt_dispute_closed",
        "type": "charge.dispute.closed",
        "created": int(datetime.now(tz=timezone.utc).timestamp()),
        "data": {
            "object": {
                "id": "dp_test",
                "charge": "ch_dispute",
                "reason": "fraudulent",
                "status": "lost",
            }
        },
    }
    app.state.stripe_client = SimpleNamespace(verify_webhook=lambda payload, signature: closed_event)
    response = client.post("/v1/payments/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1"})
    assert response.status_code == 200
    assert response.json()["processed"] is True

    async def _fetch_dispute() -> Dispute:
        async with async_session_maker() as session:
            dispute = await session.scalar(
                sa.select(Dispute).where(Dispute.opened_by == "stripe:dp_test")
            )
            assert dispute is not None
            return dispute

    dispute = asyncio.run(_fetch_dispute())
    assert dispute.state == dispute_schemas.DisputeState.CLOSED.value
    assert dispute.reason == "fraudulent"


def test_unresolvable_invoice_event_is_ignored(client, async_session_maker, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    event = {
        "id": "evt_invoice_unresolvable",
        "type": "invoice.payment_succeeded",
        "created": int(datetime.now(tz=timezone.utc).timestamp()),
        "data": {"object": {"id": "in_missing", "amount_paid": 5000, "currency": "CAD"}},
    }
    app.state.stripe_client = SimpleNamespace(verify_webhook=lambda payload, signature: event)

    response = client.post("/v1/payments/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "t=1"})
    assert response.status_code == 200
    assert response.json()["processed"] is False
