"""Finance domain schemas (expenses, budgets, categories)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FinanceExpenseCategoryResponse(BaseModel):
    category_id: UUID
    org_id: UUID
    name: str
    default: bool
    sort_order: int
    created_at: datetime

    class Config:
        from_attributes = True


class FinanceExpenseCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    default: bool = False
    sort_order: int = Field(default=0, ge=0)


class FinanceExpenseCategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    default: bool | None = None
    sort_order: int | None = Field(None, ge=0)


class FinanceExpenseCategoryListResponse(BaseModel):
    items: list[FinanceExpenseCategoryResponse]
    total: int
    page: int
    page_size: int


class FinanceExpenseResponse(BaseModel):
    expense_id: UUID
    org_id: UUID
    occurred_on: date
    category_id: UUID
    vendor: str | None
    description: str
    amount_cents: int
    tax_cents: int
    receipt_url: str | None
    payment_method: str | None
    created_at: datetime
    created_by_user_id: UUID | None
    category_name: str | None = None

    class Config:
        from_attributes = True


class FinanceExpenseCreate(BaseModel):
    occurred_on: date
    category_id: UUID
    vendor: str | None = Field(None, max_length=255)
    description: str = Field(..., min_length=1, max_length=1000)
    amount_cents: int = Field(..., ge=0)
    tax_cents: int = Field(default=0, ge=0)
    receipt_url: str | None = Field(None, max_length=2048)
    payment_method: str | None = Field(None, max_length=50)


class FinanceExpenseUpdate(BaseModel):
    occurred_on: date | None = None
    category_id: UUID | None = None
    vendor: str | None = Field(None, max_length=255)
    description: str | None = Field(None, min_length=1, max_length=1000)
    amount_cents: int | None = Field(None, ge=0)
    tax_cents: int | None = Field(None, ge=0)
    receipt_url: str | None = Field(None, max_length=2048)
    payment_method: str | None = Field(None, max_length=50)


class FinanceExpenseListResponse(BaseModel):
    items: list[FinanceExpenseResponse]
    total: int
    page: int
    page_size: int


class FinanceBudgetResponse(BaseModel):
    budget_id: UUID
    org_id: UUID
    month_yyyymm: str
    category_id: UUID
    amount_cents: int
    created_at: datetime
    category_name: str | None = None

    class Config:
        from_attributes = True


class FinanceBudgetCreate(BaseModel):
    month_yyyymm: str = Field(..., min_length=7, max_length=7)
    category_id: UUID
    amount_cents: int = Field(..., ge=0)

    @field_validator("month_yyyymm")
    @classmethod
    def validate_month(cls, value: str) -> str:
        parts = value.split("-")
        if len(parts) != 2:
            raise ValueError("month_yyyymm must be formatted YYYY-MM")
        year, month = parts
        if len(year) != 4 or len(month) != 2 or not year.isdigit() or not month.isdigit():
            raise ValueError("month_yyyymm must be formatted YYYY-MM")
        month_num = int(month)
        if month_num < 1 or month_num > 12:
            raise ValueError("month_yyyymm must include a valid month")
        return value


class FinanceBudgetUpdate(BaseModel):
    month_yyyymm: str | None = Field(None, min_length=7, max_length=7)
    category_id: UUID | None = None
    amount_cents: int | None = Field(None, ge=0)

    @field_validator("month_yyyymm")
    @classmethod
    def validate_month(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parts = value.split("-")
        if len(parts) != 2:
            raise ValueError("month_yyyymm must be formatted YYYY-MM")
        year, month = parts
        if len(year) != 4 or len(month) != 2 or not year.isdigit() or not month.isdigit():
            raise ValueError("month_yyyymm must be formatted YYYY-MM")
        month_num = int(month)
        if month_num < 1 or month_num > 12:
            raise ValueError("month_yyyymm must include a valid month")
        return value


class FinanceBudgetListResponse(BaseModel):
    items: list[FinanceBudgetResponse]


class FinanceExpenseSummaryCategory(BaseModel):
    category_id: UUID
    category_name: str
    total_cents: int
    tax_cents: int
    budget_cents: int
    percent_of_budget: float | None


class FinanceExpenseSummaryResponse(BaseModel):
    from_date: date
    to_date: date
    total_cents: int
    total_tax_cents: int
    total_budget_cents: int
    percent_of_budget: float | None
    categories: list[FinanceExpenseSummaryCategory]


class FinancePnlBreakdownItem(BaseModel):
    label: str
    total_cents: int


class FinancePnlExpenseCategoryBreakdown(BaseModel):
    category_id: UUID
    category_name: str
    total_cents: int
    tax_cents: int


class FinancePnlDataSources(BaseModel):
    revenue: str
    expenses: str


class FinancePnlResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_date: date = Field(..., alias="from")
    to_date: date = Field(..., alias="to")
    revenue_cents: int
    expense_cents: int
    net_cents: int
    revenue_breakdown: list[FinancePnlBreakdownItem]
    expense_breakdown_by_category: list[FinancePnlExpenseCategoryBreakdown]
    data_sources: FinancePnlDataSources


class FinanceCashSnapshotResponse(BaseModel):
    snapshot_id: UUID
    org_id: UUID
    as_of_date: date
    cash_cents: int
    note: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class FinanceCashSnapshotCreate(BaseModel):
    as_of_date: date
    cash_cents: int
    note: str | None = Field(None, max_length=1000)


class FinanceCashSnapshotUpdate(BaseModel):
    as_of_date: date | None = None
    cash_cents: int | None = None
    note: str | None = Field(None, max_length=1000)


class FinanceCashSnapshotListResponse(BaseModel):
    items: list[FinanceCashSnapshotResponse]


class FinanceCashflowInflowBreakdown(BaseModel):
    method: str
    total_cents: int


class FinanceCashflowOutflowBreakdown(BaseModel):
    category_id: UUID
    category_name: str
    total_cents: int
    tax_cents: int


class FinanceCashflowDataSources(BaseModel):
    inflows: str
    outflows: str


class FinanceCashflowResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_date: date = Field(..., alias="from")
    to_date: date = Field(..., alias="to")
    inflows_cents: int
    outflows_cents: int
    net_movement_cents: int
    inflows_breakdown: list[FinanceCashflowInflowBreakdown]
    outflows_breakdown_by_category: list[FinanceCashflowOutflowBreakdown]
    data_sources: FinanceCashflowDataSources
    start_cash_snapshot: FinanceCashSnapshotResponse | None = None
    end_cash_snapshot: FinanceCashSnapshotResponse | None = None
