import base64
import uuid

import pytest

from app.domain.bookings.db_models import Team
from app.domain.chat_threads import service as chat_service
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.domain.workers.db_models import Worker
from app.infra.auth import hash_password
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _admin_headers(username: str, password: str, org_id: uuid.UUID) -> dict[str, str]:
    headers = _basic_auth(username, password)
    headers["X-Test-Org"] = str(org_id)
    return headers


@pytest.fixture(autouse=True)
def admin_credentials():
    original_username = settings.admin_basic_username
    original_password = settings.admin_basic_password
    settings.admin_basic_username = "admin@example.com"
    settings.admin_basic_password = "secret"
    try:
        yield
    finally:
        settings.admin_basic_username = original_username
        settings.admin_basic_password = original_password


async def _seed_org(session, org_id: uuid.UUID, admin_email: str) -> tuple[Team, int]:
    org = await saas_service.ensure_org(session, org_id, name=f"Org {org_id}")
    user = await saas_service.create_user(session, admin_email, password=None)
    membership = await saas_service.create_membership(
        session, org, user, MembershipRole.ADMIN, is_active=True
    )
    team = Team(org_id=org_id, name="Team A")
    session.add(team)
    await session.flush()
    return team, membership.membership_id


async def _seed_worker(
    session,
    *,
    org_id: uuid.UUID,
    team_id: int,
    name: str,
    phone: str,
    password: str,
) -> Worker:
    worker = Worker(
        org_id=org_id,
        team_id=team_id,
        name=name,
        phone=phone,
        password_hash=hash_password(password, settings=settings),
    )
    session.add(worker)
    await session.flush()
    return worker


@pytest.mark.anyio
async def test_chat_org_scoping_for_admin(client, async_session_maker):
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    admin_email = settings.admin_basic_username or "admin@example.com"
    async with async_session_maker() as session:
        team_a, admin_membership_id = await _seed_org(session, org_a, admin_email)
        worker_a = await _seed_worker(
            session,
            org_id=org_a,
            team_id=team_a.team_id,
            name="Worker A",
            phone="111-111",
            password="workerpass",
        )
        thread = await chat_service.get_or_create_direct_thread(
            session,
            org_id=org_a,
            worker_id=worker_a.worker_id,
            admin_membership_id=admin_membership_id,
        )
        await session.commit()

    response = client.get(
        f"/v1/admin/chat/threads/{thread.thread_id}/messages",
        headers=_admin_headers(admin_email, "secret", org_b),
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_worker_access_own_thread_only(client, async_session_maker):
    org_id = uuid.uuid4()
    admin_email = settings.admin_basic_username or "admin@example.com"
    async with async_session_maker() as session:
        team, admin_membership_id = await _seed_org(session, org_id, admin_email)
        worker_one = await _seed_worker(
            session,
            org_id=org_id,
            team_id=team.team_id,
            name="Worker One",
            phone="222-222",
            password="workerone",
        )
        worker_two = await _seed_worker(
            session,
            org_id=org_id,
            team_id=team.team_id,
            name="Worker Two",
            phone="333-333",
            password="workertwo",
        )
        thread = await chat_service.get_or_create_direct_thread(
            session,
            org_id=org_id,
            worker_id=worker_one.worker_id,
            admin_membership_id=admin_membership_id,
        )
        await session.commit()

    response = client.get(
        f"/v1/worker/chat/threads/{thread.thread_id}/messages",
        headers=_basic_auth(worker_one.phone, "workerone"),
    )
    assert response.status_code == 200

    response = client.get(
        f"/v1/worker/chat/threads/{thread.thread_id}/messages",
        headers=_basic_auth(worker_two.phone, "workertwo"),
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_unread_count_updates_on_mark_read(client, async_session_maker):
    org_id = uuid.uuid4()
    admin_email = settings.admin_basic_username or "admin@example.com"
    async with async_session_maker() as session:
        team, admin_membership_id = await _seed_org(session, org_id, admin_email)
        worker = await _seed_worker(
            session,
            org_id=org_id,
            team_id=team.team_id,
            name="Worker Read",
            phone="444-444",
            password="workerread",
        )
        thread = await chat_service.get_or_create_direct_thread(
            session,
            org_id=org_id,
            worker_id=worker.worker_id,
            admin_membership_id=admin_membership_id,
        )
        await session.commit()

    send_response = client.post(
        f"/v1/admin/chat/threads/{thread.thread_id}/messages",
        json={"body": "Hello worker"},
        headers=_admin_headers(admin_email, "secret", org_id),
    )
    assert send_response.status_code == 200

    response = client.get(
        "/v1/worker/chat/threads",
        headers=_basic_auth(worker.phone, "workerread"),
    )
    assert response.status_code == 200
    unread = next(
        item["unread_count"]
        for item in response.json()
        if item["thread_id"] == str(thread.thread_id)
    )
    assert unread == 1

    mark_response = client.post(
        f"/v1/worker/chat/threads/{thread.thread_id}/read",
        headers=_basic_auth(worker.phone, "workerread"),
    )
    assert mark_response.status_code == 200

    response = client.get(
        "/v1/worker/chat/threads",
        headers=_basic_auth(worker.phone, "workerread"),
    )
    unread = next(
        item["unread_count"]
        for item in response.json()
        if item["thread_id"] == str(thread.thread_id)
    )
    assert unread == 0


@pytest.mark.anyio
async def test_worker_unread_badge_count_endpoint(client, async_session_maker):
    org_id = uuid.uuid4()
    admin_email = settings.admin_basic_username or "admin@example.com"
    async with async_session_maker() as session:
        team, admin_membership_id = await _seed_org(session, org_id, admin_email)
        worker = await _seed_worker(
            session,
            org_id=org_id,
            team_id=team.team_id,
            name="Worker Badge",
            phone="555-555",
            password="workerbadge",
        )
        thread = await chat_service.get_or_create_direct_thread(
            session,
            org_id=org_id,
            worker_id=worker.worker_id,
            admin_membership_id=admin_membership_id,
        )
        await session.commit()

    send_response = client.post(
        f"/v1/admin/chat/threads/{thread.thread_id}/messages",
        json={"body": "Unread badge check"},
        headers=_admin_headers(admin_email, "secret", org_id),
    )
    assert send_response.status_code == 200

    response = client.get(
        "/v1/worker/chat/unread-count",
        headers=_basic_auth(worker.phone, "workerbadge"),
    )
    assert response.status_code == 200
    assert response.json()["unread_count"] == 1

    mark_response = client.post(
        f"/v1/worker/chat/threads/{thread.thread_id}/read",
        headers=_basic_auth(worker.phone, "workerbadge"),
    )
    assert mark_response.status_code == 200

    response = client.get(
        "/v1/worker/chat/unread-count",
        headers=_basic_auth(worker.phone, "workerbadge"),
    )
    assert response.status_code == 200
    assert response.json()["unread_count"] == 0


@pytest.mark.anyio
async def test_worker_stream_requires_participant(client, async_session_maker):
    org_id = uuid.uuid4()
    admin_email = settings.admin_basic_username or "admin@example.com"
    async with async_session_maker() as session:
        team, admin_membership_id = await _seed_org(session, org_id, admin_email)
        worker_one = await _seed_worker(
            session,
            org_id=org_id,
            team_id=team.team_id,
            name="Worker Stream One",
            phone="666-666",
            password="workerone",
        )
        worker_two = await _seed_worker(
            session,
            org_id=org_id,
            team_id=team.team_id,
            name="Worker Stream Two",
            phone="777-777",
            password="workertwo",
        )
        thread = await chat_service.get_or_create_direct_thread(
            session,
            org_id=org_id,
            worker_id=worker_one.worker_id,
            admin_membership_id=admin_membership_id,
        )
        await session.commit()

    response = client.get(
        f"/v1/worker/chat/threads/{thread.thread_id}/stream",
        headers=_basic_auth(worker_two.phone, "workertwo"),
    )
    assert response.status_code == 403
