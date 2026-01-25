from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.domain.config_audit import service as config_audit_service
from app.domain.feature_modules import service as feature_service
from app.domain.integrations import maps_service
from app.domain.integrations.db_models import MapsUsage
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.settings import settings


@pytest.mark.anyio
async def test_maps_distance_matrix_missing_key_returns_heuristic(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Maps Org")
        owner = await saas_service.create_user(session, "owner@maps.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await feature_service.upsert_org_feature_overrides(
            session,
            org.org_id,
            {"module.integrations": True, "integrations.maps": True},
            audit_actor=config_audit_service.system_actor("tests"),
            request_id=None,
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_maps_api_key", None)

    token = saas_service.build_access_token(owner, membership)
    response = client.post(
        "/v1/admin/maps/distance_matrix",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "origins": [{"lat": 37.77, "lng": -122.41}],
            "destinations": [{"lat": 37.78, "lng": -122.42}],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "heuristic"
    assert payload["warning"] == "missing_key"
    assert payload["matrix"][0][0]["provider"] == "heuristic"


@pytest.mark.anyio
async def test_maps_distance_matrix_tracks_quota(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Maps Usage Org")
        owner = await saas_service.create_user(session, "owner@maps-usage.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await feature_service.upsert_org_feature_overrides(
            session,
            org.org_id,
            {"module.integrations": True, "integrations.maps": True},
            audit_actor=config_audit_service.system_actor("tests"),
            request_id=None,
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_maps_api_key", "maps-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "rows": [
                    {
                        "elements": [
                            {
                                "status": "OK",
                                "distance": {"value": 1200},
                                "duration": {"value": 600},
                                "duration_in_traffic": {"value": 700},
                            },
                            {
                                "status": "OK",
                                "distance": {"value": 2400},
                                "duration": {"value": 900},
                            },
                        ]
                    }
                ],
            },
        )

    monkeypatch.setattr(maps_service, "MAPS_HTTP_TRANSPORT", httpx.MockTransport(handler))

    token = saas_service.build_access_token(owner, membership)
    response = client.post(
        "/v1/admin/maps/distance_matrix",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "origins": [{"lat": 40.71, "lng": -74.0}],
            "destinations": [
                {"lat": 40.72, "lng": -74.01},
                {"lat": 40.73, "lng": -74.02},
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "google"
    assert payload["elements_count"] == 2

    async with async_session_maker() as session:
        usage = await session.get(
            MapsUsage,
            {"org_id": org.org_id, "day": datetime.now(timezone.utc).date()},
        )
        assert usage is not None
        assert usage.count == 2


@pytest.mark.anyio
async def test_maps_quota_scoped_to_org(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Maps Org A")
        owner = await saas_service.create_user(session, "owner@maps-a.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        org_b = await saas_service.create_organization(session, "Maps Org B")
        owner_b = await saas_service.create_user(session, "owner@maps-b.com", "secret")
        membership_b = await saas_service.create_membership(session, org_b, owner_b, MembershipRole.OWNER)
        await feature_service.upsert_org_feature_overrides(
            session,
            org.org_id,
            {"module.integrations": True, "integrations.maps": True},
            audit_actor=config_audit_service.system_actor("tests"),
            request_id=None,
        )
        await feature_service.upsert_org_feature_overrides(
            session,
            org_b.org_id,
            {"module.integrations": True, "integrations.maps": True},
            audit_actor=config_audit_service.system_actor("tests"),
            request_id=None,
        )
        session.add(
            MapsUsage(
                org_id=org.org_id,
                day=datetime.now(timezone.utc).date(),
                count=5,
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_maps_api_key", None)

    token_b = saas_service.build_access_token(owner_b, membership_b)
    response = client.get(
        "/v1/admin/maps/quota",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["used"] == 0


@pytest.mark.anyio
async def test_maps_test_key_requires_owner(async_session_maker, client, monkeypatch):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Maps Org RBAC")
        owner = await saas_service.create_user(session, "owner@maps-rbac.com", "secret")
        dispatcher = await saas_service.create_user(session, "dispatcher@maps-rbac.com", "secret")
        owner_membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        dispatcher_membership = await saas_service.create_membership(
            session, org, dispatcher, MembershipRole.DISPATCHER
        )
        await feature_service.upsert_org_feature_overrides(
            session,
            org.org_id,
            {"module.integrations": True, "integrations.maps": True},
            audit_actor=config_audit_service.system_actor("tests"),
            request_id=None,
        )
        await session.commit()

    monkeypatch.setattr(settings, "google_maps_api_key", None)

    dispatcher_token = saas_service.build_access_token(dispatcher, dispatcher_membership)
    blocked = client.post(
        "/v1/admin/maps/test_key",
        headers={"Authorization": f"Bearer {dispatcher_token}"},
    )
    assert blocked.status_code == 403

    owner_token = saas_service.build_access_token(owner, owner_membership)
    allowed = client.post(
        "/v1/admin/maps/test_key",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert allowed.status_code == 200
