import uuid
from datetime import datetime, timezone

import pytest

from app.domain.notifications_center.db_models import NotificationEvent, NotificationRead
from app.domain.rules import service as rules_service
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole


async def _create_event(session, org_id: uuid.UUID, priority: str) -> NotificationEvent:
    event = NotificationEvent(
        org_id=org_id,
        priority=priority,
        type="worker_no_show",
        title="Worker no-show",
        body="A worker did not show up for the shift.",
        entity_type="booking",
        entity_id="booking-1",
        action_href="/admin/schedule",
        action_kind="open_booking",
    )
    session.add(event)
    await session.flush()
    return event


def _user_key(user_id: uuid.UUID) -> str:
    return f"saas:{user_id}"


@pytest.mark.anyio
async def test_notifications_org_scoping(async_session_maker, client):
    async with async_session_maker() as session:
        org_one = await saas_service.create_organization(session, "Org One")
        org_two = await saas_service.create_organization(session, "Org Two")
        owner = await saas_service.create_user(session, "owner@org-one.com", "secret")
        membership = await saas_service.create_membership(session, org_one, owner, MembershipRole.OWNER)

        event_one = await _create_event(session, org_one.org_id, "HIGH")
        await _create_event(session, org_two.org_id, "HIGH")
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/notifications?filter=all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == [str(event_one.id)]


@pytest.mark.anyio
async def test_notifications_unread_filter(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Org Unread")
        owner = await saas_service.create_user(session, "owner@unread.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)

        read_event = await _create_event(session, org.org_id, "LOW")
        unread_event = await _create_event(session, org.org_id, "LOW")
        session.add(
            NotificationRead(
                org_id=org.org_id,
                user_id=_user_key(owner.user_id),
                event_id=read_event.id,
                read_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/notifications?filter=unread",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == [str(unread_event.id)]


@pytest.mark.anyio
async def test_notifications_mark_read_self_scoped(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Org Self Scope")
        owner = await saas_service.create_user(session, "owner@self.com", "secret")
        viewer = await saas_service.create_user(session, "viewer@self.com", "secret")
        owner_membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        viewer_membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)

        event = await _create_event(session, org.org_id, "MED")
        await session.commit()

    owner_token = saas_service.build_access_token(owner, owner_membership)
    mark_response = client.post(
        f"/v1/admin/notifications/{event.id}/read",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert mark_response.status_code == 200

    viewer_token = saas_service.build_access_token(viewer, viewer_membership)
    viewer_response = client.get(
        "/v1/admin/notifications?filter=unread",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert viewer_response.status_code == 200
    viewer_payload = viewer_response.json()
    assert [item["id"] for item in viewer_payload["items"]] == [str(event.id)]

    owner_unread_response = client.get(
        "/v1/admin/notifications?filter=unread",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert owner_unread_response.status_code == 200
    owner_payload = owner_unread_response.json()
    assert owner_payload["items"] == []


@pytest.mark.anyio
async def test_notifications_urgent_filter(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Org Urgent")
        owner = await saas_service.create_user(session, "owner@urgent.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)

        await _create_event(session, org.org_id, "CRITICAL")
        await _create_event(session, org.org_id, "HIGH")
        await _create_event(session, org.org_id, "MED")
        await _create_event(session, org.org_id, "LOW")
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/notifications?filter=urgent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    priorities = {item["priority"] for item in payload["items"]}
    assert priorities == {"CRITICAL", "HIGH"}


@pytest.mark.anyio
async def test_rules_action_event_appears_in_notifications_feed(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Org Rules Feed")
        owner = await saas_service.create_user(session, "owner@rules-feed.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        rule = await rules_service.create_rule(
            session,
            org.org_id,
            {
                "name": "Rules Feed Event",
                "enabled": True,
                "dry_run": False,
                "trigger_type": "payment_failed",
                "conditions_json": {"status": "failed"},
                "actions_json": [
                    {
                        "type": "create_notification_event",
                        "priority": "high",
                        "event_type": "payment_failed",
                        "title": "Payment failed",
                        "body": "Invoice failed.",
                        "entity_type": "invoice",
                        "entity_id": "inv_42",
                        "action_href": "/admin/invoices/inv_42",
                        "action_kind": "open_invoice",
                    }
                ],
            },
        )
        await session.commit()

    async with async_session_maker() as session:
        await rules_service.evaluate_rules_for_trigger(
            session,
            org_id=org.org_id,
            trigger_type=rule.trigger_type,
            payload={"status": "failed"},
            occurred_at=None,
            entity_type="invoice",
            entity_id="inv_42",
            idempotency_key=None,
            execute_actions=True,
        )
        await session.commit()

    token = saas_service.build_access_token(owner, membership)
    response = client.get(
        "/v1/admin/notifications?filter=all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Payment failed"
    assert items[0]["priority"] == "HIGH"
    assert items[0]["entity_id"] == "inv_42"
