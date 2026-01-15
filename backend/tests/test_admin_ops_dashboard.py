import pytest

from app.domain.org_settings import service as org_settings_service
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole


@pytest.mark.anyio
async def test_ops_dashboard_returns_schema_and_timezone(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Ops Dashboard Org")
        owner = await saas_service.create_user(session, "ops-dashboard@org.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        org_settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        org_settings.timezone = "America/Denver"
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/dashboard/ops",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["org_timezone"] == "America/Denver"
    assert payload["as_of"]
    assert isinstance(payload["critical_alerts"], list)
    assert isinstance(payload["upcoming_events"], list)
    assert isinstance(payload["worker_availability"], list)
    assert "booking_status_today" in payload
    booking_status = payload["booking_status_today"]
    assert set(booking_status.keys()) == {"bands", "totals"}
    assert set(booking_status["totals"].keys()) == {
        "total",
        "pending",
        "confirmed",
        "done",
        "cancelled",
    }
