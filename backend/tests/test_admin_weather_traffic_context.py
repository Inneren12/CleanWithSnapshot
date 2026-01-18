from __future__ import annotations

import pytest

from app.domain.dashboard import schemas as dashboard_schemas
from app.domain.dashboard import weather_traffic as dashboard_weather_traffic
from app.domain.feature_modules import service as feature_service
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.settings import settings


@pytest.mark.anyio
async def test_weather_traffic_provider_disabled_returns_warning(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Weather Traffic Org")
        owner = await saas_service.create_user(session, "weather-owner@org.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await feature_service.upsert_org_feature_overrides(
            session,
            org.org_id,
            {"dashboard.weather_traffic": True},
        )
        await session.commit()

    settings.weather_traffic_mode = "off"
    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/context/weather_traffic",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["warning"] is True
    assert payload["weather_now"] == {
        "temp": None,
        "wind_kph": None,
        "precip_mm": None,
        "snow_cm": None,
    }
    assert payload["next_6h"] == []
    assert payload["risk_level"] == "low"


@pytest.mark.anyio
async def test_weather_traffic_preserves_zero_values(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Weather Traffic Zero Org")
        owner = await saas_service.create_user(session, "weather-zero@org.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await feature_service.upsert_org_feature_overrides(
            session,
            org.org_id,
            {"dashboard.weather_traffic": True},
        )
        await session.commit()

    settings.weather_traffic_mode = "open_meteo"

    async def _stub_fetch_weather(*, tz: str, as_of):
        return (
            dashboard_schemas.WeatherTrafficNow(
                temp=0.0,
                wind_kph=0.0,
                precip_mm=0.0,
                snow_cm=0.0,
            ),
            [
                dashboard_schemas.WeatherTrafficHour(
                    starts_at="2024-01-01T08:00:00-07:00",
                    precip_mm=0.0,
                    snow_cm=0.0,
                )
            ],
            False,
        )

    async def _stub_fetch_traffic(*, as_of):
        return "low", "Traffic is flowing normally.", False

    monkeypatch.setattr(dashboard_weather_traffic, "_fetch_weather", _stub_fetch_weather)
    monkeypatch.setattr(dashboard_weather_traffic, "_fetch_traffic", _stub_fetch_traffic)

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/context/weather_traffic?org_timezone=America/Edmonton",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["weather_now"] == {
        "temp": 0.0,
        "wind_kph": 0.0,
        "precip_mm": 0.0,
        "snow_cm": 0.0,
    }
    assert payload["next_6h"][0]["precip_mm"] == 0.0
    assert payload["next_6h"][0]["snow_cm"] == 0.0
