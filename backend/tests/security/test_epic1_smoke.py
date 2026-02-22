"""Epic 1 verification smoke tests.

Covers the four security controls introduced in Epic 1:

  a) PR-01 – Upload streaming + size cap (413 on oversized file)
  b) PR-04 – CSRF enforcement (403 on state-changing request without token)
  c) PR-03 – Trusted-proxy header behaviour (spoofed XFF ignored)
  d) PR-02 – Stripe transaction boundary (Stripe called before DB transaction)

Run all with::

    pytest -k epic1          # name-match
    pytest -m epic1          # marker

All tests are deterministic and make zero real network calls.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.domain.bookings.db_models import Booking
from app.domain.bookings.service import LOCAL_TZ
from app.domain.leads.db_models import Lead
from app.infra.security import get_client_ip
from app.settings import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    # X-Auth-MFA mirrors the header used by test_csrf.py; admin endpoints
    # require it when settings.testing is False.
    return {"Authorization": f"Basic {token}", "X-Auth-MFA": "true"}


async def _create_booking_with_consent(session_maker) -> str:
    """Seed a confirmed booking that has photo-consent enabled."""
    async with session_maker() as session:
        lead = Lead(
            name="Epic1 Smoke Lead",
            phone="780-555-0011",
            email="epic1-smoke-upload@example.com",
            postal_code="T5A",
            address="1 Epic Ave",
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


async def _seed_lead_for_booking(session_maker) -> str:
    """Seed a lead with an estimate snapshot required for booking via API."""
    async with session_maker() as session:
        lead = Lead(
            name="Epic1 Stripe Smoke Lead",
            phone="780-555-0012",
            address="99 Smoke Street",
            email="epic1-smoke-stripe@example.com",
            preferred_dates=["Mon morning"],
            structured_inputs={"beds": 2, "baths": 1, "cleaning_type": "standard"},
            estimate_snapshot={
                "pricing_config_version": "v1",
                "config_hash": "testhash",
                "total_before_tax": 150.0,
            },
            pricing_config_version="v1",
            config_hash="testhash",
            status="NEW",
            org_id=settings.default_org_id,
        )
        session.add(lead)
        await session.commit()
        return lead.lead_id


def _future_slot() -> str:
    now = datetime.now(tz=LOCAL_TZ)
    tomorrow = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    return tomorrow.astimezone(timezone.utc).isoformat()


def _make_request(client_host: str, xff: str | None = None):
    """Build a minimal Starlette Request for unit-level IP resolution tests."""
    from starlette.requests import Request

    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": headers,
        "client": (client_host, 1234),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def upload_root(tmp_path):
    """Redirect upload storage to a throwaway temp dir and reset backend."""
    from app.main import app

    original_root = settings.order_upload_root
    settings.order_upload_root = str(tmp_path)
    app.state.storage_backend = None
    yield tmp_path
    settings.order_upload_root = original_root
    app.state.storage_backend = None


@pytest.fixture()
def admin_headers():
    """Basic-auth headers for the test admin account."""
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"
    yield _basic_auth_header("admin", "secret")
    # restore_admin_settings autouse fixture in conftest restores the originals


# ---------------------------------------------------------------------------
# (a) PR-01 — Upload streaming + size cap
# ---------------------------------------------------------------------------


@pytest.mark.epic1
def test_epic1_upload_size_cap_returns_413(client, async_session_maker, upload_root, admin_headers):
    """Epic 1 / PR-01: An upload whose size exceeds ORDER_PHOTO_MAX_BYTES is
    rejected with HTTP 413 without loading the payload into server memory."""
    booking_id = asyncio.run(_create_booking_with_consent(async_session_maker))

    original_max = settings.order_photo_max_bytes
    settings.order_photo_max_bytes = 100  # deliberately tiny cap
    try:
        response = client.post(
            f"/v1/orders/{booking_id}/photos",
            data={"phase": "AFTER"},
            files={"file": ("oversized.jpg", b"X" * 200, "image/jpeg")},
            headers=admin_headers,
        )
    finally:
        settings.order_photo_max_bytes = original_max

    assert response.status_code == 413, (
        f"Expected 413 for oversized upload but got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# (b) PR-04 — CSRF enforcement
# ---------------------------------------------------------------------------


@pytest.mark.epic1
def test_epic1_csrf_blocks_post_without_token(client):
    """Epic 1 / PR-04: A state-changing request that reaches a CSRF-protected
    endpoint without a valid token is rejected with HTTP 403."""
    settings.testing = False
    settings.admin_basic_username = "admin"
    settings.admin_basic_password = "secret"

    headers = _basic_auth_header("admin", "secret")
    response = client.post(
        "/v1/admin/ui/workers/new",
        headers=headers,
        data={
            "name": "Epic1 CSRF Smoke Worker",
            "phone": "+1 555-0099",
            "team_id": 1,
        },
        follow_redirects=False,
    )

    assert response.status_code == 403, (
        f"Expected 403 (CSRF rejected) but got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# (c) PR-03 — Trusted-proxy header behaviour
# ---------------------------------------------------------------------------


@pytest.mark.epic1
def test_epic1_spoofed_xff_from_untrusted_source_is_ignored():
    """Epic 1 / PR-03: When the TCP source address is NOT in TRUSTED_PROXY_CIDRS,
    any X-Forwarded-For value is discarded and the resolved client IP equals the
    direct connection host (request.client.host)."""
    spoofed_xff = "1.2.3.4"
    direct_connection_host = "203.0.113.99"  # public address, not a trusted proxy

    request = _make_request(client_host=direct_connection_host, xff=spoofed_xff)
    resolved = get_client_ip(request, trusted_cidrs=[])

    assert resolved == direct_connection_host, (
        f"Expected connection host {direct_connection_host!r} but resolved {resolved!r}; "
        "spoofed XFF was trusted from an untrusted source — PR-03 regression"
    )
    assert resolved != spoofed_xff, (
        f"Resolved IP matches the spoofed XFF {spoofed_xff!r}; "
        "PR-03 trusted-proxy guard is broken"
    )


# ---------------------------------------------------------------------------
# (d) PR-02 — Stripe transaction boundary
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.epic1
async def test_epic1_stripe_called_outside_db_transaction(
    client, async_session_maker, monkeypatch
):
    """Epic 1 / PR-02: Structural assertion that Stripe create_checkout_session
    executes BEFORE any DB transaction opens (Phase 1 before Phase 2 per the
    two-phase booking pattern documented in docs/payments/TRANSACTION_BOUNDARIES.md).

    The test monkeypatches booking_service.create_booking to flip an in_txn sentinel
    and Stripe's call dispatcher to capture the flag at call time.
    """
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_epic1_smoke")
    monkeypatch.setattr(settings, "deposits_enabled", True)
    monkeypatch.setattr(
        settings, "stripe_success_url", "https://example.com/success?booking={BOOKING_ID}"
    )
    monkeypatch.setattr(
        settings, "stripe_cancel_url", "https://example.com/cancel?booking={BOOKING_ID}"
    )
    monkeypatch.setattr(settings, "deposit_currency", "cad")

    lead_id = await _seed_lead_for_booking(async_session_maker)

    # Sentinel: flipped to True while create_booking (DB Phase 2) is executing.
    in_txn: dict[str, bool] = {"value": False}

    from app.api import routes_bookings

    original_create_booking = routes_bookings.booking_service.create_booking

    async def _wrapped_create_booking(*args, **kwargs):
        in_txn["value"] = True
        try:
            return await original_create_booking(*args, **kwargs)
        finally:
            in_txn["value"] = False

    monkeypatch.setattr(
        "app.api.routes_bookings.booking_service.create_booking",
        _wrapped_create_booking,
    )

    # Record the in_txn flag value at the moment Stripe is called.
    stripe_called_inside_txn: dict[str, bool] = {"value": False}

    async def _mock_stripe(stripe_client, method_name: str, /, *args, **kwargs):
        if method_name == "create_checkout_session":
            stripe_called_inside_txn["value"] = in_txn["value"]
            return SimpleNamespace(
                id="cs_test_epic1_smoke",
                url="https://stripe.test/checkout/epic1",
                payment_intent="pi_test_epic1_smoke",
            )
        if method_name == "cancel_checkout_session":
            return None
        raise AssertionError(f"Unexpected Stripe method in smoke test: {method_name}")

    monkeypatch.setattr(
        "app.api.routes_bookings.stripe_infra.call_stripe_client_method",
        _mock_stripe,
    )

    response = client.post(
        "/v1/bookings",
        json={"starts_at": _future_slot(), "time_on_site_hours": 2.0, "lead_id": lead_id},
    )

    assert response.status_code == 201, (
        f"Booking creation failed ({response.status_code}): {response.text}"
    )
    assert not stripe_called_inside_txn["value"], (
        "REGRESSION (PR-02): Stripe create_checkout_session was called INSIDE a DB "
        "transaction — it must execute in Phase 1, before session.begin() / begin_nested(). "
        "See docs/payments/TRANSACTION_BOUNDARIES.md."
    )
