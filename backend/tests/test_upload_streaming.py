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
from app.domain.org_settings.db_models import OrganizationSettings
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
    body = response.json()
    assert body["content_type"] == "image/jpeg"
    assert body["size_bytes"] > 0


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


def test_upload_without_content_length_does_not_500(
    client, async_session_maker, upload_root, admin_headers, monkeypatch
):
    """Uploads should stream successfully even when Content-Length is unavailable."""
    from starlette.datastructures import Headers

    original_get = Headers.get

    def _headers_get(self, key, default=None):
        if str(key).lower() == "content-length":
            return None
        return original_get(self, key, default)

    monkeypatch.setattr(Headers, "get", _headers_get)

    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

    response = client.post(
        f"/v1/orders/{booking_id}/photos",
        data={"phase": "AFTER"},
        files={"file": ("chunked-like.jpg", b"chunked-stream-payload", "image/jpeg")},
        headers=admin_headers,
    )

    assert response.status_code == 201, response.text


def test_upload_quota_uses_streamed_file_bytes_not_request_content_length(
    client, async_session_maker, upload_root, admin_headers, monkeypatch
):
    """Quota enforcement must use actual streamed bytes, not multipart Content-Length."""
    from starlette.datastructures import Headers

    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

    async def _set_max_storage():
        async with async_session_maker() as session:
            settings_row = await session.get(OrganizationSettings, settings.default_org_id)
            assert settings_row is not None
            settings_row.max_storage_bytes = 64
            settings_row.storage_bytes_used = 0
            await session.commit()

    asyncio.run(_set_max_storage())

    original_get = Headers.get

    def _headers_get(self, key, default=None):
        if str(key).lower() == "content-length":
            # Simulate multipart overhead / inflated body size hint.
            return "5000"
        return original_get(self, key, default)

    monkeypatch.setattr(Headers, "get", _headers_get)

    original_max = settings.order_photo_max_bytes
    settings.order_photo_max_bytes = 10_000
    try:
        response = client.post(
            f"/v1/orders/{booking_id}/photos",
            data={"phase": "AFTER"},
            files={"file": ("small.jpg", b"small-file", "image/jpeg")},
            headers=admin_headers,
        )
    finally:
        settings.order_photo_max_bytes = original_max

    assert response.status_code == 201, response.text
