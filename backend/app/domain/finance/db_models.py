from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base, UUID_TYPE
from app.settings import settings


class FinanceExpenseCategory(Base):
    __tablename__ = "finance_expense_categories"

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    expenses: Mapped[list["FinanceExpense"]] = relationship(
        "FinanceExpense",
        back_populates="category",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    budgets: Mapped[list["FinanceBudget"]] = relationship(
        "FinanceBudget",
        back_populates="category",
        cascade="save-update, merge",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("ix_finance_expense_categories_org_id", "org_id"),
        Index("ix_finance_expense_categories_org_sort", "org_id", "sort_order"),
    )


class FinanceExpense(Base):
    __tablename__ = "finance_expenses"

    expense_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("finance_expense_categories.category_id", ondelete="RESTRICT"),
        nullable=False,
    )
    vendor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    receipt_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, nullable=True)

    category: Mapped[FinanceExpenseCategory] = relationship(
        "FinanceExpenseCategory",
        back_populates="expenses",
        foreign_keys=[category_id],
    )

    __table_args__ = (
        Index("ix_finance_expenses_org_id", "org_id"),
        Index("ix_finance_expenses_org_occurred", "org_id", "occurred_on"),
        Index("ix_finance_expenses_org_category", "org_id", "category_id"),
    )


class FinanceBudget(Base):
    __tablename__ = "finance_budgets"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    month_yyyymm: Mapped[str] = mapped_column(String(7), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("finance_expense_categories.category_id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    category: Mapped[FinanceExpenseCategory] = relationship(
        "FinanceExpenseCategory",
        back_populates="budgets",
        foreign_keys=[category_id],
    )

    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "month_yyyymm",
            "category_id",
            name="uq_finance_budgets_org_month_category",
        ),
        Index("ix_finance_budgets_org_id", "org_id"),
        Index("ix_finance_budgets_org_month", "org_id", "month_yyyymm"),
        Index("ix_finance_budgets_org_category", "org_id", "category_id"),
    )


class FinanceCashSnapshot(Base):
    __tablename__ = "finance_cash_snapshots"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE,
        ForeignKey("organizations.org_id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: settings.default_org_id,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    cash_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("org_id", "as_of_date", name="uq_finance_cash_snapshots_org_date"),
        Index("ix_finance_cash_snapshots_org_id", "org_id"),
        Index("ix_finance_cash_snapshots_org_date", "org_id", "as_of_date"),
    )
