import uuid
from datetime import datetime, timezone

import pytest

from app.domain.bookings.db_models import Booking
from app.domain.workers.db_models import Worker
from app.infra.auth import hash_password
from app.settings import settings


@pytest.mark.parametrize(
    "endpoint",
    [
        ("/v1/admin/config", "get"),
        ("/v1/admin/finance/reconcile/invoices", "get"),
    ],
)
def test_dispatcher_cannot_access_finance_or_config(dispatcher_client, endpoint):
    path, method = endpoint
    response = getattr(dispatcher_client, method)(path)
    assert response.status_code == 403


def test_accountant_cannot_change_pricing(accountant_client):
    response = accountant_client.post("/v1/admin/pricing/reload")
    assert response.status_code == 403


async def _seed_worker(session, *, name: str, phone: str, org_id: uuid.UUID) -> Worker:
    worker = Worker(
        org_id=org_id,
        team_id=1,
        name=name,
        phone=phone,
        password_hash=hash_password("secret", settings=settings),
        is_active=True,
    )
    session.add(worker)
    await session.flush()
    return worker


async def _seed_booking(session, *, org_id: uuid.UUID, worker_id: int) -> Booking:
    booking = Booking(
        booking_id=str(uuid.uuid4()),
        org_id=org_id,
        team_id=1,
        assigned_worker_id=worker_id,
        starts_at=datetime.now(tz=timezone.utc),
        duration_minutes=120,
        status="CONFIRMED",
    )
    session.add(booking)
    await session.flush()
    return booking


@pytest.mark.anyio
async def test_worker_only_sees_assigned_jobs(async_session_maker, client):
    org_id = settings.default_org_id
    async with async_session_maker() as session:
        worker_a = await _seed_worker(session, name="Worker A", phone="555-0001", org_id=org_id)
        worker_b = await _seed_worker(session, name="Worker B", phone="555-0002", org_id=org_id)
        booking_a = await _seed_booking(session, org_id=org_id, worker_id=worker_a.worker_id)
        booking_b = await _seed_booking(session, org_id=org_id, worker_id=worker_b.worker_id)
        await session.commit()

    login = client.post("/worker/login", auth=("555-0001", "secret"))
    assert login.status_code == 200

    own_job = client.get(f"/worker/jobs/{booking_a.booking_id}")
    assert own_job.status_code == 200

    other_job = client.get(f"/worker/jobs/{booking_b.booking_id}")
    assert other_job.status_code == 404
