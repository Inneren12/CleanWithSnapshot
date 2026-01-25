import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from app.domain.config_audit import service as config_audit_service
from app.domain.bookings.db_models import Booking, BookingPhoto
from app.domain.feature_modules import service as feature_service
from app.domain.leads.db_models import Lead
from app.domain.saas import service as saas_service
from app.domain.saas.db_models import MembershipRole


async def _create_booking(async_session_maker, org_id: uuid.UUID) -> str:
    async with async_session_maker() as session:
        lead = Lead(
            org_id=org_id,
            name="Evidence Lead",
            phone="555-0100",
            email="evidence@example.com",
            postal_code="T5A",
            address="123 Evidence St",
            preferred_dates=["Mon"],
            structured_inputs={"beds": 2, "baths": 1, "cleaning_type": "standard"},
            estimate_snapshot={
                "price_cents": 10000,
                "subtotal_cents": 10000,
                "tax_cents": 0,
                "pricing_config_version": "v1",
                "config_hash": "hash",
                "line_items": [],
            },
            pricing_config_version="v1",
            config_hash="hash",
            referral_code=str(uuid.uuid4())[:8],
        )
        session.add(lead)
        await session.commit()
        await session.refresh(lead)

        booking = Booking(
            org_id=org_id,
            team_id=1,
            lead_id=lead.lead_id,
            starts_at=datetime.now(tz=timezone.utc),
            duration_minutes=60,
            status="CONFIRMED",
        )
        session.add(booking)
        await session.commit()
        await session.refresh(booking)
        return booking.booking_id


@pytest.mark.anyio
async def test_quality_photo_evidence_org_scoping(async_session_maker, client):
    async with async_session_maker() as session:
        org_a = await saas_service.create_organization(session, "Photo Org A")
        owner_a = await saas_service.create_user(session, "photo-a@org.com", "secret")
        membership_a = await saas_service.create_membership(session, org_a, owner_a, MembershipRole.OWNER)
        await feature_service.upsert_org_feature_overrides(
            session,
            org_a.org_id,
            {"quality.photo_evidence": True},
            audit_actor=config_audit_service.system_actor("tests"),
            request_id=None,
        )

        org_b = await saas_service.create_organization(session, "Photo Org B")
        owner_b = await saas_service.create_user(session, "photo-b@org.com", "secret")
        membership_b = await saas_service.create_membership(session, org_b, owner_b, MembershipRole.OWNER)
        await feature_service.upsert_org_feature_overrides(
            session,
            org_b.org_id,
            {"quality.photo_evidence": True},
            audit_actor=config_audit_service.system_actor("tests"),
            request_id=None,
        )
        await session.commit()

    booking_a = await _create_booking(async_session_maker, org_a.org_id)
    booking_b = await _create_booking(async_session_maker, org_b.org_id)

    token_a = saas_service.build_access_token(owner_a, membership_a)
    token_b = saas_service.build_access_token(owner_b, membership_b)

    response_a = client.post(
        f"/v1/admin/bookings/{booking_a}/photos",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "kind": "before",
            "storage_key": "org-a/evidence.jpg",
            "mime": "image/jpeg",
            "bytes": 1234,
            "consent": True,
        },
    )
    assert response_a.status_code == 201

    response_b = client.post(
        f"/v1/admin/bookings/{booking_b}/photos",
        headers={"Authorization": f"Bearer {token_b}"},
        json={
            "kind": "after",
            "storage_key": "org-b/evidence.jpg",
            "mime": "image/jpeg",
            "bytes": 2345,
            "consent": True,
        },
    )
    assert response_b.status_code == 201

    list_resp = client.get(
        "/v1/admin/quality/photos",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert payload["total"] == 1
    assert payload["items"][0]["booking_id"] == booking_a


@pytest.mark.anyio
async def test_quality_photo_evidence_consent_persisted(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "Consent Org")
        owner = await saas_service.create_user(session, "consent-owner@org.com", "secret")
        membership = await saas_service.create_membership(session, org, owner, MembershipRole.OWNER)
        await feature_service.upsert_org_feature_overrides(
            session,
            org.org_id,
            {"quality.photo_evidence": True},
            audit_actor=config_audit_service.system_actor("tests"),
            request_id=None,
        )
        await session.commit()

    booking_id = await _create_booking(async_session_maker, org.org_id)
    token = saas_service.build_access_token(owner, membership)

    response = client.post(
        f"/v1/admin/bookings/{booking_id}/photos",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "kind": "after",
            "storage_key": "consent/evidence.jpg",
            "mime": "image/jpeg",
            "bytes": 1024,
            "consent": False,
        },
    )
    assert response.status_code == 201

    async with async_session_maker() as session:
        result = await session.execute(
            sa.select(BookingPhoto).where(
                BookingPhoto.booking_id == booking_id,
                BookingPhoto.org_id == org.org_id,
            )
        )
        photo = result.scalar_one()
        assert photo.consent is False


@pytest.mark.anyio
async def test_quality_photo_evidence_rbac_blocks_viewer(async_session_maker, client):
    async with async_session_maker() as session:
        org = await saas_service.create_organization(session, "RBAC Org")
        viewer = await saas_service.create_user(session, "rbac-viewer@org.com", "secret")
        membership = await saas_service.create_membership(session, org, viewer, MembershipRole.VIEWER)
        await feature_service.upsert_org_feature_overrides(
            session,
            org.org_id,
            {"quality.photo_evidence": True},
            audit_actor=config_audit_service.system_actor("tests"),
            request_id=None,
        )
        await session.commit()

    booking_id = await _create_booking(async_session_maker, org.org_id)
    token = saas_service.build_access_token(viewer, membership)

    response = client.post(
        f"/v1/admin/bookings/{booking_id}/photos",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "kind": "before",
            "storage_key": "rbac/evidence.jpg",
            "mime": "image/jpeg",
            "bytes": 256,
            "consent": True,
        },
    )
    assert response.status_code == 403
