import uuid
import pytest
import pytest_asyncio
from datetime import date, datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.domain.data_rights import service as data_rights_service
from app.domain.leads.db_models import Lead
from app.domain.bookings.db_models import Booking, OrderPhoto
from app.domain.invoices.db_models import Invoice
from app.domain.admin_audit.db_models import AdminAuditLog
from app.domain.data_rights.db_models import DataDeletionRequest
# Make sure iam_roles table is loaded for foreign keys
import app.domain.iam.db_models
import app.domain.addons.db_models # For addon_definitions
import app.domain.pricing_settings.db_models # For service_addons
import app.domain.marketing.db_models # For promo_codes
from app.settings import settings
from app.infra.db import Base

# Setup in-memory sqlite db for this test
@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session

    await engine.dispose()

@pytest.mark.asyncio
async def test_deletion_totals_aggregation(db_session):
    # Setup Org
    org_id = settings.default_org_id

    # Create 2 leads with same email
    target_email = "forgetme@example.com"
    lead1 = Lead(
        org_id=org_id,
        name="Lead One",
        phone="555-0101",
        email=target_email,
        structured_inputs={},
        estimate_snapshot={},
        pricing_config_version="v1",
        config_hash="abc",
    )
    lead2 = Lead(
        org_id=org_id,
        name="Lead Two",
        phone="555-0102",
        email=target_email,
        structured_inputs={},
        estimate_snapshot={},
        pricing_config_version="v1",
        config_hash="def",
    )
    db_session.add_all([lead1, lead2])
    await db_session.flush()

    # Add Booking + Photos for Lead 1
    booking1 = Booking(
        booking_id=str(uuid.uuid4()),
        org_id=org_id,
        lead_id=lead1.lead_id,
        team_id=1,
        status="DONE",
        scheduled_date=date.today(),
        starts_at=datetime.now(),
        duration_minutes=60,
    )
    db_session.add(booking1)
    await db_session.flush()

    photo1 = OrderPhoto(
        order_id=booking1.booking_id,
        org_id=org_id,
        filename="p1.jpg",
        size_bytes=100,
        phase="before",
        uploaded_by="worker",
        content_type="image/jpeg",
        sha256="dummyhash1",
        storage_key="photos/p1.jpg",
    )
    photo2 = OrderPhoto(
        order_id=booking1.booking_id,
        org_id=org_id,
        filename="p2.jpg",
        size_bytes=100,
        phase="after",
        uploaded_by="worker",
        content_type="image/jpeg",
        sha256="dummyhash2",
        storage_key="photos/p2.jpg",
    )
    db_session.add_all([photo1, photo2])

    # Add Invoice for Lead 2
    invoice1 = Invoice(
        org_id=org_id,
        customer_id=lead2.lead_id,
        invoice_number="INV-DEL-001",
        status="draft",
        issue_date=date.today(),
        due_date=date.today(),
        currency="CAD",
        subtotal_cents=100,
        total_cents=100,
        tax_cents=0,
    )
    db_session.add(invoice1)
    await db_session.flush()

    # Request Deletion
    req, count = await data_rights_service.request_data_deletion(
        db_session,
        org_id=org_id,
        lead_id=None,
        email=target_email,
        reason="privacy",
        requested_by="admin",
    )
    assert count == 2
    await db_session.commit()

    # Process
    stats = await data_rights_service.process_pending_deletions(db_session)

    assert stats["processed"] == 1
    assert stats["leads_anonymized"] == 2
    assert stats["photos_deleted"] == 2
    assert stats["invoices_detached"] == 1

    # Check Audit Log
    stmt = select(AdminAuditLog).where(
        AdminAuditLog.resource_id == str(req.request_id),
        AdminAuditLog.action == "gdpr_deletion_processed"
    )
    result = await db_session.execute(stmt)
    log = result.scalar_one()

    assert log.context["leads_deleted"] == 2
    assert log.context["photos_deleted"] == 2
    assert log.context["invoices_detached"] == 1


@pytest.mark.asyncio
async def test_deletion_request_with_zero_matching_leads_is_processed(db_session):
    req = DataDeletionRequest(
        org_id=settings.default_org_id,
        email="nobody@example.com",
        status="pending",
    )
    db_session.add(req)
    await db_session.commit()

    stats = await data_rights_service.process_pending_deletions(db_session)

    assert stats["processed"] == 1
    refreshed = await db_session.get(DataDeletionRequest, req.request_id)
    assert refreshed is not None
    assert refreshed.status == "processed"
    assert refreshed.processed_at is not None

    stmt = select(AdminAuditLog).where(AdminAuditLog.resource_id == str(req.request_id))
    result = await db_session.execute(stmt)
    log = result.scalar_one()
    assert log.context["leads_deleted"] == 0
    assert log.context["photos_deleted"] == 0
    assert log.context["invoices_detached"] == 0


@pytest.mark.asyncio
async def test_fk_integrity_error_falls_back_to_anonymization(db_session):
    org_id = settings.default_org_id
    referrer = Lead(
        org_id=org_id,
        name="Referrer",
        phone="555-0109",
        email="referrer@example.com",
        structured_inputs={},
        estimate_snapshot={},
        pricing_config_version="v1",
        config_hash="aaa",
    )
    referred = Lead(
        org_id=org_id,
        name="Target",
        phone="555-0110",
        email="target@example.com",
        structured_inputs={},
        estimate_snapshot={},
        pricing_config_version="v1",
        config_hash="bbb",
    )
    db_session.add_all([referrer, referred])
    await db_session.flush()

    from app.domain.leads.db_models import ReferralCredit

    credit = ReferralCredit(
        referrer_lead_id=referrer.lead_id,
        referred_lead_id=referred.lead_id,
        applied_code=referrer.referral_code,
    )
    db_session.add(credit)

    req, _ = await data_rights_service.request_data_deletion(
        db_session,
        org_id=org_id,
        lead_id=referred.lead_id,
        email=None,
        reason="gdpr",
        requested_by="tester",
    )
    await db_session.commit()

    stats = await data_rights_service.process_pending_deletions(db_session)
    assert stats["processed"] == 1
    assert stats["leads_anonymized"] == 1

    still_exists = await db_session.get(Lead, referred.lead_id)
    assert still_exists is not None
    assert still_exists.name == "[deleted]"
    assert still_exists.phone == "[deleted]"
    assert still_exists.email is None
    assert still_exists.pending_deletion is False
    assert still_exists.deleted_at is not None

    processed_req = await db_session.get(DataDeletionRequest, req.request_id)
    assert processed_req is not None
    assert "anonymize_fallback_fk" in (processed_req.processed_notes or "")

    stmt = select(AdminAuditLog).where(AdminAuditLog.resource_id == str(req.request_id))
    result = await db_session.execute(stmt)
    log = result.scalar_one()
    assert "anonymize_fallback_fk" in log.context["deletion_modes"]
