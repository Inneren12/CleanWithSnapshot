import datetime as dt
import uuid

import pytest

from app.domain.dispatcher import alert_state_store
from app.domain.saas.service import ensure_org


@pytest.mark.anyio
async def test_alert_state_store_sms_gate(async_session_maker):
    now = dt.datetime.now(dt.timezone.utc)
    org_id = uuid.uuid4()
    async with async_session_maker() as session:
        await ensure_org(session, org_id, name="Alert Store Org")
        await session.commit()
        store = alert_state_store.get_alert_state_store(session)
        allowed_first = await store.allow_sms_send(
            org_id,
            "late-worker:booking-1",
            now,
            dt.timedelta(minutes=30),
        )
        allowed_second = await store.allow_sms_send(
            org_id,
            "late-worker:booking-1",
            now + dt.timedelta(minutes=5),
            dt.timedelta(minutes=30),
        )

    assert allowed_first is True
    assert allowed_second is False


@pytest.mark.anyio
async def test_alert_state_store_ack_and_org_scope(async_session_maker):
    now = dt.datetime.now(dt.timezone.utc)
    org_id = uuid.uuid4()
    other_org_id = uuid.uuid4()
    async with async_session_maker() as session:
        await ensure_org(session, org_id, name="Primary Org")
        await ensure_org(session, other_org_id, name="Other Org")
        await session.commit()
        store = alert_state_store.get_alert_state_store(session)
        await store.ack(org_id, "alert-key-1", now + dt.timedelta(minutes=30))
        is_acked_primary = await store.is_acked(org_id, "alert-key-1", now)
        is_acked_other = await store.is_acked(other_org_id, "alert-key-1", now)
        is_acked_expired = await store.is_acked(
            org_id,
            "alert-key-1",
            now + dt.timedelta(minutes=31),
        )

    assert is_acked_primary is True
    assert is_acked_other is False
    assert is_acked_expired is False
