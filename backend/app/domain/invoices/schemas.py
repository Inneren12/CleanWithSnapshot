from datetime import date, datetime
import uuid
from decimal import Decimal
from typing import List, Literal

from pydantic import BaseModel, Field, field_validator

from app.domain.invoices import statuses
from app.domain.queues.schemas import QuickActionItem


class InvoiceItemCreate(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    qty: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)
    tax_rate: Decimal | None = Field(default=None, ge=0)


class InvoiceCreateRequest(BaseModel):
    issue_date: date | None = None
    due_date: date | None = None
    currency: str = Field(default="CAD", max_length=8)
    notes: str | None = Field(default=None, max_length=1000)
    items: List[InvoiceItemCreate] = Field(min_length=1, max_length=50)


class InvoiceItemResponse(BaseModel):
    item_id: int
    description: str
    qty: int
    unit_price_cents: int
    line_total_cents: int
    tax_rate: float | None = None


class PaymentResponse(BaseModel):
    payment_id: str
    provider: str
    provider_ref: str | None = None
    method: str
    amount_cents: int
    currency: str
    status: str
    received_at: datetime | None = None
    reference: str | None = None
    created_at: datetime


class EmailEventResponse(BaseModel):
    event_id: str
    email_type: str
    recipient: str
    subject: str
    created_at: datetime


class CustomerInfo(BaseModel):
    customer_id: str
    name: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None


class BookingInfo(BaseModel):
    booking_id: str
    booking_number: str | None = None
    scheduled_start: datetime | None = None
    status: str | None = None


class InvoiceResponse(BaseModel):
    invoice_id: str
    invoice_number: str
    order_id: str | None
    customer_id: str | None
    status: str
    issue_date: date
    due_date: date | None
    currency: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    paid_cents: int
    balance_due_cents: int
    notes: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[InvoiceItemResponse]
    payments: list[PaymentResponse]
    email_events: list[EmailEventResponse] = Field(default_factory=list)
    public_link: str | None = None
    customer: CustomerInfo | None = None
    booking: BookingInfo | None = None


class InvoiceListItem(BaseModel):
    invoice_id: str
    invoice_number: str
    order_id: str | None
    customer_id: str | None
    status: str
    issue_date: date
    due_date: date | None
    currency: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    paid_cents: int
    balance_due_cents: int
    created_at: datetime
    updated_at: datetime


class InvoiceListResponse(BaseModel):
    invoices: list[InvoiceListItem]
    page: int
    page_size: int
    total: int


class OverdueInvoiceSummary(BaseModel):
    invoice_id: str
    invoice_number: str
    client: str | None = None
    client_email: str | None = None
    amount_due: int
    due_at: date
    days_overdue: int
    status: str


class OverdueBucketSummary(BaseModel):
    bucket: Literal["critical", "attention", "recent"]
    total_count: int
    total_amount_due: int
    template_key: str
    invoices: list[OverdueInvoiceSummary]


class OverdueSummaryResponse(BaseModel):
    as_of: date
    buckets: list[OverdueBucketSummary]


class OverdueRemindRequest(BaseModel):
    bucket: Literal["critical", "attention", "recent"]
    invoice_ids: list[str] | None = None


class OverdueRemindResponse(BaseModel):
    bucket: Literal["critical", "attention", "recent"]
    template_key: str
    succeeded: list[str]
    failed: list[dict]


class ManualPaymentRequest(BaseModel):
    amount_cents: int = Field(gt=0)
    method: str = Field(pattern="^(cash|etransfer|other|card)$")
    reference: str | None = Field(default=None, max_length=255)
    received_at: datetime | None = None

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in statuses.PAYMENT_METHODS:
            raise ValueError("Invalid payment method")
        return normalized


class InvoiceStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        return statuses.normalize_status(value)


class ManualPaymentResult(BaseModel):
    invoice: InvoiceResponse
    payment: PaymentResponse


class InvoiceSendResponse(BaseModel):
    invoice: InvoiceResponse
    public_link: str
    email_sent: bool


class InvoicePaymentInitResponse(BaseModel):
    provider: str
    amount_cents: int
    currency: str
    checkout_url: str | None = None
    client_secret: str | None = None


class GstReportResponse(BaseModel):
    range_start: date
    range_end: date
    invoice_count: int
    taxable_subtotal_cents: int
    tax_cents: int


class SalesLedgerRow(BaseModel):
    invoice_number: str
    issue_date: date
    due_date: date | None
    status: str
    currency: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    paid_cents: int
    balance_due_cents: int
    customer_id: str | None = None
    booking_id: str | None = None


class PaymentLedgerRow(BaseModel):
    payment_id: str
    invoice_number: str | None
    booking_id: str | None
    provider: str
    method: str
    status: str
    amount_cents: int
    currency: str
    received_at: datetime | None = None
    created_at: datetime


class AccountingExportRow(BaseModel):
    invoice_number: str
    issue_date: date
    due_date: date | None = None
    status: str
    currency: str
    taxable_subtotal_cents: int
    tax_cents: int
    total_cents: int
    paid_cents: int
    payment_fees_cents: int
    balance_due_cents: int
    customer_id: str | None = None
    booking_id: str | None = None
    last_payment_at: datetime | None = None


class PnlRow(BaseModel):
    booking_id: str
    invoice_number: str
    revenue_cents: int
    labour_cents: int
    payment_fees_cents: int
    margin_cents: int
    margin_pct: float | None
    worker_rate_cents: int
    actual_minutes: int


class PnlReportResponse(BaseModel):
    range_start: date
    range_end: date
    rows: list[PnlRow]


class InvoiceReconcileItem(BaseModel):
    invoice_id: str
    invoice_number: str
    status: str
    total_cents: int
    outstanding_cents: int
    succeeded_payments_count: int
    last_payment_at: datetime | None = None
    quick_actions: list[QuickActionItem] = Field(default_factory=list)


class InvoiceReconcileListResponse(BaseModel):
    items: list[InvoiceReconcileItem]
    total: int


class InvoiceReconcileResponse(BaseModel):
    invoice_id: str
    invoice_number: str
    status: str
    total_cents: int
    paid_cents: int
    outstanding_cents: int
    succeeded_payments_count: int


class InvoiceReconcilePlan(BaseModel):
    dry_run: bool = True
    before: InvoiceReconcileResponse
    after: InvoiceReconcileResponse
    planned_operations: list[str]


class StripeEventView(BaseModel):
    event_id: str
    type: str | None = None
    created_at: datetime
    org_id: uuid.UUID | None = None
    invoice_id: str | None = None
    booking_id: str | None = None
    processed_status: str
    last_error: str | None = None


class StripeEventListResponse(BaseModel):
    items: list[StripeEventView]
    total: int
    limit: int
    offset: int


class BulkRemindRequest(BaseModel):
    invoice_ids: list[str] = Field(min_length=1, max_length=100)


class BulkRemindResult(BaseModel):
    succeeded: list[str]
    failed: list[dict]


class BulkMarkPaidRequest(BaseModel):
    invoice_ids: list[str] = Field(min_length=1, max_length=100)
    method: str = Field(pattern="^(cash|etransfer|other|card)$")
    note: str | None = Field(default=None, max_length=500)

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in statuses.PAYMENT_METHODS:
            raise ValueError("Invalid payment method")
        return normalized


class BulkMarkPaidResult(BaseModel):
    succeeded: list[str]
    failed: list[dict]


class InvoiceReminderResponse(BaseModel):
    invoice: InvoiceResponse
    email_sent: bool
    recipient: str
