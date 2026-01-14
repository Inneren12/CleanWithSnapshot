import base64
import csv
import io
import uuid
from datetime import datetime, timezone

import pytest

from app.domain.bookings.db_models import Team
from app.domain.saas.db_models import Organization
from app.domain.workers.db_models import Worker
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def _dispatch_credentials():
    original = {
        "dispatcher_basic_username": settings.dispatcher_basic_username,
        "dispatcher_basic_password": settings.dispatcher_basic_password,
    }
    settings.dispatcher_basic_username = "dispatch"
    settings.dispatcher_basic_password = "secret"
    yield
    for key, value in original.items():
        setattr(settings, key, value)


@pytest.mark.anyio
async def test_admin_worker_bulk_archive_unarchive_org_scoped(client, async_session_maker):
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    async with async_session_maker() as session:
        session.add_all([Organization(org_id=org_a, name="Org A"), Organization(org_id=org_b, name="Org B")])
        await session.flush()
        team_a = Team(org_id=org_a, name="Team A")
        team_b = Team(org_id=org_b, name="Team B")
        session.add_all([team_a, team_b])
        await session.flush()
        worker_one = Worker(org_id=org_a, team_id=team_a.team_id, name="Worker One", phone="111")
        worker_two = Worker(org_id=org_a, team_id=team_a.team_id, name="Worker Two", phone="222")
        worker_other = Worker(org_id=org_b, team_id=team_b.team_id, name="Worker Other", phone="333")
        session.add_all([worker_one, worker_two, worker_other])
        await session.commit()

    headers = {**_basic_auth("dispatch", "secret"), "X-Test-Org": str(org_a)}
    archive_resp = client.post(
        "/v1/admin/ui/workers/bulk/archive",
        headers=headers,
        data={"worker_ids": [worker_one.worker_id, worker_two.worker_id, worker_other.worker_id]},
        follow_redirects=False,
    )
    assert archive_resp.status_code == 303

    async with async_session_maker() as session:
        archived_one = await session.get(Worker, worker_one.worker_id)
        archived_two = await session.get(Worker, worker_two.worker_id)
        untouched_other = await session.get(Worker, worker_other.worker_id)
        assert archived_one is not None
        assert archived_one.archived_at is not None
        assert archived_one.is_active is False
        assert archived_two is not None
        assert archived_two.archived_at is not None
        assert archived_two.is_active is False
        assert untouched_other is not None
        assert untouched_other.archived_at is None

    unarchive_resp = client.post(
        "/v1/admin/ui/workers/bulk/unarchive",
        headers=headers,
        data={"worker_ids": [worker_one.worker_id, worker_two.worker_id]},
        follow_redirects=False,
    )
    assert unarchive_resp.status_code == 303

    async with async_session_maker() as session:
        unarchived_one = await session.get(Worker, worker_one.worker_id)
        unarchived_two = await session.get(Worker, worker_two.worker_id)
        assert unarchived_one is not None
        assert unarchived_one.archived_at is None
        assert unarchived_one.is_active is True
        assert unarchived_two is not None
        assert unarchived_two.archived_at is None
        assert unarchived_two.is_active is True


@pytest.mark.anyio
async def test_admin_workers_export_selected_csv_safe(client, async_session_maker):
    org_id = uuid.uuid4()
    async with async_session_maker() as session:
        session.add(Organization(org_id=org_id, name="Org CSV"))
        await session.flush()
        team = Team(org_id=org_id, name="CSV Team")
        session.add(team)
        await session.flush()
        worker_safe = Worker(org_id=org_id, team_id=team.team_id, name="=CSV Danger", phone="555")
        worker_ok = Worker(org_id=org_id, team_id=team.team_id, name="Normal Worker", phone="666")
        session.add_all([worker_safe, worker_ok])
        await session.commit()

    headers = {**_basic_auth("dispatch", "secret"), "X-Test-Org": str(org_id)}
    export_resp = client.post(
        "/v1/admin/ui/workers/export_selected",
        headers=headers,
        data={"worker_ids": [worker_safe.worker_id, worker_ok.worker_id]},
    )
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"].startswith("text/csv")
    assert "'=CSV Danger" in export_resp.text
    rows = list(csv.DictReader(io.StringIO(export_resp.text)))
    assert rows
    assert set(rows[0].keys()) == {
        "worker_id",
        "name",
        "phone",
        "email",
        "role",
        "team_id",
        "team_name",
        "is_active",
        "archived_at",
        "rating_avg",
        "rating_count",
        "skills",
        "created_at",
    }


@pytest.mark.anyio
async def test_admin_workers_export_filtered_org_scoped(client, async_session_maker):
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    async with async_session_maker() as session:
        session.add_all([Organization(org_id=org_a, name="Org A"), Organization(org_id=org_b, name="Org B")])
        await session.flush()
        team_a = Team(org_id=org_a, name="Team A")
        team_b = Team(org_id=org_b, name="Team B")
        session.add_all([team_a, team_b])
        await session.flush()
        archived_time = datetime.now(tz=timezone.utc)
        worker_archived = Worker(
            org_id=org_a,
            team_id=team_a.team_id,
            name="Archived A",
            phone="111",
            archived_at=archived_time,
        )
        worker_other = Worker(
            org_id=org_b,
            team_id=team_b.team_id,
            name="Archived B",
            phone="222",
            archived_at=archived_time,
        )
        session.add_all([worker_archived, worker_other])
        await session.commit()

    headers = {**_basic_auth("dispatch", "secret"), "X-Test-Org": str(org_a)}
    export_resp = client.get(
        "/v1/admin/ui/workers/export?format=csv&status=archived",
        headers=headers,
    )
    assert export_resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(export_resp.text)))
    assert len(rows) == 1
    assert rows[0]["name"] == "Archived A"
