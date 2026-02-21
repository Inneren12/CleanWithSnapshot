import asyncio

import pytest

from app.domain.org_settings import service as org_settings_service
from app.domain.saas import service as saas_service
from app.domain.storage_quota import service as storage_quota_service
from app.domain.storage_quota.db_models import OrgStorageReservation
from app.jobs import storage_quota as storage_quota_job
from app.infra.metrics import metrics


def _counter_value(counter, **labels) -> float:
    if labels:
        return counter.labels(**labels)._value.get()
    return counter._value.get()


@pytest.mark.anyio
async def test_storage_quota_unlimited_allows_reservations(async_session_maker):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Unlimited Storage Org")
        settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        settings.max_storage_bytes = None
        await session.commit()

    async with async_session_maker() as session:
        reservation = await storage_quota_service.reserve_bytes(
            session,
            org.org_id,
            512,
            resource_type="order_photo",
            resource_id="photo-1",
        )
        await storage_quota_service.finalize_reservation(session, reservation.reservation_id, 512)
        await session.commit()

    async with async_session_maker() as session:
        snapshot = await storage_quota_service.get_org_storage_quota_snapshot(session, org.org_id)
        assert snapshot.max_storage_bytes is None
        assert snapshot.storage_bytes_used == 512


@pytest.mark.anyio
async def test_storage_quota_allows_remaining_rejects_over(async_session_maker):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Quota Storage Org")
        settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        settings.max_storage_bytes = 100
        await session.commit()

    async with async_session_maker() as session:
        reservation = await storage_quota_service.reserve_bytes(session, org.org_id, 60)
        await storage_quota_service.finalize_reservation(session, reservation.reservation_id, 60)
        await session.commit()

    async with async_session_maker() as session:
        baseline = _counter_value(metrics.org_storage_quota_rejections, reason="hard_limit")
        with pytest.raises(storage_quota_service.OrgStorageQuotaExceeded):
            await storage_quota_service.reserve_bytes(session, org.org_id, 50)
        assert _counter_value(metrics.org_storage_quota_rejections, reason="hard_limit") == baseline + 1


@pytest.mark.anyio
async def test_storage_quota_zero_blocks(async_session_maker):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Zero Storage Org")
        settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        settings.max_storage_bytes = 0
        await session.commit()

    async with async_session_maker() as session:
        with pytest.raises(storage_quota_service.OrgStorageQuotaExceeded):
            await storage_quota_service.reserve_bytes(session, org.org_id, 1)


@pytest.mark.anyio
async def test_storage_quota_concurrent_reservations(async_session_maker):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Concurrent Storage Org")
        settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        settings.max_storage_bytes = 100
        await session.commit()

    async def _attempt() -> str:
        async with async_session_maker() as session:
            try:
                reservation = await storage_quota_service.reserve_bytes(session, org.org_id, 60)
                await storage_quota_service.finalize_reservation(session, reservation.reservation_id, 60)
                await asyncio.sleep(0.05)
                await session.commit()
                return "reserved"
            except storage_quota_service.OrgStorageQuotaExceeded:
                await session.rollback()
                return "rejected"

    results = await asyncio.gather(_attempt(), _attempt())
    assert results.count("reserved") == 1


@pytest.mark.anyio
async def test_storage_quota_reservation_expiry_releases(async_session_maker):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Expire Storage Org")
        settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        settings.storage_bytes_used = 111
        await session.commit()

    async with async_session_maker() as session:
        reservation = await storage_quota_service.reserve_bytes(
            session,
            org.org_id,
            40,
            expires_in_seconds=-5,
        )
        snapshot_before = await storage_quota_service.get_org_storage_quota_snapshot(session, org.org_id)
        assert snapshot_before.storage_bytes_used == 111
        assert snapshot_before.storage_bytes_pending == 40
        await session.commit()

    async with async_session_maker() as session:
        result = await storage_quota_job.run_storage_quota_cleanup(session)
        assert result["expired"] >= 1

    async with async_session_maker() as session:
        db_reservation = await session.get(OrgStorageReservation, reservation.reservation_id)
        assert db_reservation is not None
        assert db_reservation.status == storage_quota_service.StorageReservationStatus.EXPIRED.value

        snapshot = await storage_quota_service.get_org_storage_quota_snapshot(session, org.org_id)
        assert snapshot.storage_bytes_used == 111
        assert snapshot.storage_bytes_pending == 0


@pytest.mark.anyio
async def test_storage_quota_finalize_and_delete(async_session_maker):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Finalize Storage Org")
        await org_settings_service.get_or_create_org_settings(session, org.org_id)
        await session.commit()

    async with async_session_maker() as session:
        reservation = await storage_quota_service.reserve_bytes(session, org.org_id, 80)
        await storage_quota_service.finalize_reservation(session, reservation.reservation_id, 80)
        await session.commit()

    async with async_session_maker() as session:
        await storage_quota_service.decrement_storage_usage(
            session,
            org.org_id,
            80,
            resource_type="order_photo",
            resource_id="photo-1",
        )
        await session.commit()

    async with async_session_maker() as session:
        snapshot = await storage_quota_service.get_org_storage_quota_snapshot(session, org.org_id)
        assert snapshot.storage_bytes_used == 0


@pytest.mark.anyio
async def test_storage_quota_size_mismatch_adjusts(async_session_maker):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Mismatch Storage Org")
        settings = await org_settings_service.get_or_create_org_settings(session, org.org_id)
        settings.max_storage_bytes = 200
        await session.commit()

    async with async_session_maker() as session:
        reservation = await storage_quota_service.reserve_bytes(session, org.org_id, 120)
        await storage_quota_service.finalize_reservation(session, reservation.reservation_id, 90)
        await session.commit()

    async with async_session_maker() as session:
        snapshot = await storage_quota_service.get_org_storage_quota_snapshot(session, org.org_id)
        assert snapshot.storage_bytes_used == 90
