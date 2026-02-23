from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bookings import photos_service
from app.domain.bookings.db_models import Booking, OrderPhoto
from app.domain.data_rights.db_models import DataDeletionRequest, DataExportRequest
from app.domain.errors import DomainError
from app.domain.invoices.db_models import Invoice, InvoicePublicToken, Payment
from app.domain.leads.db_models import Lead
from app.domain.leads.service import export_payload_from_lead
from app.infra.storage import StorageBackend, new_storage_backend
from app.settings import settings


def encode_data_export_cursor(created_at: datetime, export_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{export_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def decode_data_export_cursor(cursor: str) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        created_raw, export_raw = decoded.split("|", 1)
        created_at = datetime.fromisoformat(created_raw)
        export_id = uuid.UUID(export_raw)
    except Exception:  # noqa: BLE001
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at, export_id


def decode_data_export_cursor_strict(cursor: str) -> tuple[datetime, uuid.UUID]:
    parsed = decode_data_export_cursor(cursor)
    if not parsed:
        raise ValueError("invalid_cursor")
    return parsed


def _apply_data_export_cursor(stmt: Any, cursor: str | None) -> Any:
    parsed = decode_data_export_cursor(cursor) if cursor else None
    if not parsed:
        return stmt
    created_at, export_id = parsed
    return stmt.where(
        or_(
            DataExportRequest.created_at < created_at,
            (DataExportRequest.created_at == created_at) & (DataExportRequest.export_id < export_id),
        )
    )

def _sanitize_booking(booking: Booking) -> dict:
    return {
        "booking_id": booking.booking_id,
        "lead_id": booking.lead_id,
        "team_id": booking.team_id,
        "status": booking.status,
        "starts_at": booking.starts_at.isoformat() if booking.starts_at else None,
        "duration_minutes": booking.duration_minutes,
        "scheduled_date": booking.scheduled_date.isoformat() if booking.scheduled_date else None,
        "created_at": booking.created_at.isoformat() if booking.created_at else None,
        "updated_at": booking.updated_at.isoformat() if booking.updated_at else None,
        "deposit_required": booking.deposit_required,
        "deposit_cents": booking.deposit_cents,
        "deposit_status": booking.deposit_status,
        "consent_photos": booking.consent_photos,
    }


def _sanitize_invoice(invoice: Invoice) -> dict:
    return {
        "invoice_id": invoice.invoice_id,
        "invoice_number": invoice.invoice_number,
        "customer_id": invoice.customer_id,
        "order_id": invoice.order_id,
        "status": invoice.status,
        "issue_date": invoice.issue_date.isoformat() if invoice.issue_date else None,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "currency": invoice.currency,
        "subtotal_cents": invoice.subtotal_cents,
        "taxable_subtotal_cents": invoice.taxable_subtotal_cents,
        "tax_cents": invoice.tax_cents,
        "tax_rate_basis": float(invoice.tax_rate_basis) if invoice.tax_rate_basis else None,
        "total_cents": invoice.total_cents,
        "notes": invoice.notes,
        "created_by": invoice.created_by,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
        "updated_at": invoice.updated_at.isoformat() if invoice.updated_at else None,
    }


def _sanitize_payment(payment: Payment) -> dict:
    return {
        "payment_id": payment.payment_id,
        "invoice_id": payment.invoice_id,
        "booking_id": payment.booking_id,
        "provider": payment.provider,
        "method": payment.method,
        "amount_cents": payment.amount_cents,
        "currency": payment.currency,
        "status": payment.status,
        "received_at": payment.received_at.isoformat() if payment.received_at else None,
        "reference": payment.reference,
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
    }


def _photo_reference(photo: OrderPhoto) -> dict:
    return {
        "photo_id": photo.photo_id,
        "order_id": photo.order_id,
        "filename": photo.filename,
        "original_filename": photo.original_filename,
        "content_type": photo.content_type,
        "size_bytes": photo.size_bytes,
        "storage_provider": photo.storage_provider,
        "storage_key": photo.storage_key,
        "review_status": photo.review_status,
        "needs_retake": photo.needs_retake,
        "created_at": photo.created_at.isoformat() if photo.created_at else None,
    }


async def export_client_data(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    lead_id: str | None = None,
    email: str | None = None,
) -> dict:
    lead_filters = [Lead.org_id == org_id]
    if lead_id:
        lead_filters.append(Lead.lead_id == lead_id)
    if email:
        lead_filters.append(Lead.email == email)

    lead_result = await session.execute(select(Lead).where(*lead_filters))
    leads = list(lead_result.scalars().all())
    if not leads:
        raise DomainError(detail="lead_not_found")

    lead_ids = [lead.lead_id for lead in leads]
    booking_result = await session.execute(
        select(Booking).where(Booking.lead_id.in_(lead_ids), Booking.org_id == org_id)
    )
    bookings = list(booking_result.scalars().all())
    booking_ids = [booking.booking_id for booking in bookings]

    invoice_result = await session.execute(
        select(Invoice).where(
            Invoice.org_id == org_id,
            (Invoice.customer_id.in_(lead_ids)) | (Invoice.order_id.in_(booking_ids)),
        )
    )
    invoices = list(invoice_result.scalars().all())
    invoice_ids = [invoice.invoice_id for invoice in invoices]

    payment_result = await session.execute(
        select(Payment).where(
            Payment.org_id == org_id,
            (Payment.invoice_id.in_(invoice_ids)) | (Payment.booking_id.in_(booking_ids)),
        )
    )
    payments = list(payment_result.scalars().all())

    photos_result = await session.execute(
        select(OrderPhoto).where(
            OrderPhoto.org_id == org_id, OrderPhoto.order_id.in_(booking_ids)
        )
    )
    photos = list(photos_result.scalars().all())

    return {
        "leads": [export_payload_from_lead(lead) for lead in leads],
        "bookings": [_sanitize_booking(booking) for booking in bookings],
        "invoices": [_sanitize_invoice(invoice) for invoice in invoices],
        "payments": [_sanitize_payment(payment) for payment in payments],
        "photos": [_photo_reference(photo) for photo in photos],
    }


async def request_data_deletion(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    lead_id: str | None,
    email: str | None,
    reason: str | None,
    requested_by: str | None,
) -> tuple[DataDeletionRequest, int]:
    lead_filters = [Lead.org_id == org_id]
    if lead_id:
        lead_filters.append(Lead.lead_id == lead_id)
    if email:
        lead_filters.append(Lead.email == email)

    lead_result = await session.execute(select(Lead).where(*lead_filters))
    leads = list(lead_result.scalars().all())
    if not leads:
        raise DomainError(detail="lead_not_found")

    now = datetime.now(tz=timezone.utc)
    for lead in leads:
        lead.pending_deletion = True
        lead.deletion_requested_at = now

    request = DataDeletionRequest(
        org_id=org_id,
        lead_id=lead_id,
        email=email,
        reason=reason,
        requested_by=requested_by,
        status="pending",
        processed_notes=None,
    )
    session.add(request)
    await session.flush()
    return request, len(leads)


async def _anonymize_lead(
    session: AsyncSession,
    lead: Lead,
    *,
    storage: StorageBackend,
) -> tuple[int, int]:
    booking_result = await session.execute(
        select(Booking).where(Booking.lead_id == lead.lead_id, Booking.org_id == lead.org_id)
    )
    bookings = list(booking_result.scalars().all())
    booking_ids = [booking.booking_id for booking in bookings]
    photo_count = 0
    for booking_id in booking_ids:
        photo_result = await session.execute(
            select(OrderPhoto).where(
                OrderPhoto.order_id == booking_id,
                OrderPhoto.org_id == lead.org_id,
            )
        )
        photos = list(photo_result.scalars().all())
        for photo in photos:
            await photos_service.delete_photo(
                session,
                booking_id,
                photo.photo_id,
                storage=storage,
                org_id=lead.org_id,
            )
            photo_count += 1

    if booking_ids:
        await session.execute(
            update(Booking)
            .where(Booking.booking_id.in_(booking_ids))
            .values(lead_id=None)
        )

    invoice_result = await session.execute(
        select(Invoice).where(
            Invoice.org_id == lead.org_id,
            (Invoice.customer_id == lead.lead_id) | (Invoice.order_id.in_(booking_ids)),
        )
    )
    invoices = list(invoice_result.scalars().all())
    invoice_ids = [invoice.invoice_id for invoice in invoices]
    invoices_detached = 0
    if invoice_ids:
        await session.execute(delete(InvoicePublicToken).where(InvoicePublicToken.invoice_id.in_(invoice_ids)))
        detach = await session.execute(
            update(Invoice)
            .where(Invoice.invoice_id.in_(invoice_ids))
            .values(customer_id=None)
        )
        invoices_detached = detach.rowcount or 0

    lead.name = "Deleted contact"
    lead.phone = "deleted"
    lead.email = None
    lead.postal_code = None
    lead.address = None
    lead.access_notes = None
    lead.parking = None
    lead.pets = None
    lead.allergies = None
    lead.notes = None
    lead.structured_inputs = {}
    lead.estimate_snapshot = {}
    lead.preferred_dates = []
    lead.pending_deletion = False
    lead.deleted_at = datetime.now(tz=timezone.utc)

    return photo_count, invoices_detached


async def process_pending_deletions(
    session: AsyncSession,
    *,
    storage_backend: StorageBackend | None = None,
) -> dict[str, int]:
    storage = storage_backend or getattr(session.bind, "storage_backend", None) or new_storage_backend()
    stmt = select(DataDeletionRequest).where(DataDeletionRequest.status == "pending")
    result = await session.execute(stmt)
    requests = list(result.scalars().all())
    processed = 0
    leads_anonymized = 0
    photos_deleted = 0
    invoices_detached = 0

    for request in requests:
        lead_filters = [Lead.org_id == request.org_id]
        if request.lead_id:
            lead_filters.append(Lead.lead_id == request.lead_id)
        if request.email:
            lead_filters.append(Lead.email == request.email)

        lead_result = await session.execute(select(Lead).where(*lead_filters))
        leads = list(lead_result.scalars().all())
        for lead in leads:
            photo_count, detached = await _anonymize_lead(session, lead, storage=storage)
            leads_anonymized += 1
            photos_deleted += photo_count
            invoices_detached += detached

        request.status = "processed"
        request.processed_at = datetime.now(tz=timezone.utc)
        request.processed_notes = f"anonymized:{len(leads)}"
        processed += 1

    await session.commit()
    return {
        "processed": processed,
        "leads_anonymized": leads_anonymized,
        "photos_deleted": photos_deleted,
        "invoices_detached": invoices_detached,
    }


_SENSITIVE_EXPORT_KEYS = {
    "token",
    "secret",
    "signature",
    "authorization",
    "access_token",
    "refresh_token",
    "id_token",
}


def _redact_sensitive_fields(payload: Any) -> Any:
    if payload is None:
        return None
    if isinstance(payload, list):
        return [_redact_sensitive_fields(item) for item in payload]
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            normalized = str(key).lower()
            if (
                normalized in _SENSITIVE_EXPORT_KEYS
                or normalized.endswith("_token")
                or normalized.endswith("_secret")
            ):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = _redact_sensitive_fields(value)
        return sanitized
    return payload


async def create_data_export_request(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    subject_id: str,
    subject_type: str,
    subject_email: str | None,
    requested_by: str | None,
    requested_by_type: str | None,
    request_id: str | None,
) -> DataExportRequest:
    record = DataExportRequest(
        org_id=org_id,
        subject_id=subject_id,
        subject_type=subject_type,
        subject_email=subject_email,
        status="pending",
        requested_by=requested_by,
        requested_by_type=requested_by_type,
        request_id=request_id,
    )
    session.add(record)
    await session.flush()
    return record


async def find_recent_export_request(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    subject_id: str | None,
    subject_email: str | None,
    cooldown_seconds: int,
) -> DataExportRequest | None:
    if cooldown_seconds <= 0:
        return None
    cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=cooldown_seconds)
    conditions = [DataExportRequest.org_id == org_id]
    if subject_id and subject_email:
        conditions.append(
            or_(
                DataExportRequest.subject_id == subject_id,
                DataExportRequest.subject_email == subject_email,
            )
        )
    elif subject_id:
        conditions.append(DataExportRequest.subject_id == subject_id)
    elif subject_email:
        conditions.append(DataExportRequest.subject_email == subject_email)
    else:
        return None
    recent_stmt = (
        select(DataExportRequest)
        .where(
            *conditions,
            DataExportRequest.status.in_(["pending", "processing", "completed"]),
            func.coalesce(DataExportRequest.completed_at, DataExportRequest.created_at) >= cutoff,
        )
        .order_by(DataExportRequest.created_at.desc())
        .limit(1)
    )
    result = await session.execute(recent_stmt)
    return result.scalar_one_or_none()


async def list_data_export_requests(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    subject_email: str | None = None,
    subject_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    offset: int | None = None,
) -> tuple[list[DataExportRequest], int, str | None, str | None]:
    stmt = select(DataExportRequest).where(DataExportRequest.org_id == org_id)
    if subject_email and subject_id:
        stmt = stmt.where(
            or_(
                DataExportRequest.subject_email == subject_email,
                DataExportRequest.subject_id == subject_id,
            )
        )
    elif subject_email:
        stmt = stmt.where(DataExportRequest.subject_email == subject_email)
    elif subject_id:
        stmt = stmt.where(DataExportRequest.subject_id == subject_id)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    order_by = (
        DataExportRequest.created_at.desc(),
        DataExportRequest.export_id.desc(),
    )
    use_offset_pagination = offset is not None and cursor is None
    if use_offset_pagination:
        paged_stmt = stmt.order_by(*order_by).limit(limit).offset(offset)
    else:
        scoped_stmt = _apply_data_export_cursor(stmt, cursor)
        paged_stmt = scoped_stmt.order_by(*order_by).limit(limit)
    result = await session.execute(paged_stmt)
    items = list(result.scalars().all())

    next_cursor = None
    if not use_offset_pagination and items and len(items) == limit:
        tail = items[-1]
        next_cursor = encode_data_export_cursor(tail.created_at, tail.export_id)

    prev_cursor = None
    return items, total, next_cursor, prev_cursor


async def generate_data_export_bundle(
    session: AsyncSession,
    *,
    export_request: DataExportRequest,
    storage_backend: StorageBackend | None = None,
) -> DataExportRequest:
    storage = storage_backend or getattr(session.bind, "storage_backend", None) or new_storage_backend()
    export_request.status = "processing"
    await session.flush()

    lead_id = export_request.subject_id if export_request.subject_type == "lead" else None
    email = export_request.subject_email if export_request.subject_email else None
    if export_request.subject_type == "email":
        email = export_request.subject_id

    try:
        bundle = await export_client_data(
            session,
            export_request.org_id,
            lead_id=lead_id,
            email=email,
        )
    except DomainError as exc:
        export_request.status = "failed"
        export_request.error_code = exc.detail
        await session.flush()
        return export_request

    sanitized_bundle = _redact_sensitive_fields(bundle)
    payload = {
        "export_id": str(export_request.export_id),
        "org_id": str(export_request.org_id),
        "subject_id": export_request.subject_id,
        "subject_type": export_request.subject_type,
        "subject_email": export_request.subject_email,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "data": sanitized_bundle,
    }
    data_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    async def _stream() -> Any:
        yield data_bytes

    key = f"data-exports/{export_request.org_id}/{export_request.export_id}.json"
    stored = await storage.put(
        key=key,
        body=_stream(),
        content_type="application/json",
    )
    export_request.storage_key = stored.key
    export_request.content_type = stored.content_type
    export_request.size_bytes = stored.size
    export_request.status = "completed"
    export_request.completed_at = datetime.now(tz=timezone.utc)
    export_request.error_code = None
    await session.flush()
    return export_request


async def purge_expired_exports(
    session: AsyncSession,
    *,
    storage_backend: StorageBackend | None = None,
) -> dict[str, int]:
    retention_days = settings.data_export_retention_days
    if not retention_days or retention_days <= 0:
        return {"processed": 0, "deleted": 0}
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
    stmt = select(DataExportRequest).where(
        DataExportRequest.completed_at.is_not(None),
        DataExportRequest.completed_at <= cutoff,
    )
    result = await session.execute(stmt)
    records = list(result.scalars().all())
    processed = 0
    deleted = 0
    storage = storage_backend or getattr(session.bind, "storage_backend", None) or new_storage_backend()
    for record in records:
        processed += 1
        if record.storage_key:
            await storage.delete(key=record.storage_key)
            deleted += 1
        await session.delete(record)
    if records:
        await session.commit()
    return {"processed": processed, "deleted": deleted}
