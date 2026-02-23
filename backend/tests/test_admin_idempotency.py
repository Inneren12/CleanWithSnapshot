import asyncio
import threading
from datetime import datetime, timezone
import base64
import uuid

import sqlalchemy as sa
from fastapi import Request
from httpx import Response as HTTPXResponse, Request as HTTPXRequest

from app.api.idempotency import _request_fingerprint, require_idempotency
from app.domain.admin_idempotency import AdminIdempotency
from app.domain.bookings.db_models import EmailEvent
from app.domain.export_events.db_models import ExportEvent
from app.domain.invoices import service as invoice_service
from app.domain.invoices import statuses as invoice_statuses
from app.domain.invoices.db_models import Invoice, Payment
from app.domain.ops import service as ops_service
from app.infra.security import InMemoryRateLimiter
from app.settings import settings


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _bootstrap_invoice(async_session_maker) -> str:
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    async def _create() -> str:
        async with async_session_maker() as session:
            invoice = Invoice(
                invoice_number=f"INV-{uuid.uuid4()}",
                status=invoice_statuses.INVOICE_STATUS_DRAFT,
                issue_date=datetime.now(tz=timezone.utc).date(),
                due_date=None,
                currency="CAD",
                subtotal_cents=1000,
                tax_cents=0,
                total_cents=1000,
                notes="manual",
                created_by="admin",
            )
            session.add(invoice)
            await session.commit()
            await session.refresh(invoice)
            return invoice.invoice_id

    return asyncio.run(_create())


def test_payment_idempotency_prevents_duplicate(client, async_session_maker):
    invoice_id = _bootstrap_invoice(async_session_maker)
    admin_headers = _auth_headers("admin", "secret")

    first = client.post(
        f"/v1/admin/invoices/{invoice_id}/record-payment",
        headers={**admin_headers, "Idempotency-Key": "pay-once"},
        json={"amount_cents": 500, "method": "cash"},
    )
    assert first.status_code == 201

    second = client.post(
        f"/v1/admin/invoices/{invoice_id}/record-payment",
        headers={**admin_headers, "Idempotency-Key": "pay-once"},
        json={"amount_cents": 500, "method": "cash"},
    )
    assert second.status_code == 201

    async def _count_payments() -> int:
        async with async_session_maker() as session:
            result = await session.execute(
                sa.select(sa.func.count()).select_from(Payment).where(Payment.invoice_id == invoice_id)
            )
            return int(result.scalar_one())

    payment_count = asyncio.run(_count_payments())
    assert payment_count == 1


def test_idempotency_conflict_returns_409(client, async_session_maker):
    invoice_id = _bootstrap_invoice(async_session_maker)
    admin_headers = _auth_headers("admin", "secret")

    first = client.post(
        f"/v1/admin/invoices/{invoice_id}/record-payment",
        headers={**admin_headers, "Idempotency-Key": "conflict-key"},
        json={"amount_cents": 500, "method": "cash"},
    )
    assert first.status_code == 201

    conflict = client.post(
        f"/v1/admin/invoices/{invoice_id}/record-payment",
        headers={**admin_headers, "Idempotency-Key": "conflict-key"},
        json={"amount_cents": 700, "method": "cash"},
    )
    assert conflict.status_code == 409


class RecordingAdapter:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_email(
        self, recipient: str, subject: str, body: str, headers: dict[str, str] | None = None
    ) -> bool:
        self.sent.append((recipient, subject, body))
        return True


def test_resend_email_event_idempotent(client, async_session_maker):
    settings.dispatcher_basic_username = "admin"
    settings.dispatcher_basic_password = "secret"
    client.app.state.email_adapter = RecordingAdapter()

    async def _seed_event() -> EmailEvent:
        async with async_session_maker() as session:
            event = EmailEvent(
                org_id=settings.default_org_id,
                email_type="booking_pending",
                recipient="idem@example.com",
                subject="Test",
                body="Hello",
                dedupe_key=f"test-{uuid.uuid4()}",
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            return event

    event = asyncio.run(_seed_event())
    headers = _auth_headers("admin", "secret")

    first = client.post(
        f"/v1/admin/messaging/events/{event.event_id}/resend",
        headers={**headers, "Idempotency-Key": "resend-event"},
    )
    assert first.status_code == 202

    repeat = client.post(
        f"/v1/admin/messaging/events/{event.event_id}/resend",
        headers={**headers, "Idempotency-Key": "resend-event"},
    )
    assert repeat.status_code == 202
    assert len(client.app.state.email_adapter.sent) == 1


def test_replay_rate_limit_triggers(client, async_session_maker, monkeypatch):
    original_limiter = client.app.state.action_rate_limiter
    client.app.state.action_rate_limiter = InMemoryRateLimiter(1)
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    # Disable private-IP blocking so DNS resolution is skipped; the test
    # environment has no outbound DNS and example.com would fail lookup.
    monkeypatch.setattr(settings, "export_webhook_block_private_ips", False)

    async def _seed_event() -> ExportEvent:
        async with async_session_maker() as session:
            event = ExportEvent(
                org_id=settings.default_org_id,
                mode="webhook",
                target_url="https://example.com/webhook",
                payload={"demo": True},
                attempts=0,
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            return event

    event = asyncio.run(_seed_event())
    client.app.state.export_transport = lambda request: HTTPXResponse(200, request=HTTPXRequest("POST", request.url))
    headers = {**_auth_headers("admin", "secret"), "Idempotency-Key": "replay-limit"}

    try:
        first = client.post(f"/v1/admin/export-dead-letter/{event.event_id}/replay", headers=headers)
        assert first.status_code == 202

        limited = client.post(f"/v1/admin/export-dead-letter/{event.event_id}/replay", headers=headers)
        assert limited.status_code == 429
    finally:
        client.app.state.action_rate_limiter = original_limiter


def test_resend_email_event_concurrent_same_key_claim_first(client, async_session_maker, monkeypatch):
    settings.dispatcher_basic_username = "admin"
    settings.dispatcher_basic_password = "secret"

    async def _seed_event() -> EmailEvent:
        async with async_session_maker() as session:
            event = EmailEvent(
                org_id=settings.default_org_id,
                email_type="booking_pending",
                recipient="idem-concurrency@example.com",
                subject="Test",
                body="Hello",
                dedupe_key=f"test-{uuid.uuid4()}",
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            return event

    event = asyncio.run(_seed_event())
    headers = _auth_headers("admin", "secret")

    lock = threading.Lock()
    call_count = 0
    first_started = threading.Event()
    release_first = threading.Event()

    async def _fake_resend_email_event(session, adapter, org_id, event_id):  # noqa: ARG001
        nonlocal call_count
        with lock:
            call_count += 1
            current_call = call_count
        if current_call == 1:
            first_started.set()
            release_first.wait(timeout=2)
        return {"event_id": event_id, "status": "delivered"}

    monkeypatch.setattr(ops_service, "resend_email_event", _fake_resend_email_event)

    responses: list[tuple[int, dict[str, str]]] = []

    def _send_request() -> None:
        response = client.post(
            f"/v1/admin/messaging/events/{event.event_id}/resend",
            headers={**headers, "Idempotency-Key": "concurrent-resend"},
        )
        responses.append((response.status_code, dict(response.headers)))

    first_thread = threading.Thread(target=_send_request)
    second_thread = threading.Thread(target=_send_request)

    first_thread.start()
    assert first_started.wait(timeout=2)
    second_thread.start()
    release_first.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert call_count == 1
    assert len(responses) == 2
    statuses = sorted(status for status, _ in responses)
    assert statuses == [202, 202]

    replay = client.post(
        f"/v1/admin/messaging/events/{event.event_id}/resend",
        headers={**headers, "Idempotency-Key": "concurrent-resend"},
    )
    assert replay.status_code == 202
    assert call_count == 1


def test_resend_email_event_pending_key_returns_409(client, async_session_maker, monkeypatch):
    settings.dispatcher_basic_username = "admin"
    settings.dispatcher_basic_password = "secret"

    async def _seed_pending() -> tuple[str, str]:
        async with async_session_maker() as session:
            event = EmailEvent(
                org_id=settings.default_org_id,
                email_type="booking_pending",
                recipient="idem-pending@example.com",
                subject="Test",
                body="Hello",
                dedupe_key=f"test-{uuid.uuid4()}",
            )
            session.add(event)
            await session.flush()
            path = f"/v1/admin/messaging/events/{event.event_id}/resend"
            request = HTTPXRequest("POST", f"http://testserver{path}")
            request_hash = _request_fingerprint(request, "")
            pending = AdminIdempotency(
                org_id=settings.default_org_id,
                key="pending-resend",
                endpoint="resend_email_event",
                request_hash=request_hash,
                response_status=AdminIdempotency.STATUS_PENDING,
                response_body_json=None,
            )
            session.add(pending)
            await session.commit()
            return event.event_id, request_hash

    event_id, _request_hash = asyncio.run(_seed_pending())
    headers = _auth_headers("admin", "secret")

    called = False

    async def _unexpected_call(*args, **kwargs):  # noqa: ARG001
        nonlocal called
        called = True
        return {"event_id": event_id, "status": "delivered"}

    monkeypatch.setattr(ops_service, "resend_email_event", _unexpected_call)

    response = client.post(
        f"/v1/admin/messaging/events/{event_id}/resend",
        headers={**headers, "Idempotency-Key": "pending-resend"},
    )
    assert response.status_code == 409
    assert response.headers.get("retry-after") == "1"
    assert called is False


def test_resend_email_event_failed_key_replays_failure_not_pending(client, async_session_maker, monkeypatch):
    settings.dispatcher_basic_username = "admin"
    settings.dispatcher_basic_password = "secret"

    async def _seed_failed() -> str:
        async with async_session_maker() as session:
            event = EmailEvent(
                org_id=settings.default_org_id,
                email_type="booking_pending",
                recipient="idem-failed@example.com",
                subject="Test",
                body="Hello",
                dedupe_key=f"test-{uuid.uuid4()}",
            )
            session.add(event)
            await session.flush()
            path = f"/v1/admin/messaging/events/{event.event_id}/resend"
            request = HTTPXRequest("POST", f"http://testserver{path}")
            request_hash = _request_fingerprint(request, "")
            failed = AdminIdempotency(
                org_id=settings.default_org_id,
                key="failed-resend",
                endpoint="resend_email_event",
                request_hash=request_hash,
                response_status=AdminIdempotency.STATUS_FAILED,
                response_body_json={
                    "detail": "Request processing failed",
                    "status": 500,
                    "title": "Internal Server Error",
                },
            )
            session.add(failed)
            await session.commit()
            return event.event_id

    event_id = asyncio.run(_seed_failed())
    headers = _auth_headers("admin", "secret")

    called = False

    async def _unexpected_call(*args, **kwargs):  # noqa: ARG001
        nonlocal called
        called = True
        return {"event_id": event_id, "status": "delivered"}

    monkeypatch.setattr(ops_service, "resend_email_event", _unexpected_call)

    response = client.post(
        f"/v1/admin/messaging/events/{event_id}/resend",
        headers={**headers, "Idempotency-Key": "failed-resend"},
    )
    assert response.status_code == 500
    assert response.headers.get("retry-after") is None
    assert response.json() == {
        "detail": "Request processing failed",
        "status": 500,
        "title": "Internal Server Error",
    }
    assert called is False


def test_require_idempotency_uses_get_bind_when_bind_is_none(async_session_maker):
    async def _run() -> None:
        async with async_session_maker() as session:
            class SessionProxy:
                bind = None

                def __init__(self, wrapped):
                    self._wrapped = wrapped
                    self.get_bind_called = False

                def get_bind(self):
                    self.get_bind_called = True
                    return self._wrapped.get_bind()

                async def execute(self, *args, **kwargs):
                    return await self._wrapped.execute(*args, **kwargs)

            proxy = SessionProxy(session)
            org_id = settings.default_org_id
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/v1/admin/messaging/events/abc/resend",
                "headers": [(b"idempotency-key", b"proxy-bind")],
                "query_string": b"",
                "scheme": "http",
                "server": ("testserver", 80),
                "client": ("testclient", 50000),
            }

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            request = Request(scope, receive)
            result = await require_idempotency(request, proxy, org_id, "resend_email_event")
            assert proxy.get_bind_called is True
            assert hasattr(result, "claimed_record")
            assert getattr(result, "existing_response", None) is None

    asyncio.run(_run())


def test_record_payment_concurrent_same_key_executes_once(client, async_session_maker, monkeypatch):
    """Two concurrent requests with the same idempotency key must not double-charge.

    The claim-first INSERT ... ON CONFLICT DO NOTHING guarantees that only the
    request that wins the atomic INSERT will execute the side-effect (payment
    creation).  The losing request receives a 201 replay once the first
    completes.  In both cases exactly one Payment row must exist.

    The blocking technique (release_first.wait) pins the asyncio event loop to
    Thread 1, so Thread 2's request is only processed after Thread 1 fully
    commits.  This sidesteps SQLite StaticPool's single-connection limitation
    while still exercising the claim-first idempotency guarantee.
    """
    invoice_id = _bootstrap_invoice(async_session_maker)
    admin_headers = _auth_headers("admin", "secret")

    lock = threading.Lock()
    call_count = 0
    first_started = threading.Event()
    release_first = threading.Event()

    real_record = invoice_service.record_manual_payment

    async def _slow_record_manual_payment(**kwargs):
        nonlocal call_count
        with lock:
            call_count += 1
            current_call = call_count
        payment = await real_record(**kwargs)
        if current_call == 1:
            first_started.set()
            release_first.wait(timeout=2)  # block event loop; Thread 2 queued
        return payment

    monkeypatch.setattr(invoice_service, "record_manual_payment", _slow_record_manual_payment)

    responses: list[int] = []

    def _send() -> None:
        r = client.post(
            f"/v1/admin/invoices/{invoice_id}/record-payment",
            headers={**admin_headers, "Idempotency-Key": "pay-concurrent-charge"},
            json={"amount_cents": 500, "method": "cash"},
        )
        responses.append(r.status_code)

    t1 = threading.Thread(target=_send)
    t2 = threading.Thread(target=_send)

    t1.start()
    assert first_started.wait(timeout=5), "Thread 1 never reached slow payment handler"
    t2.start()
    release_first.set()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert call_count == 1, f"Payment handler called {call_count} times; expected 1"
    assert len(responses) == 2
    statuses = sorted(responses)
    # Thread 1 (winner) returns 201.  Thread 2 (loser) sees the PENDING record
    # while Thread 1 is still in-flight, so it gets 409 Retry-After; once
    # Thread 1 commits and Thread 2 retries, it would receive 201 replay.
    assert statuses in ([201, 201], [201, 409]), f"Unexpected status codes: {statuses}"

    async def _count_payments() -> int:
        async with async_session_maker() as session:
            result = await session.execute(
                sa.select(sa.func.count()).select_from(Payment).where(Payment.invoice_id == invoice_id)
            )
            return int(result.scalar_one())

    payment_count = asyncio.run(_count_payments())
    assert payment_count == 1, f"Expected exactly 1 payment, found {payment_count}"
