"""
Tests for streaming upload security: no full-buffer reads, size limits, content-type gating.

These tests verify the fix for the DoS vulnerability where `await file.read()` loaded
entire uploads into memory before any size checks were applied.
"""
import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.domain.bookings.db_models import Booking
from app.domain.leads.db_models import Lead
from app.main import app
from app.settings import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def _create_booking_with_consent(session_maker) -> str:
    async with session_maker() as session:
        lead = Lead(
            name="Stream Test Lead",
            phone="780-555-9999",
            email="stream@example.com",
            postal_code="T5A",
            address="1 Stream Ave",
            preferred_dates=["Mon"],
            structured_inputs={"beds": 1, "baths": 1, "cleaning_type": "standard"},
            estimate_snapshot={
                "price_cents": 5000,
                "subtotal_cents": 5000,
                "tax_cents": 0,
                "pricing_config_version": "v1",
                "config_hash": "h",
                "line_items": [],
            },
            pricing_config_version="v1",
            config_hash="h",
        )
        session.add(lead)
        await session.commit()
        await session.refresh(lead)

        booking = Booking(
            org_id=settings.default_org_id,
            team_id=1,
            lead_id=lead.lead_id,
            starts_at=datetime.now(tz=timezone.utc),
            duration_minutes=60,
            status="CONFIRMED",
            consent_photos=True,
        )
        session.add(booking)
        await session.commit()
        await session.refresh(booking)
        return booking.booking_id


async def _get_quota_state(session_maker):
    from app.domain.storage_quota import service as storage_quota_service

    async with session_maker() as session:
        snapshot = await storage_quota_service.get_org_storage_quota_snapshot(session, settings.default_org_id)
        return snapshot.storage_bytes_used, snapshot.storage_bytes_pending


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def upload_root(tmp_path):
    original_root = settings.order_upload_root
    settings.order_upload_root = str(tmp_path)
    app.state.storage_backend = None
    yield tmp_path
    settings.order_upload_root = original_root
    app.state.storage_backend = None


@pytest.fixture()
def admin_headers():
    original_username = settings.admin_basic_username
    original_password = settings.admin_basic_password
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    yield _basic_auth_header("admin", "secret")
    settings.admin_basic_username = original_username
    settings.admin_basic_password = original_password


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_upload_valid_small_image_returns_201(client, async_session_maker, upload_root, admin_headers):
    """A valid small image upload should succeed with 201."""
    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

    response = client.post(
        f"/v1/orders/{booking_id}/photos",
        data={"phase": "AFTER"},
        files={"file": ("photo.jpg", b"JFIF-data-here", "image/jpeg")},
        headers=admin_headers,
    )

    assert response.status_code == 201


def test_upload_missing_content_length_succeeds(client, async_session_maker, upload_root, admin_headers):
    """Upload without Content-Length header (or empty) should succeed."""
    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

    # Simulate missing Content-Length by sending an empty string, which triggers
    # the same fallback path as a missing header.
    headers = {**admin_headers, "Content-Length": ""}

    response = client.post(
        f"/v1/orders/{booking_id}/photos",
        data={"phase": "AFTER"},
        files={"file": ("photo.jpg", b"JFIF-data", "image/jpeg")},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["size_bytes"] > 0


def test_upload_skips_content_length_quota_gating(
    client, async_session_maker, upload_root, admin_headers, monkeypatch
):
    """Multipart Content-Length must not be used for storage entitlement bytes gating."""
    from app.api import entitlements

    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

    async def _should_not_be_called(request, bytes_to_add, session):
        raise AssertionError(f"unexpected entitlement bytes check: {bytes_to_add}")

    monkeypatch.setattr(entitlements, "enforce_storage_entitlement", _should_not_be_called)

    response = client.post(
        f"/v1/orders/{booking_id}/photos",
        data={"phase": "AFTER"},
        files={"file": ("near-limit.jpg", b"X" * 32, "image/jpeg")},
        headers=admin_headers,
    )

    assert response.status_code == 201


def test_upload_finalizes_with_actual_not_exceeding_reserved(
    client, async_session_maker, upload_root, admin_headers, monkeypatch
):
    """Finalize must never be called with actual_bytes greater than reserved bytes."""
    from sqlalchemy import select

    from app.domain.storage_quota import service as storage_quota_service
    from app.domain.storage_quota.db_models import OrgStorageReservation

    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))
    original_finalize = storage_quota_service.finalize_reservation

    async def _checked_finalize(session, reservation_id, actual_bytes, *, audit_identity=None):
        result = await session.execute(
            select(OrgStorageReservation).where(OrgStorageReservation.reservation_id == reservation_id)
        )
        reservation = result.scalar_one()
        assert actual_bytes <= reservation.bytes_reserved
        return await original_finalize(
            session,
            reservation_id,
            actual_bytes,
            audit_identity=audit_identity,
        )

    monkeypatch.setattr(storage_quota_service, "finalize_reservation", _checked_finalize)

    response = client.post(
        f"/v1/orders/{booking_id}/photos",
        data={"phase": "AFTER"},
        files={"file": ("finalize-check.jpg", b"Y" * (96 * 1024), "image/jpeg")},
        headers=admin_headers,
    )

    assert response.status_code == 201


def test_upload_quota_enforcement_on_actual_bytes(client, async_session_maker, upload_root, admin_headers):
    """Quota enforcement must reject uploads that exceed the remaining quota during streaming."""
    from app.domain.org_settings.service import get_or_create_org_settings

    # 1. Setup: Limit org storage to a small amount (e.g. 50 bytes)
    async def _set_quota():
        async with async_session_maker() as session:
            settings_obj = await get_or_create_org_settings(session, settings.default_org_id)
            settings_obj.max_storage_bytes = 50
            await session.commit()

    asyncio.run(_set_quota())

    try:
        booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

        # 2. Upload file larger than 50 bytes (e.g. 100 bytes)
        content = b"X" * 100
        response = client.post(
            f"/v1/orders/{booking_id}/photos",
            data={"phase": "AFTER"},
            files={"file": ("large.jpg", content, "image/jpeg")},
            headers=admin_headers,
        )

        # 3. Expect 409 Conflict (Quota Exceeded)
        assert response.status_code == 409
        error = response.json()
        assert error["title"] == "Storage quota exceeded"
    finally:
        # Cleanup: Reset quota
        async def _reset_quota():
            async with async_session_maker() as session:
                settings_obj = await get_or_create_org_settings(session, settings.default_org_id)
                settings_obj.max_storage_bytes = None
                await session.commit()
        asyncio.run(_reset_quota())


def test_upload_quota_near_limit_allows_exact_remaining(
    client, async_session_maker, upload_root, admin_headers
):
    """Uploads that exactly fit remaining quota should pass, but overage must fail."""
    from app.domain.org_settings.service import get_or_create_org_settings

    async def _set_quota(max_bytes: int):
        async with async_session_maker() as session:
            settings_obj = await get_or_create_org_settings(session, settings.default_org_id)
            settings_obj.max_storage_bytes = max_bytes
            settings_obj.storage_bytes_used = 0
            await session.commit()

    async def _reset_quota():
        async with async_session_maker() as session:
            settings_obj = await get_or_create_org_settings(session, settings.default_org_id)
            settings_obj.max_storage_bytes = None
            settings_obj.storage_bytes_used = 0
            await session.commit()

    asyncio.run(_set_quota(3 * 1024 * 1024))
    try:
        booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

        first = client.post(
            f"/v1/orders/{booking_id}/photos",
            data={"phase": "AFTER"},
            files={"file": ("first.jpg", b"A" * (1024 * 1024), "image/jpeg")},
            headers=admin_headers,
        )
        assert first.status_code == 201

        exact_remaining = client.post(
            f"/v1/orders/{booking_id}/photos",
            data={"phase": "AFTER"},
            files={"file": ("second.jpg", b"B" * (1024 * 1024), "image/jpeg")},
            headers=admin_headers,
        )
        assert exact_remaining.status_code == 201

        exceed = client.post(
            f"/v1/orders/{booking_id}/photos",
            data={"phase": "AFTER"},
            files={"file": ("third.jpg", b"C" * (1024 * 1024 + 1), "image/jpeg")},
            headers=admin_headers,
        )
        assert exceed.status_code == 409
    finally:
        asyncio.run(_reset_quota())


def test_upload_quota_exceeded_cleans_partial_local_file(
    client, async_session_maker, upload_root, admin_headers
):
    """A quota failure during streaming must not leave partial files in local storage or leak usage."""
    from app.domain.org_settings.service import get_or_create_org_settings

    async def _set_quota(max_bytes: int):
        async with async_session_maker() as session:
            settings_obj = await get_or_create_org_settings(session, settings.default_org_id)
            settings_obj.max_storage_bytes = max_bytes
            settings_obj.storage_bytes_used = 0
            await session.commit()

    async def _reset_quota():
        async with async_session_maker() as session:
            settings_obj = await get_or_create_org_settings(session, settings.default_org_id)
            settings_obj.max_storage_bytes = None
            settings_obj.storage_bytes_used = 0
            await session.commit()

    asyncio.run(_set_quota(64 * 1024))
    try:
        booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))
        used_before, pending_before = asyncio.run(_get_quota_state(async_session_maker))
        response = client.post(
            f"/v1/orders/{booking_id}/photos",
            data={"phase": "AFTER"},
            files={"file": ("too-big.jpg", b"X" * (64 * 1024 + 16), "image/jpeg")},
            headers=admin_headers,
        )

        assert response.status_code == 409
        assert not [p for p in Path(upload_root).rglob("*") if p.is_file()], "Partial upload file should be deleted"
        used_after, pending_after = asyncio.run(_get_quota_state(async_session_maker))
        assert used_after == used_before
        assert pending_before == 0
        assert pending_after == 0
    finally:
        asyncio.run(_reset_quota())


def test_upload_increments_storage_usage_correctly(client, async_session_maker, upload_root, admin_headers):
    """A successful upload increases used by exactly file bytes and leaves no pending bytes."""

    used_before, pending_before = asyncio.run(_get_quota_state(async_session_maker))
    assert pending_before == 0

    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))
    content = b"X" * 12345

    response = client.post(
        f"/v1/orders/{booking_id}/photos",
        data={"phase": "AFTER"},
        files={"file": ("usage_test.jpg", content, "image/jpeg")},
        headers=admin_headers,
    )
    assert response.status_code == 201

    used_after, pending_after = asyncio.run(_get_quota_state(async_session_maker))
    assert used_after == used_before + len(content)
    assert pending_after == 0


def test_upload_oversized_file_returns_413(client, async_session_maker, upload_root, admin_headers):
    """An upload whose Content-Length exceeds the configured limit must be rejected with 413
    without the server loading the payload into memory first."""
    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

    original_max = settings.order_photo_max_bytes
    settings.order_photo_max_bytes = 100  # tiny limit for this test
    try:
        oversized_content = b"X" * 200  # well above the 100-byte limit
        response = client.post(
            f"/v1/orders/{booking_id}/photos",
            data={"phase": "AFTER"},
            files={"file": ("big.jpg", oversized_content, "image/jpeg")},
            headers=admin_headers,
        )
    finally:
        settings.order_photo_max_bytes = original_max

    assert response.status_code == 413


def test_upload_invalid_content_type_returns_415(client, async_session_maker, upload_root, admin_headers):
    """Uploads with a disallowed content-type must be rejected with 415."""
    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

    response = client.post(
        f"/v1/orders/{booking_id}/photos",
        data={"phase": "AFTER"},
        files={"file": ("script.js", b"alert('xss')", "application/javascript")},
        headers=admin_headers,
    )

    assert response.status_code == 415


def test_upload_pdf_content_type_returns_415(client, async_session_maker, upload_root, admin_headers):
    """PDF uploads must be rejected with 415 (only images are allowed)."""
    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

    response = client.post(
        f"/v1/orders/{booking_id}/photos",
        data={"phase": "AFTER"},
        files={"file": ("doc.pdf", b"%PDF-1.4 fake-pdf", "application/pdf")},
        headers=admin_headers,
    )

    assert response.status_code == 415


def test_upload_does_not_full_read_file(client, async_session_maker, upload_root, admin_headers, monkeypatch):
    """The upload endpoint must NOT call file.read() without a chunk size (streaming guard).

    This test monkey-patches UploadFile.read to raise a hard error if read() is ever
    called without an explicit chunk size (i.e., size == -1, which reads the entire
    file into memory).  A 201 response proves the endpoint streamed the body correctly.
    """
    from fastapi import UploadFile

    full_reads: list[str] = []
    original_read = UploadFile.read

    async def _guarded_read(self, size: int = -1) -> bytes:
        if size < 0:
            # Record the violation but still forward the call so the test can
            # observe the error rather than crashing the server process.
            full_reads.append(f"read() called without chunk size (size={size})")
        return await original_read(self, size)

    monkeypatch.setattr(UploadFile, "read", _guarded_read)

    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

    response = client.post(
        f"/v1/orders/{booking_id}/photos",
        data={"phase": "AFTER"},
        files={"file": ("stream.jpg", b"JFIF-small-payload", "image/jpeg")},
        headers=admin_headers,
    )

    assert response.status_code == 201, (
        f"Expected 201 but got {response.status_code}: {response.text}"
    )
    assert not full_reads, (
        "Streaming DoS regression: upload endpoint called file.read() without a "
        f"chunk size — full buffer read detected: {full_reads}"
    )


def test_upload_png_allowed(client, async_session_maker, upload_root, admin_headers):
    """PNG files must be accepted."""
    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

    response = client.post(
        f"/v1/orders/{booking_id}/photos",
        data={"phase": "BEFORE"},
        files={"file": ("photo.png", b"\x89PNG\r\n\x1a\n-fake", "image/png")},
        headers=admin_headers,
    )

    assert response.status_code == 201


def test_upload_webp_allowed(client, async_session_maker, upload_root, admin_headers):
    """WebP files must be accepted."""
    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

    response = client.post(
        f"/v1/orders/{booking_id}/photos",
        data={"phase": "BEFORE"},
        files={"file": ("photo.webp", b"RIFFfakeWEBPfake", "image/webp")},
        headers=admin_headers,
    )

    assert response.status_code == 201
