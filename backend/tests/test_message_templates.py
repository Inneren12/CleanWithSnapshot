import base64
import uuid

import pytest
import sqlalchemy as sa

from app.domain.bookings.db_models import Team
from app.domain.message_templates.db_models import MessageTemplate
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole, User
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
    user = await session.scalar(sa.select(User).where(User.email == admin_email))
    if user is None:
        user = await saas_service.create_user(session, admin_email, password=None)
    membership = await saas_service.create_membership(
        session, org, user, MembershipRole.ADMIN, is_active=True
    )
    team = Team(org_id=org_id, name=f"Team {org_id}")
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
async def test_message_templates_crud_and_scope(client, async_session_maker):
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    admin_email = settings.admin_basic_username or "admin@example.com"

    async with async_session_maker() as session:
        await _seed_org(session, org_a, admin_email)
        await _seed_org(session, org_b, admin_email)
        await session.commit()

    response = client.post(
        "/v1/admin/ui/message-templates",
        data={"name": "Arrival note", "body": "We will start at 9am."},
        headers=_admin_headers(admin_email, "secret", org_a),
        follow_redirects=False,
    )
    assert response.status_code == 303

    async with async_session_maker() as session:
        template = await session.scalar(
            sa.select(MessageTemplate).where(MessageTemplate.org_id == org_a)
        )
        assert template is not None
        template_id = template.template_id

    response = client.post(
        f"/v1/admin/ui/message-templates/{template_id}",
        data={"name": "Arrival reminder", "body": "We will start at 9:15am."},
        headers=_admin_headers(admin_email, "secret", org_a),
        follow_redirects=False,
    )
    assert response.status_code == 303

    response = client.post(
        f"/v1/admin/ui/message-templates/{template_id}",
        data={"name": "Bad edit", "body": "No access."},
        headers=_admin_headers(admin_email, "secret", org_b),
        follow_redirects=False,
    )
    assert response.status_code == 404

    response = client.post(
        f"/v1/admin/ui/message-templates/{template_id}/delete",
        headers=_admin_headers(admin_email, "secret", org_a),
        follow_redirects=False,
    )
    assert response.status_code == 303

    async with async_session_maker() as session:
        remaining = await session.scalar(
            sa.select(sa.func.count(MessageTemplate.template_id)).where(
                MessageTemplate.org_id == org_a
            )
        )
        assert remaining == 0


@pytest.mark.anyio
async def test_broadcast_delivery_to_selected_workers(client, async_session_maker):
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    admin_email = settings.admin_basic_username or "admin@example.com"

    async with async_session_maker() as session:
        team_a, _admin_membership_id = await _seed_org(session, org_a, admin_email)
        team_b, _admin_membership_b_id = await _seed_org(session, org_b, admin_email)
        worker_one = await _seed_worker(
            session,
            org_id=org_a,
            team_id=team_a.team_id,
            name="Worker One",
            phone="101-101",
            password="workerone",
        )
        worker_two = await _seed_worker(
            session,
            org_id=org_a,
            team_id=team_a.team_id,
            name="Worker Two",
            phone="202-202",
            password="workertwo",
        )
        worker_other_org = await _seed_worker(
            session,
            org_id=org_b,
            team_id=team_b.team_id,
            name="Worker Other",
            phone="303-303",
            password="workerother",
        )
        await session.commit()

    response = client.post(
        "/v1/admin/ui/workers/bulk/announce",
        data={"worker_ids": [str(worker_one.worker_id)], "announcement_body": "Team update."},
        headers=_admin_headers(admin_email, "secret", org_a),
        follow_redirects=False,
    )
    assert response.status_code == 303

    threads_response = client.get(
        "/v1/worker/chat/threads",
        headers=_basic_auth(worker_one.phone, "workerone"),
    )
    assert threads_response.status_code == 200
    threads = threads_response.json()
    assert len(threads) == 1
    assert threads[0]["thread_type"] == "group"

    thread_id = threads[0]["thread_id"]
    messages_response = client.get(
        f"/v1/worker/chat/threads/{thread_id}/messages",
        headers=_basic_auth(worker_one.phone, "workerone"),
    )
    assert messages_response.status_code == 200
    assert messages_response.json()[0]["body"] == "Team update."

    other_threads_response = client.get(
        "/v1/worker/chat/threads",
        headers=_basic_auth(worker_two.phone, "workertwo"),
    )
    assert other_threads_response.status_code == 200
    assert other_threads_response.json() == []

    response = client.post(
        "/v1/admin/ui/workers/bulk/announce",
        data={
            "worker_ids": [str(worker_other_org.worker_id)],
            "announcement_body": "Cross-org.",
        },
        headers=_admin_headers(admin_email, "secret", org_a),
        follow_redirects=False,
    )
    assert response.status_code == 404
