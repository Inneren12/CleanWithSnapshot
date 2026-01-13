import base64

import pytest

from app.domain.bookings.service import ensure_default_team
from app.settings import settings


def _basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(autouse=True)
def _reset_dispatch_creds():
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
async def test_admin_can_create_team_and_booking_form_lists_teams(client, async_session_maker):
    async with async_session_maker() as session:
        default_team = await ensure_default_team(session)
        await session.commit()

    headers = _basic_auth("dispatch", "secret")
    create_resp = client.post(
        "/v1/admin/teams",
        headers=headers,
        json={"name": "Crew B"},
    )
    assert create_resp.status_code == 200

    list_resp = client.get("/v1/admin/teams", headers=headers)
    assert list_resp.status_code == 200
    payload = list_resp.json()
    team_names = {team["name"] for team in payload}
    assert default_team.name in team_names
    assert "Crew B" in team_names

    form_resp = client.get("/v1/admin/ui/bookings/new", headers=headers)
    assert form_resp.status_code == 200
    assert default_team.name in form_resp.text
    assert "Crew B" in form_resp.text
