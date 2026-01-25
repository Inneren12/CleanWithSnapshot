import asyncio
import base64
import uuid

from app.domain.config_audit import service as config_audit_service
from app.domain.feature_modules import service as feature_service
from app.domain.saas.db_models import Organization
from app.settings import settings


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def _seed_org(async_session_maker, org_id: uuid.UUID, name: str) -> None:
    async with async_session_maker() as session:
        session.add(Organization(org_id=org_id, name=name))
        await session.commit()


async def _enable_rules_features(async_session_maker, org_id: uuid.UUID) -> None:
    async with async_session_maker() as session:
        overrides = await feature_service.get_org_feature_overrides(session, org_id)
        overrides["module.notifications_center"] = True
        overrides["notifications.rules_builder"] = True
        await feature_service.upsert_org_feature_overrides(
            session,
            org_id,
            overrides,
            audit_actor=config_audit_service.system_actor("tests"),
            request_id=None,
        )
        await session.commit()


def test_rules_rbac_owner_only(client, async_session_maker):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "admin123"
    settings.legacy_basic_auth_enabled = True

    asyncio.run(_enable_rules_features(async_session_maker, settings.default_org_id))

    owner_headers = _auth_headers("owner", "secret")
    admin_headers = _auth_headers("admin", "admin123")

    payload = {
        "name": "Owner Only Rule",
        "enabled": True,
        "trigger_type": "booking",
        "conditions_json": {"tier": "gold"},
        "actions_json": [{"type": "notify"}],
    }

    denied = client.post("/v1/admin/rules", json=payload, headers=admin_headers)
    assert denied.status_code == 403

    allowed = client.post("/v1/admin/rules", json=payload, headers=owner_headers)
    assert allowed.status_code == 201


def test_rules_org_scoped(client, async_session_maker):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    org_id = uuid.uuid4()
    asyncio.run(_seed_org(async_session_maker, org_id, "Rules Org"))
    asyncio.run(_enable_rules_features(async_session_maker, settings.default_org_id))
    asyncio.run(_enable_rules_features(async_session_maker, org_id))

    owner_headers = _auth_headers("owner", "secret")
    org_headers = {**owner_headers, "X-Test-Org": str(org_id)}

    payload = {
        "name": "Org Scoped Rule",
        "enabled": True,
        "trigger_type": "booking",
    }

    create_resp = client.post("/v1/admin/rules", json=payload, headers=org_headers)
    assert create_resp.status_code == 201
    rule_id = create_resp.json()["rule_id"]

    list_default = client.get("/v1/admin/rules", headers=owner_headers)
    assert list_default.status_code == 200
    assert all(item["rule_id"] != rule_id for item in list_default.json())

    get_default = client.get(f"/v1/admin/rules/{rule_id}", headers=owner_headers)
    assert get_default.status_code == 404

    list_org = client.get("/v1/admin/rules", headers=org_headers)
    assert list_org.status_code == 200
    assert any(item["rule_id"] == rule_id for item in list_org.json())


def test_rule_test_endpoint_deterministic(client, async_session_maker):
    settings.owner_basic_username = "owner"
    settings.owner_basic_password = "secret"
    settings.legacy_basic_auth_enabled = True

    asyncio.run(_enable_rules_features(async_session_maker, settings.default_org_id))

    owner_headers = _auth_headers("owner", "secret")

    create_payload = {
        "name": "Deterministic Rule",
        "enabled": True,
        "trigger_type": "booking",
        "conditions_json": {"tier": "gold"},
        "actions_json": [{"type": "notify"}],
    }

    create_resp = client.post("/v1/admin/rules", json=create_payload, headers=owner_headers)
    assert create_resp.status_code == 201
    rule_id = create_resp.json()["rule_id"]

    test_payload = {
        "rule_id": rule_id,
        "payload": {"tier": "gold"},
        "trigger_type": "booking",
    }

    first = client.post("/v1/admin/rules/test", json=test_payload, headers=owner_headers)
    second = client.post("/v1/admin/rules/test", json=test_payload, headers=owner_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["matched"] is True
    assert first.json()["actions_json"] == []
    assert first.json()["dry_run"] is True
