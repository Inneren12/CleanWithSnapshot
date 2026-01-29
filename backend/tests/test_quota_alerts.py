import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from app.domain.notifications_center import db_models as notifications_models
from app.domain.org_settings import service as org_settings_service
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole
from app.jobs import quota_alerts


@pytest.mark.anyio
async def test_quota_alerts_emit_once_per_threshold(db_session):
    org_id = uuid.uuid4()
    org = await saas_service.ensure_org(db_session, org_id, name="Quota Alerts Org")
    settings_record = await org_settings_service.get_or_create_org_settings(db_session, org_id)
    settings_record.max_users = 10
    await db_session.flush()

    for idx in range(8):
        user = await saas_service.create_user(
            db_session,
            f"user-{idx}@example.com",
            "Passw0rd!",
        )
        await saas_service.create_membership(db_session, org, user, MembershipRole.ADMIN)
    await db_session.commit()

    await quota_alerts.run_quota_alerts(db_session)

    events = await db_session.scalars(
        sa.select(notifications_models.NotificationEvent).where(
            notifications_models.NotificationEvent.org_id == org_id,
            notifications_models.NotificationEvent.type == quota_alerts.EVENT_TYPE,
        )
    )
    events_list = list(events)
    assert len(events_list) == 1
    assert events_list[0].entity_type == "org_user_quota"

    await quota_alerts.run_quota_alerts(db_session)

    events_again = await db_session.scalars(
        sa.select(notifications_models.NotificationEvent).where(
            notifications_models.NotificationEvent.org_id == org_id,
            notifications_models.NotificationEvent.type == quota_alerts.EVENT_TYPE,
        )
    )
    assert len(list(events_again)) == 1

    user = await saas_service.create_user(db_session, "user-9@example.com", "Passw0rd!")
    await saas_service.create_membership(db_session, org, user, MembershipRole.ADMIN)
    await db_session.commit()

    await quota_alerts.run_quota_alerts(db_session)

    events_after = await db_session.scalars(
        sa.select(notifications_models.NotificationEvent).where(
            notifications_models.NotificationEvent.org_id == org_id,
            notifications_models.NotificationEvent.type == quota_alerts.EVENT_TYPE,
        )
    )
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    entity_ids = {event.entity_id for event in events_after}
    assert entity_ids == {f"80:{period}", f"90:{period}"}


@pytest.mark.anyio
async def test_quota_alerts_storage_threshold(db_session):
    org_id = uuid.uuid4()
    await saas_service.ensure_org(db_session, org_id, name="Storage Alerts Org")
    settings_record = await org_settings_service.get_or_create_org_settings(db_session, org_id)
    settings_record.max_storage_bytes = 100
    settings_record.storage_bytes_used = 85
    await db_session.commit()

    await quota_alerts.run_quota_alerts(db_session)

    events = await db_session.scalars(
        sa.select(notifications_models.NotificationEvent).where(
            notifications_models.NotificationEvent.org_id == org_id,
            notifications_models.NotificationEvent.type == quota_alerts.EVENT_TYPE,
            notifications_models.NotificationEvent.entity_type == "org_storage_quota",
        )
    )
    events_list = list(events)
    assert len(events_list) == 1
