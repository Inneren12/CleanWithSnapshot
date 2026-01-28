from __future__ import annotations

from html import escape
import logging
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.photo_tokens import verify_photo_download_token
from app.api.problem_details import problem_details
from app.domain.bookings import photos_service
from app.domain.bookings.db_models import Booking
from app.domain.clients.db_models import ClientUser
from app.domain.documents import service as document_service
from app.domain.admin_audit import service as audit_service
from app.domain.admin_audit.db_models import AdminAuditActionType, AdminAuditSensitivity
from app.domain.feature_modules import service as feature_service
from app.domain.invoices import schemas as invoice_schemas, service as invoice_service, statuses as invoice_statuses
from app.domain.nps import schemas as nps_schemas, service as nps_service
from app.domain.nps.db_models import NpsToken
from app.domain.notifications import email_service
from app.domain.quality import service as quality_service
from app.domain.storage_quota import service as storage_quota_service
from app.infra.db import get_db_session
from app.infra.email import resolve_app_email_adapter
from app.infra.storage import resolve_storage_backend
from app.infra import stripe as stripe_infra
from app.settings import settings

router = APIRouter(include_in_schema=False)
logger = logging.getLogger(__name__)


@router.get("/", include_in_schema=False)
async def public_root() -> JSONResponse:
    return JSONResponse(
        {
            "service": "cleaning-api",
            "healthz": "/healthz",
            "readyz": "/readyz",
            "admin": "/v1/admin",
        }
    )


@router.get("/photos/{token}", name="public_photo_download", include_in_schema=False)
async def public_photo_download(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    claims = await verify_photo_download_token(token, user_agent=request.headers.get("user-agent"))
    storage = resolve_storage_backend(request.app.state)
    ttl = min(settings.photo_url_ttl_seconds, max(claims.exp - int(time.time()), 1))

    if claims.resource_type == "booking_photo":
        enabled = await feature_service.effective_feature_enabled(
            session, claims.org_id, "quality.photo_evidence"
        )
        if not enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")
        booking_photo = await quality_service.get_booking_photo(
            session, org_id=claims.org_id, photo_id=claims.photo_id
        )
        if booking_photo.booking_id != claims.order_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found")
        if not booking_photo.consent:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Photo consent not granted")
        key = booking_photo.storage_key
        content_type = booking_photo.mime
        filename = booking_photo.photo_id
    else:
        photo = await photos_service.get_photo(session, claims.order_id, claims.photo_id, claims.org_id)
        order = await photos_service.fetch_order(session, claims.order_id, claims.org_id)
        if not order.consent_photos:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Photo consent not granted")
        key = photos_service.storage_key_for_photo(photo, claims.org_id)
        content_type = photo.content_type
        filename = photo.original_filename or photo.filename

    if storage.supports_direct_io():
        file_path = storage.path_for(key) if hasattr(storage, "path_for") else None
        if not file_path or not file_path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing")
        response = FileResponse(path=file_path, media_type=content_type, filename=filename)
    else:
        signed_url = await storage.generate_signed_get_url(
            key=key,
            expires_in=ttl,
            resource_url=str(request.url),
            variant=claims.variant,
        )
        response = RedirectResponse(
            url=signed_url, status_code=settings.photo_download_redirect_status
        )

    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _stripe_client(request: Request):
    if getattr(request.app.state, "stripe_client", None):
        return request.app.state.stripe_client
    services = getattr(request.app.state, "services", None)
    if services and getattr(services, "stripe_client", None):
        return services.stripe_client
    return stripe_infra.resolve_client(request.app.state)


def _format_currency(cents: int, currency: str) -> str:
    return f"{currency} {cents / 100:,.2f}"


def _render_invoice_html(context: dict) -> str:
    invoice = context["invoice"]
    customer = context["customer"]
    token = context.get("token")
    rows = []
    rows.append("<h1>Invoice</h1>")
    rows.append(f"<p><strong>Invoice #:</strong> {escape(invoice['invoice_number'])}</p>")
    rows.append(f"<p><strong>Status:</strong> {escape(invoice['status'])}</p>")
    rows.append(f"<p><strong>Issue Date:</strong> {escape(str(invoice['issue_date']))}</p>")
    if invoice.get("due_date"):
        rows.append(f"<p><strong>Due Date:</strong> {escape(str(invoice['due_date']))}</p>")
    if token:
        rows.append(f"<p><a href=\"/i/{escape(token)}.pdf\">Download PDF</a></p>")
    if invoice.get("order_id") and token:
        rows.append(
            f"<p><a href=\"/i/{escape(token)}/service-agreement.pdf\">Service agreement</a></p>"
        )

    rows.append("<h2>Bill To</h2>")
    if customer.get("name"):
        rows.append(f"<p>{escape(customer['name'])}</p>")
    if customer.get("email"):
        rows.append(f"<p>{escape(customer['email'])}</p>")
    if customer.get("address"):
        rows.append(f"<p>{escape(customer['address'])}</p>")

    rows.append("<h2>Items</h2>")
    rows.append(
        "<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\" width=\"100%\">"
        "<tr><th align=\"left\">Description</th><th>Qty</th><th align=\"right\">Unit Price" \
        "</th><th align=\"right\">Line Total</th></tr>"
    )
    for item in invoice.get("items", []):
        rows.append(
            "<tr>"
            f"<td>{escape(item['description'])}</td>"
            f"<td align=\"center\">{item['qty']}</td>"
            f"<td align=\"right\">{_format_currency(item['unit_price_cents'], invoice['currency'])}</td>"
            f"<td align=\"right\">{_format_currency(item['line_total_cents'], invoice['currency'])}</td>"
            "</tr>"
        )
    rows.append("</table>")

    rows.append("<h2>Totals</h2>")
    rows.append(
        f"<p>Subtotal: {_format_currency(invoice['subtotal_cents'], invoice['currency'])}<br>"
        f"Tax: {_format_currency(invoice['tax_cents'], invoice['currency'])}<br>"
        f"Total: <strong>{_format_currency(invoice['total_cents'], invoice['currency'])}</strong></p>"
    )
    if invoice.get("balance_due_cents") is not None:
        rows.append(
            f"<p>Balance Due: {_format_currency(invoice['balance_due_cents'], invoice['currency'])}</p>"
        )
    if invoice.get("notes"):
        rows.append(f"<h3>Notes</h3><p>{escape(invoice['notes'])}</p>")
    if token and invoice.get("payments"):
        succeeded = [p for p in invoice["payments"] if p.get("status") == invoice_statuses.PAYMENT_STATUS_SUCCEEDED]
        if succeeded:
            rows.append("<h3>Receipts</h3>")
            for payment in succeeded:
                payment_id = escape(payment["payment_id"])
                rows.append(
                    f"<p><a href=\"/i/{escape(token)}/receipts/{payment_id}.pdf\">Receipt {payment_id}</a></p>"
                )

    body = "\n".join(rows)
    return f"""
    <html lang=\"en\">
      <head>
        <title>Invoice {escape(invoice['invoice_number'])}</title>
      </head>
      <body>
        {body}
      </body>
    </html>
    """


def _render_nps_form(order_id: str, token: str) -> str:
    options = "".join(
        f'<label class="score"><input type="radio" name="score" value="{value}" required> {value}</label>'
        for value in range(11)
    )
    return f"""
    <html>
      <head>
        <title>Rate your cleaning</title>
        <style>
          body {{ font-family: Arial, sans-serif; max-width: 540px; margin: 40px auto; padding: 0 12px; }}
          h1 {{ color: #0f172a; }}
          form {{ margin-top: 16px; }}
          .scores {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }}
          .score {{ padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 6px; min-width: 44px; text-align: center; }}
          textarea {{ width: 100%; min-height: 120px; padding: 10px; border-radius: 8px; border: 1px solid #cbd5e1; }}
          button {{ background: #2563eb; color: white; border: none; padding: 10px 16px; border-radius: 6px; cursor: pointer; }}
          .muted {{ color: #475569; font-size: 0.95em; }}
        </style>
      </head>
      <body>
        <h1>How did we do?</h1>
        <p class="muted">Rate your recent cleaning from 0 (very unhappy) to 10 (delighted).</p>
        <form method="post" action="/nps/{escape(order_id)}">
          <input type="hidden" name="token" value="{escape(token)}" />
          <div class="scores">{options}</div>
          <label class="muted" for="comment">Anything to share? (optional)</label>
          <textarea id="comment" name="comment" placeholder="Tell us what went well or what to fix"></textarea>
          <div style="margin-top: 12px;"><button type="submit">Submit</button></div>
        </form>
      </body>
    </html>
    """


async def _load_nps_token(
    session: AsyncSession, *, token: str, booking_id: str | None = None
) -> tuple[NpsToken, Booking]:
    token_pair = await nps_service.fetch_token_with_booking(
        session, token=token, booking_id=booking_id
    )
    if not token_pair:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
    token_record, booking = token_pair
    try:
        nps_service.verify_nps_token(token_record)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    enabled = await feature_service.effective_feature_enabled(
        session, token_record.org_id, "quality.nps"
    )
    if not enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return token_record, booking


async def _notify_admin_on_low_score(
    request: Request | None,
    *,
    booking: Booking,
    score: int,
    comment: str | None,
    client: ClientUser | None,
) -> None:
    adapter = resolve_app_email_adapter(request) if request else None
    recipient = settings.admin_notification_email
    if adapter and recipient:
        subject = f"Support ticket created for order {booking.booking_id}"
        body_lines = [
            f"Order: {booking.booking_id}",
            f"Score: {score}",
        ]
        if client and client.email:
            body_lines.append(f"Client: {client.email}")
        if comment:
            body_lines.append("Comment: " + comment)
        try:
            await adapter.send_email(recipient=recipient, subject=subject, body="\n".join(body_lines))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "nps_admin_notification_failed",
                extra={"extra": {"order_id": booking.booking_id, "reason": type(exc).__name__}},
            )


def _render_message(title: str, body: str, status_text: str | None = None) -> str:
    status_section = f"<p class=\"muted\">{escape(status_text)}</p>" if status_text else ""
    return f"""
    <html>
      <head>
        <title>{escape(title)}</title>
        <style>
          body {{ font-family: Arial, sans-serif; max-width: 520px; margin: 40px auto; padding: 0 12px; }}
          h1 {{ color: #0f172a; }}
          .muted {{ color: #475569; }}
        </style>
      </head>
      <body>
        <h1>{escape(title)}</h1>
        {status_section}
        <p>{escape(body)}</p>
      </body>
    </html>
    """


@router.get("/nps/{order_id}", response_class=HTMLResponse, name="nps_form")
async def nps_form(order_id: str, token: str, session: AsyncSession = Depends(get_db_session)) -> HTMLResponse:
    token_record, booking = await _load_nps_token(session, token=token, booking_id=order_id)

    existing = await nps_service.get_existing_response_by_token(session, token_record.token)
    if existing:
        return HTMLResponse(_render_message("Thanks for the feedback!", "We've already received your rating."))

    return HTMLResponse(_render_nps_form(order_id, token))


@router.post("/nps/{order_id}", response_class=HTMLResponse)
async def submit_nps(
    order_id: str,
    request: Request,
    token: str = Form(...),
    score: int = Form(...),
    comment: str | None = Form(None),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    token_record, booking = await _load_nps_token(session, token=token, booking_id=order_id)

    if score < 0 or score > 10:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Score must be between 0 and 10")

    existing = await nps_service.get_existing_response_by_token(session, token_record.token)
    if existing:
        return HTMLResponse(_render_message("Thanks for the feedback!", "We've already received your rating."))

    await nps_service.record_response(
        session,
        token_record=token_record,
        booking=booking,
        score=score,
        comment=comment,
    )

    ticket = None
    client = await session.get(ClientUser, booking.client_id) if booking.client_id else None
    if score <= 3:
        ticket = await nps_service.ensure_ticket_for_low_score(
            session,
            booking=booking,
            score=score,
            comment=comment,
            client=client,
        )
        await _notify_admin_on_low_score(
            request,
            booking=booking,
            score=score,
            comment=comment,
            client=client,
        )

    await session.commit()

    if ticket:
        message = "Thanks for your feedback. Our support team will reach out to resolve this."  # noqa: E501
    else:
        message = "Thanks for your feedback! If you loved the service, feel free to share a Google review."
    return HTMLResponse(_render_message("Thanks!", message))


@router.post(
    "/v1/public/nps/{token}",
    response_model=nps_schemas.PublicNpsSubmitResponse,
    status_code=status.HTTP_200_OK,
)
async def submit_nps_public(
    token: str,
    payload: nps_schemas.PublicNpsSubmitRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> nps_schemas.PublicNpsSubmitResponse:
    token_record, booking = await _load_nps_token(session, token=token)
    existing = await nps_service.get_existing_response_by_token(session, token_record.token)
    if existing:
        return nps_schemas.PublicNpsSubmitResponse(
            status="already_submitted",
            token=existing.token,
            created_at=existing.created_at,
        )

    response = await nps_service.record_response(
        session,
        token_record=token_record,
        booking=booking,
        score=payload.score,
        comment=payload.comment,
    )

    client = await session.get(ClientUser, booking.client_id) if booking.client_id else None
    if payload.score <= 3:
        ticket = await nps_service.ensure_ticket_for_low_score(
            session,
            booking=booking,
            score=payload.score,
            comment=payload.comment,
            client=client,
        )
        if ticket:
            await _notify_admin_on_low_score(
                request,
                booking=booking,
                score=payload.score,
                comment=payload.comment,
                client=client,
            )

    await session.commit()
    return nps_schemas.PublicNpsSubmitResponse(
        status="submitted",
        token=response.token,
        created_at=response.created_at,
    )


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(token: str, session: AsyncSession = Depends(get_db_session)) -> HTMLResponse:
    try:
        data = email_service.verify_unsubscribe_token(token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")

    # Validate scope
    scope = data.get("scope")
    if scope not in {email_service.SCOPE_MARKETING, email_service.SCOPE_NPS}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid scope")

    await email_service.register_unsubscribe(
        session, recipient=data["email"], scope=scope, org_id=data.get("org_id")
    )
    return HTMLResponse(
        _render_message(
            "You've been unsubscribed",
            "You will no longer receive these emails.",
            status_text="Preference updated",
        )
    )
async def _download_invoice_pdf(
    token: str, request: Request, session: AsyncSession
) -> Response:
    invoice = await invoice_service.get_invoice_by_public_token(session, token)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == invoice_statuses.INVOICE_STATUS_VOID:
        raise HTTPException(status_code=400, detail="Invoice is void")
    lead = await invoice_service.fetch_customer(session, invoice)
    try:
        document = await document_service.get_or_create_invoice_document(session, invoice=invoice, lead=lead)
        await audit_service.record_system_action(
            session,
            org_id=invoice.org_id,
            action="PUBLIC_INVOICE_PDF_DOWNLOAD",
            resource_type="invoice",
            resource_id=invoice.invoice_id,
            action_type=AdminAuditActionType.READ,
            sensitivity_level=AdminAuditSensitivity.SENSITIVE,
            context={"token_hash_prefix": invoice_service.hash_public_token(token)[:8]},
        )
        await session.commit()
    except storage_quota_service.OrgStorageQuotaExceeded as exc:
        await session.rollback()
        return problem_details(
            request,
            status=status.HTTP_409_CONFLICT,
            title="Storage quota exceeded",
            detail="Organization storage quota exceeded",
            errors=[
                {
                    "code": "ORG_STORAGE_QUOTA_EXCEEDED",
                    "bytes_requested": exc.requested_bytes,
                    "storage_bytes_used": exc.snapshot.storage_bytes_used,
                    "storage_bytes_pending": exc.snapshot.storage_bytes_pending,
                    "max_storage_bytes": exc.snapshot.max_storage_bytes,
                    "remaining_bytes": exc.snapshot.remaining_bytes,
                }
            ],
        )
    pdf_bytes = document_service.pdf_bytes(document)
    filename = f"{invoice.invoice_number}.pdf"
    headers = {"Content-Disposition": f"inline; filename=\"{filename}\""}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.get(
    "/i/{token}.pdf",
    response_class=Response,
    name="public_invoice_pdf",
)
async def download_invoice_pdf(
    token: str, request: Request, session: AsyncSession = Depends(get_db_session)
) -> Response:
    return await _download_invoice_pdf(token, request, session)


@router.get(
    "/v1/public/invoices/{token}/pdf",
    response_class=Response,
    name="public_invoice_pdf_api",
)
async def download_invoice_pdf_api(
    token: str, request: Request, session: AsyncSession = Depends(get_db_session)
) -> Response:
    return await _download_invoice_pdf(token, request, session)


@router.get(
    "/i/{token}/receipts/{payment_id}.pdf",
    response_class=Response,
    name="public_receipt_pdf",
)
async def download_receipt_pdf(
    token: str, payment_id: str, request: Request, session: AsyncSession = Depends(get_db_session)
) -> Response:
    invoice = await invoice_service.get_invoice_by_public_token(session, token)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    payment = next((p for p in invoice.payments if p.payment_id == payment_id), None)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.status != invoice_statuses.PAYMENT_STATUS_SUCCEEDED:
        raise HTTPException(status_code=400, detail="Receipt available only for successful payments")
    lead = await invoice_service.fetch_customer(session, invoice)
    try:
        document = await document_service.get_or_create_receipt_document(
            session, invoice=invoice, payment=payment, lead=lead
        )
        await session.commit()
    except storage_quota_service.OrgStorageQuotaExceeded as exc:
        await session.rollback()
        return problem_details(
            request,
            status=status.HTTP_409_CONFLICT,
            title="Storage quota exceeded",
            detail="Organization storage quota exceeded",
            errors=[
                {
                    "code": "ORG_STORAGE_QUOTA_EXCEEDED",
                    "bytes_requested": exc.requested_bytes,
                    "storage_bytes_used": exc.snapshot.storage_bytes_used,
                    "storage_bytes_pending": exc.snapshot.storage_bytes_pending,
                    "max_storage_bytes": exc.snapshot.max_storage_bytes,
                    "remaining_bytes": exc.snapshot.remaining_bytes,
                }
            ],
        )
    pdf_bytes = document_service.pdf_bytes(document)
    filename = f"{invoice.invoice_number}-receipt.pdf"
    headers = {"Content-Disposition": f"inline; filename=\"{filename}\""}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.get(
    "/i/{token}/service-agreement.pdf",
    response_class=Response,
    name="public_service_agreement_pdf",
)
async def download_service_agreement_pdf(
    token: str, request: Request, session: AsyncSession = Depends(get_db_session)
) -> Response:
    invoice = await invoice_service.get_invoice_by_public_token(session, token)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.order_id is None:
        raise HTTPException(status_code=404, detail="No related booking for agreement")
    booking = await session.get(Booking, invoice.order_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    lead = await invoice_service.fetch_customer(session, invoice)
    client = await session.get(ClientUser, booking.client_id) if booking.client_id else None
    try:
        document = await document_service.get_or_create_service_agreement_document(
            session, booking=booking, lead=lead, client=client
        )
        await session.commit()
    except storage_quota_service.OrgStorageQuotaExceeded as exc:
        await session.rollback()
        return problem_details(
            request,
            status=status.HTTP_409_CONFLICT,
            title="Storage quota exceeded",
            detail="Organization storage quota exceeded",
            errors=[
                {
                    "code": "ORG_STORAGE_QUOTA_EXCEEDED",
                    "bytes_requested": exc.requested_bytes,
                    "storage_bytes_used": exc.snapshot.storage_bytes_used,
                    "storage_bytes_pending": exc.snapshot.storage_bytes_pending,
                    "max_storage_bytes": exc.snapshot.max_storage_bytes,
                    "remaining_bytes": exc.snapshot.remaining_bytes,
                }
            ],
        )
    pdf_bytes = document_service.pdf_bytes(document)
    filename = f"{invoice.invoice_number}-service-agreement.pdf"
    headers = {"Content-Disposition": f"inline; filename=\"{filename}\""}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.get("/i/{token}", response_class=HTMLResponse, name="public_invoice_view")
async def view_invoice(
    token: str, request: Request, session: AsyncSession = Depends(get_db_session)
) -> HTMLResponse:
    invoice = await invoice_service.get_invoice_by_public_token(session, token)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    lead = await invoice_service.fetch_customer(session, invoice)
    context = invoice_service.build_public_invoice_view(invoice, lead)
    context["token"] = token
    html = _render_invoice_html(context)
    return HTMLResponse(content=html)


@router.post(
    "/i/{token}/pay",
    response_model=invoice_schemas.InvoicePaymentInitResponse,
    status_code=status.HTTP_201_CREATED,
    name="public_invoice_pay",
)
async def create_invoice_payment(
    token: str,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> invoice_schemas.InvoicePaymentInitResponse:
    invoice = await invoice_service.get_invoice_by_public_token(session, token)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == invoice_statuses.INVOICE_STATUS_VOID:
        raise HTTPException(status_code=409, detail="Invoice is void")
    if invoice.status == invoice_statuses.INVOICE_STATUS_DRAFT:
        raise HTTPException(status_code=409, detail="Invoice not sent yet")
    if not settings.stripe_secret_key:
        logger.warning(
            "public_dependency_unavailable",
            extra={
                "extra": {
                    "dependency": "stripe_checkout",
                    "path": http_request.url.path,
                    "method": http_request.method,
                }
            },
        )
        raise HTTPException(status_code=503, detail="Stripe not configured")

    outstanding = invoice_service.outstanding_balance_cents(invoice)
    if outstanding <= 0:
        raise HTTPException(status_code=409, detail="Invoice already paid")

    lead = await invoice_service.fetch_customer(session, invoice)
    stripe_client = _stripe_client(http_request)
    checkout_session = await stripe_infra.create_checkout_session(
        stripe_client=stripe_client,
        secret_key=settings.stripe_secret_key,
        amount_cents=outstanding,
        currency=invoice.currency.lower(),
        success_url=settings.stripe_invoice_success_url.replace("{INVOICE_ID}", invoice.invoice_id),
        cancel_url=settings.stripe_invoice_cancel_url.replace("{INVOICE_ID}", invoice.invoice_id),
        metadata={"invoice_id": invoice.invoice_id, "invoice_number": invoice.invoice_number},
        payment_intent_metadata={"invoice_id": invoice.invoice_id, "invoice_number": invoice.invoice_number},
        product_name=f"Invoice {invoice.invoice_number}",
        customer_email=getattr(lead, "email", None),
    )
    checkout_url = getattr(checkout_session, "url", None) or checkout_session.get("url")
    logger.info(
        "stripe_invoice_checkout_created",
        extra={
            "extra": {
                "invoice_id": invoice.invoice_id,
                "checkout_session_id": getattr(checkout_session, "id", None) or checkout_session.get("id"),
            }
        },
    )

    return invoice_schemas.InvoicePaymentInitResponse(
        provider="stripe",
        amount_cents=outstanding,
        currency=invoice.currency,
        checkout_url=checkout_url,
        client_secret=None,
    )
