from __future__ import annotations

from datetime import datetime, timedelta, timezone

import anyio

from app.domain.bookings.db_models import Booking
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice
from app.domain.notifications_center.db_models import NotificationEvent
from app.domain.notifications_digests import service as digest_service
from app.domain.notifications_digests.db_models import NotificationDigestSetting
from app.jobs import notifications_digests
from app.infra.email import NoopEmailAdapter
from app.settings import settings


class _RecordingEmailAdapter:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_email(self, recipient: str, subject: str, body: str) -> bool:
        self.sent.append((recipient, subject, body))
        return True


def test_digest_payload_deterministic(async_session_maker):
    now = datetime(2026, 2, 1, 15, 0, 0, tzinfo=timezone.utc)

    async def _seed() -> None:
        async with async_session_maker() as session:
            session.add(
                NotificationEvent(
                    priority="CRITICAL",
                    type="payment_failed",
                    title="Payment failed",
                    body="Invoice INV-1 payment failed.",
                    entity_type="invoice",
                    entity_id="INV-1",
                    action_href="/admin/invoices/INV-1",
                    action_kind="open_invoice",
                )
            )
            session.add(
                Booking(
                    team_id=1,
                    lead_id=None,
                    starts_at=now,
                    duration_minutes=60,
                    status="CONFIRMED",
                )
            )
            session.add(
                Invoice(
                    invoice_number="INV-1",
                    order_id=None,
                    customer_id=None,
                    status=invoice_statuses.INVOICE_STATUS_SENT,
                    issue_date=now.date(),
                    due_date=(now - timedelta(days=2)).date(),
                    currency="CAD",
                    subtotal_cents=10000,
                    taxable_subtotal_cents=0,
                    tax_cents=0,
                    total_cents=10000,
                )
            )
            await session.commit()

    async def _build_payload() -> digest_service.DigestPayload:
        async with async_session_maker() as session:
            return await digest_service.build_digest_payload(
                session,
                org_id=settings.default_org_id,
                digest_key="daily_summary",
                recipients=["owner@example.com"],
                now=now,
            )

    anyio.run(_seed)
    payload = anyio.run(_build_payload)

    assert payload.subject == "Daily summary digest"
    assert "Digest: daily_summary" in payload.body
    assert "- Payment failed" in payload.body
    assert "Today's bookings summary:" in payload.body
    assert "- Confirmed: 1" in payload.body
    assert "Overdue invoices snapshot:" in payload.body
    assert "- Count: 1" in payload.body
    assert "- Total outstanding cents: 10000" in payload.body


def test_digest_job_skips_when_email_disabled(async_session_maker):
    now = datetime(2026, 2, 1, 15, 0, 0, tzinfo=timezone.utc)

    async def _seed() -> None:
        async with async_session_maker() as session:
            session.add(
                NotificationDigestSetting(
                    digest_key="daily_summary",
                    enabled=True,
                    schedule="daily",
                    recipients=["owner@example.com"],
                )
            )
            await session.commit()

    async def _run_job() -> dict[str, int]:
        async with async_session_maker() as session:
            return await notifications_digests.run_notifications_digest(
                session,
                NoopEmailAdapter(),
                schedule="daily",
                now=now,
            )

    anyio.run(_seed)
    result = anyio.run(_run_job)

    assert result["sent"] == 0
    assert result["skipped"] == 1


def test_digest_job_gates_by_period(async_session_maker):
    now = datetime(2026, 2, 1, 9, 0, 0, tzinfo=timezone.utc)
    next_day = now + timedelta(days=1)

    async def _seed() -> None:
        async with async_session_maker() as session:
            session.add(
                NotificationDigestSetting(
                    digest_key="daily_summary",
                    enabled=True,
                    schedule="daily",
                    recipients=["owner@example.com"],
                )
            )
            await session.commit()

    async def _run(run_at: datetime) -> dict[str, int]:
        async with async_session_maker() as session:
            adapter = _RecordingEmailAdapter()
            result = await notifications_digests.run_notifications_digest(
                session,
                adapter,
                schedule="daily",
                now=run_at,
            )
            result["sent_emails"] = len(adapter.sent)
            return result

    anyio.run(_seed)
    first = anyio.run(_run, now)
    second = anyio.run(_run, now)
    third = anyio.run(_run, next_day)

    assert first["sent"] == 1
    assert first["sent_emails"] == 1
    assert second["sent"] == 0
    assert second["skipped"] == 1
    assert third["sent"] == 1
