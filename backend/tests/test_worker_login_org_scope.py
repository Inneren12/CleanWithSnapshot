import uuid

import pytest

from app.domain.bookings.db_models import Team
from app.domain.saas.db_models import Organization
from app.domain.workers.db_models import Worker
from app.infra.auth import hash_password
from app.settings import settings


@pytest.fixture(autouse=True)
def _disable_env_worker_auth():
    original = (settings.worker_basic_username, settings.worker_basic_password, settings.worker_portal_secret)
    settings.worker_basic_username = None
    settings.worker_basic_password = None
    settings.worker_portal_secret = "test-worker-secret"
    yield
    settings.worker_basic_username, settings.worker_basic_password, settings.worker_portal_secret = original


@pytest.mark.anyio
async def test_worker_login_requires_org_id(async_session_maker, client_no_raise):
    response = client_no_raise.post("/worker/login", auth=("555-1010", "secret"))
    assert response.status_code == 422


@pytest.mark.anyio
async def test_worker_login_scoped_by_org(async_session_maker, client_no_raise):
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    async with async_session_maker() as session:
        session.add_all(
            [
                Organization(org_id=org_a, name="Worker Login Org A"),
                Organization(org_id=org_b, name="Worker Login Org B"),
            ]
        )
        team_a = Team(org_id=org_a, name=f"Team A {org_a}")
        team_b = Team(org_id=org_b, name=f"Team B {org_b}")
        session.add_all([team_a, team_b])
        await session.flush()

        session.add(
            Worker(
                org_id=org_b,
                team_id=team_b.team_id,
                name="Worker B",
                phone="555-1010",
                password_hash=hash_password("secret", settings=settings),
                is_active=True,
            )
        )
        await session.commit()

    success = client_no_raise.post("/worker/login", auth=("555-1010", "secret"), json={"org_id": str(org_b)})
    assert success.status_code == 200

    wrong_org = client_no_raise.post(
        "/worker/login", auth=("555-1010", "secret"), json={"org_id": str(org_a)}
    )
    assert wrong_org.status_code == 401
    assert wrong_org.json()["detail"] == "Invalid phone or password"

    wrong_phone = client_no_raise.post("/worker/login", auth=("555-9999", "secret"), json={"org_id": str(org_b)})
    assert wrong_phone.status_code == 401
    assert wrong_phone.json()["detail"] == "Invalid phone or password"
