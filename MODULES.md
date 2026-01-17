# Product Modules Map

This document maps all major product modules in CleanWithSnapshot, showing where to find and modify features.

---

## Module Visibility System

Modules can be toggled at three levels:

1. **Organization-level** - Enable/disable entire modules for an org
2. **Role-level** - Permission requirements to access features
3. **User-level** - Individual users can hide modules from their UI

**Feature visibility precedence:** Org enabled → Role has permission → Not user-hidden

---

## Module Keys (16 Total)

These keys control visibility in the admin panel:

```
module.dashboard              # Main dashboard
module.schedule               # Scheduling/dispatcher
module.invoices               # Invoicing
module.quality                # Quality checks
module.teams                  # Team management
module.analytics              # Analytics/reports
module.finance                # Finance
module.pricing                # Pricing configuration
module.marketing              # Marketing
module.leads                  # Leads
module.inventory              # Inventory
module.training               # Training
module.notifications_center   # Notifications
module.settings               # Organization settings
module.integrations           # Integrations
module.api                    # API access
```

**Integrations subfeatures:**

```
integrations.google_calendar  # Google Calendar OAuth + sync (feature gated)
```

**Configuration:**
- Backend: `backend/app/domain/feature_modules/service.py`
- Frontend: `web/app/admin/lib/featureVisibility.ts`
- Database: `feature_modules` table (org-level toggles)

---

## Core Business Modules

### 1. Dashboard

**Purpose:** Overview KPIs, recent activity, quick actions

**Key Pages:**
- `web/app/admin/page.tsx` - Main dashboard
- `web/app/admin/dashboard/ops/page.tsx` - Ops dashboard UI (`/admin/dashboard/ops`)

**Backend Routers:**
- `backend/app/api/routes_admin.py` - `/v1/admin/ui/dashboard` (GET)
- `backend/app/api/routes_admin.py` - `/v1/admin/dashboard/ops` (GET, ops aggregates)
- `backend/app/api/routes_admin.py` - `/v1/admin/activity` (GET, activity feed polling)

**Key Services:**
- N/A (dashboard aggregates data from other modules)

**Ops dashboard bands:**
- Booking status band model: `backend/app/domain/ops/schemas.py::OpsDashboardBookingStatusBand`.
- Band definitions: `backend/app/domain/ops/service.py::BOOKING_STATUS_BANDS` (edit here to change ranges).

**Ops dashboard data sources:**
- `critical_alerts` is a projection of unread CRITICAL/HIGH notifications from the notifications center
  (`backend/app/api/routes_admin.py::_build_ops_critical_alerts()`), gated by `module.notifications_center`.
- `quality_today` draws from client feedback and quality issues in
  `backend/app/api/routes_admin.py::_build_ops_quality_today()`.
- `upcoming_events` aggregates next-24h critical items from bookings, invoices, and availability blocks in
  `backend/app/api/routes_admin.py::_build_ops_upcoming_events()` (unassigned bookings, first booking tomorrow,
  invoices due today, training blocks).
- `booking_status_today` counts bookings from `backend/app/api/routes_admin.py::get_ops_dashboard()` and uses
  `backend/app/domain/ops/service.py::build_booking_status_bands()`.

**Key Tables:**
- `events` - Analytics events
- `bookings` - Recent bookings
- `invoices` - Invoice summary

**Permissions Required:**
- `core.view` - Read-only dashboard access

**Feature Key:** `module.dashboard`

**How to add a new Critical Alert type:**

1. **Backend schema:** Update `backend/app/domain/ops/schemas.py` to add new alert fields if needed and extend `OpsDashboardAlert` metadata.
2. **Backend data:** Update `backend/app/api/routes_admin.py::get_ops_dashboard()` and `_build_ops_critical_alerts()` to calculate the new alert, respecting org scoping and permission checks.
3. **Permissions:** Use `permission_keys_for_request()` and guard finance alerts with `invoices.view` + `finance.view`, scheduling alerts with `bookings.view`, etc.
4. **Frontend:** Render the new alert in `web/app/admin/dashboard/ops/page.tsx` and provide CTA links.
5. **Docs & tests:** Document the alert shape in `API_ENTRYPOINTS.md` and add coverage in `backend/tests/test_admin_ops_dashboard.py`.

---

### 2. Schedule

**Purpose:** Team calendars, worker availability, blocking periods, quick booking creation

**Key Pages:**
- `web/app/admin/schedule/page.tsx` - Schedule view
- `web/app/admin/SchedulePageClient.tsx` - Client-side calendar

**Backend Routers:**
- `backend/app/api/routes_admin.py` - `/v1/admin/ui/schedule` (GET)
- `backend/app/api/routes_bookings.py` - `/v1/bookings/*` (availability, slot search)

**Key Services:**
- `backend/app/domain/bookings/service.py` - Booking CRUD
- `backend/app/domain/scheduling/availability/service.py` - Availability blocking

**Key Tables:**
- `bookings` - Job records
- `teams` - Team definitions
- `team_working_hours` - Regular working hours
- `team_blackout` - Availability blocks (vacation, maintenance, etc.)
- `booking_workers` - Worker assignments

**Permissions Required:**
- `bookings.view` - View schedule
- `bookings.edit` - Edit bookings
- `bookings.assign` - Assign workers
- `schedule.blocking.manage` - Manage availability blocks

**Feature Key:** `module.schedule`

**Where to Change:**

#### Schedule Week/Day View
- Frontend: `web/app/admin/schedule/page.tsx`
- API: `backend/app/api/routes_admin.py::/v1/admin/schedule`

#### Schedule Team Calendar View
- Frontend: `web/app/admin/schedule/SchedulePageClient.tsx` (Teams tab)
- API: `backend/app/api/routes_admin.py::/v1/admin/schedule/team_calendar`
- Service: `backend/app/domain/ops/service.py::list_team_calendar()` (org TZ aggregation)

**Recurring series behavior:** Removing or cancelling a recurring series preserves existing bookings;
the series link is cleared while historical bookings remain.

#### Worker Timeline View
- Frontend: `web/app/admin/schedule/SchedulePageClient.tsx` (Timeline tab)
- API: `backend/app/api/routes_admin.py::/v1/admin/schedule/worker_timeline`
- Service: `backend/app/domain/ops/service.py::list_worker_timeline()` (org TZ aggregation)

#### Schedule List View (table + bulk actions)
- Frontend: `web/app/admin/schedule/SchedulePageClient.tsx` (list mode UI, filters, export/print panel with week/month/custom range + notes toggle)
- Styles: `web/app/styles/components.css` (schedule list/table styles)
- API: `backend/app/api/routes_admin.py::/v1/admin/schedule` (date range + paging + query params)

#### Quick Create Booking
- Frontend: `web/app/admin/schedule/` (quick create form)
- API: `backend/app/api/routes_admin.py::/v1/admin/ui/bookings/create`
- Service: `backend/app/domain/bookings/service.py::create_booking()`

#### Conflict Detection
- Service: `backend/app/domain/bookings/service.py::check_conflicts()`
- Logic: Checks for overlapping bookings by team/worker
- Availability/busy status respects booking buffer minutes (`BUFFER_MINUTES`).

#### Availability Blocking
- Frontend: `web/app/admin/settings/availability-blocks/page.tsx`
- API: `backend/app/api/routes_admin_settings.py::/v1/admin/settings/availability-blocks`
- Service: `backend/app/domain/scheduling/availability/service.py`
- Table: `team_blackout`

---

### 3. Invoices

**Purpose:** Invoice creation, editing, payment tracking, bulk actions, public invoice links

**Key Pages:**
- `web/app/admin/invoices/page.tsx` - Invoice list
- `web/app/admin/invoices/[id]/page.tsx` - Invoice detail

**Backend Routers:**
- `backend/app/api/routes_admin.py` - `/v1/admin/ui/invoices/*` (CRUD)
- `backend/app/api/routes_payments.py` - `/v1/payments/*` (Stripe integration)

**Key Services:**
- `backend/app/domain/invoices/service.py` - Invoice CRUD, status updates
- `backend/app/domain/invoices/statuses.py` - Status enum definitions

**Key Tables:**
- `invoices` - Invoice headers
- `invoice_items` - Line items
- `invoice_public_tokens` - Public access tokens for client view
- `payments` - Payment records
- `stripe_events` - Stripe webhook events

**Permissions Required:**
- `invoices.view` - Read invoices
- `invoices.edit` - Create/update invoices
- `payments.record` - Record payments

**Feature Key:** `module.invoices`

**Where to Change:**

#### Invoice List View
- Frontend: `web/app/admin/invoices/page.tsx`
- API: `backend/app/api/routes_admin.py::/v1/admin/ui/invoices` (GET)

#### Invoice Detail Page
- Frontend: `web/app/admin/invoices/[id]/page.tsx`
- API: `backend/app/api/routes_admin.py::/v1/admin/ui/invoices/{id}` (GET)

#### Overdue Alerts
- Frontend: `web/app/admin/invoices/page.tsx` (overdue summary cards + quick actions)
- API: `backend/app/api/routes_admin.py::/v1/admin/invoices/overdue_summary` (GET)
- API: `backend/app/api/routes_admin.py::/v1/admin/invoices/overdue_remind` (POST)
- Where to change bucketing rules: `backend/app/api/routes_admin.py::_bucket_for_days_overdue()` and `_overdue_bucket_bounds()`

#### Bulk Actions
- API: `backend/app/api/routes_admin.py` (bulk status updates, exports)
- Service: `backend/app/domain/invoices/service.py::bulk_update_status()`

#### Public Link Token
- Service: `backend/app/domain/invoices/service.py::create_public_token()`
- Table: `invoice_public_tokens`
- Public endpoint: `/v1/public/invoices/{token}`

#### PDF Generation
- Location: TBD (not yet implemented, placeholder exists)

---

### 4. Dispatcher

**Purpose:** Real-time dispatch board, worker routing, job assignments, AI optimization

**Key Pages:**
- `web/app/admin/dispatcher/page.tsx` - Dispatch board

**Backend Routers:**
- `backend/app/api/routes_dispatcher.py` - `/v1/dispatcher/*`

**Key Services:**
- `backend/app/domain/dispatcher/service.py` - Route optimization
- `backend/app/domain/dispatcher/ai_suggestions.py` - AI-powered assignment suggestions

**Key Tables:**
- `bookings` - Jobs to assign
- `booking_workers` - Worker assignments
- `workers` - Worker pool
- `teams` - Team definitions

**Permissions Required:**
- `bookings.view` - View dispatch board
- `bookings.assign` - Assign workers to jobs

**Feature Key:** `module.schedule` (shared with schedule)

**Where to Change:**

#### Dispatch Board UI
- Frontend: `web/app/admin/dispatcher/page.tsx`
- API: `backend/app/api/routes_dispatcher.py::/v1/dispatcher/board`

#### AI Suggestions
- Service: `backend/app/domain/dispatcher/ai_suggestions.py`
- Toggle: User-level preference `schedule.optimization_ai`

#### Route Optimization
- Service: `backend/app/domain/dispatcher/service.py::optimize_routes()`

---

### 5. Teams

**Purpose:** Worker team management, team schedules, team assignments

**Key Pages:**
- `web/app/admin/teams/page.tsx` - Teams list (`/admin/teams`)
- `web/app/admin/teams/[team_id]/page.tsx` - Team detail (`/admin/teams/{id}`)
- `web/app/admin/teams/compare/page.tsx` - Team comparison (`/admin/teams/compare`)

**Team schedule note:** Weekly team schedule grouping uses the organization timezone for day buckets
and headers to avoid UTC shifts for near-midnight bookings.

**Backend Routers:**
- `backend/app/api/routes_admin.py` - `/v1/admin/teams`, `/v1/admin/teams/{id}/*`, `/v1/admin/ui/teams/*`

**Key Services:**
- `backend/app/domain/workers/service.py` - Worker/team CRUD

**Key Tables:**
- `teams` - Team records
- `workers` - Worker records (FK to team)
- `team_working_hours` - Regular schedules
- `team_blackout` - Unavailability periods

**ORM note:** `Team` and `Worker` models live in `backend/app/domain/bookings/db_models.py` and
`backend/app/domain/workers/db_models.py`; membership and lead relationships use explicit
`foreign_keys` to avoid ambiguity.

**Permissions Required:**
- `core.view` - View teams
- `users.manage` - Manage workers/teams

**Feature Key:** `module.teams`

**Where to Change:**

#### Worker Management
- API: `backend/app/api/routes_admin.py::/v1/admin/ui/workers`
- Service: `backend/app/domain/workers/service.py`
- Guide: [docs/ADMIN_GUIDE.md](./docs/ADMIN_GUIDE.md#worker-password-management)

#### Team Reporting
- API: `backend/app/api/routes_admin.py::/v1/admin/teams`
- Detail: `backend/app/api/routes_admin.py::/v1/admin/teams/{id}`, `/members`, `/recent_bookings`, `/metrics`
- Comparison: `backend/app/api/routes_admin.py::/v1/admin/teams/compare`
- Frontend: `web/app/admin/teams/`

---

### 6. Quality

**Purpose:** Quality issue triage, complaints tracking, and operational checklists

**Key Pages:**
- `web/app/admin/quality/issues/[id]/page.tsx` - Issue detail workflow (`/admin/quality/issues/{id}`)
- `web/app/admin/quality/common/page.tsx` - Common issue tags analytics (`/admin/quality/common`)
- `web/app/admin/quality/reviews/page.tsx` - Reviews timeline + reply tools (`/admin/quality/reviews`)
- `web/app/admin/quality/leaderboard/page.tsx` - Worker quality leaderboard (`/admin/quality/leaderboard`)

**Backend Routers:**
- `backend/app/api/routes_admin.py` - `/v1/admin/quality/issues` (list + filters)
- `backend/app/api/routes_admin.py` - `/v1/admin/quality/issues/{id}` (detail)
- `backend/app/api/routes_admin.py` - `/v1/admin/quality/issues/{id}` (PATCH status/resolution)
- `backend/app/api/routes_admin.py` - `/v1/admin/quality/issues/{id}/tags` (apply issue tags)
- `backend/app/api/routes_admin.py` - `/v1/admin/quality/issues/{id}/respond` (response log + SLA timestamp)
- `backend/app/api/routes_admin.py` - `/v1/admin/quality/issues/triage` (Critical/Medium/Low buckets)
- `backend/app/api/routes_admin.py` - `/v1/admin/quality/issues/common` (common issue tags analytics)
- `backend/app/api/routes_admin.py` - `/v1/admin/quality/reviews` (client reviews list + filters)
- `backend/app/api/routes_admin.py` - `/v1/admin/quality/ratings/distribution` (monthly rating distribution)
- `backend/app/api/routes_admin.py` - `/v1/admin/quality/workers/leaderboard` (worker rating/review/complaint leaderboard)
- `backend/app/api/routes_admin.py` - `/v1/admin/quality/reviews/{id}/reply` (review reply logging)
- `backend/app/api/routes_checklists.py` - `/v1/checklists/*` (job checklists)

**Key Services:**
- `backend/app/domain/quality/service.py` - Issue triage + severity logic
- `backend/app/domain/quality/service.py` - Review list + reply logging + template catalog
- `backend/app/domain/checklists/service.py` - Checklist CRUD

**Key Tables:**
- `quality_issues` - Issue/complaint records
- `quality_issue_tags` - Issue tag mappings
- `quality_tag_catalog` - Allowed tag catalog
- `quality_review_replies` - Logged review replies
- `checklists` - Checklist templates
- `checklist_items` - Individual check items

**Review templates:** Stored in `backend/app/domain/quality/service.py` as `REVIEW_REPLY_TEMPLATES` (returned via the reviews list endpoint).

**Common issues analytics:** `/v1/admin/quality/issues/common` supports `from`/`to` query params to scope the date range (defaults to the last 30 days).

**Tag ordering:** Tag assignment order is stored in `quality_issue_tags.position` and returned in that position order.

**Permissions Required:**
- `quality.view` - View issue triage + issue details
- `quality.manage` - Resolve/manage issues (future mutations)
- `bookings.view` - View job checklists
- `bookings.edit` - Update checklists

**Feature Key:** `module.quality`

**Where to Change:**
- API: `backend/app/api/routes_admin.py::/v1/admin/quality/issues`
- Service: `backend/app/domain/quality/service.py`
- Models: `backend/app/domain/quality/db_models.py`
- Service breakdown: `backend/app/api/routes_admin.py::/v1/admin/quality/services/breakdown`,
  `backend/app/domain/quality/service.py::get_service_quality_breakdown()`,
  `web/app/admin/quality/page.tsx`
- Detail widgets: `web/app/admin/workers/[id]/page.tsx` and
  `web/app/admin/clients/[id]/page.tsx` (quality summary widgets linking to `/admin/quality`)

---

### 7. Analytics

**Purpose:** Reports, KPIs, operational dashboards

**Key Pages:**
- `web/app/admin/analytics/page.tsx` - Financial summary (`/admin/analytics`)
- `web/app/admin/analytics/funnel/page.tsx` - Booking funnel (`/admin/analytics/funnel`)
- `web/app/admin/analytics/geo/page.tsx` - Geo heatmap by area (`/admin/analytics/geo`)
- `web/app/admin/analytics/clients/page.tsx` - Client CLV + retention cohorts (`/admin/analytics/clients`)

**Backend Routers:**
- `backend/app/api/routes_admin.py` - Analytics endpoints (`/v1/admin/analytics/*`)

**Key Services:**
- `backend/app/domain/analytics/service.py` - Event aggregation, KPI calculation, geo heatmap aggregates,
  client CLV summaries, retention cohorts

**Key Tables:**
- `events` - Analytics events
- `leads` - Inquiry records (funnel entry point)
- `lead_quotes` - Quotes tied to inquiries
- `bookings` - Job data
- `invoices` - Financial data
- `invoice_payments` - Paid revenue signals
- `client_users` - Client identities for CLV/retention
- `client_addresses` - Area labels + coordinates
- `teams` - Zone metadata
- `nps_responses` - Post-service reviews

**Permissions Required:**
- `reports.view` - View reports
- `finance.view` - Finance analytics

**Feature Key:** `module.analytics`

---

### 8. Finance

**Purpose:** Financial reporting, payment reconciliation, and expense tracking

**Key Pages:**
- `web/app/admin/finance/expenses/page.tsx` - Expense tracking (`/admin/finance/expenses`)
- `web/app/admin/finance/budgets/page.tsx` - Monthly budgets (`/admin/finance/budgets`)
- `web/app/admin/finance/pnl/page.tsx` - Profit & Loss report (`/admin/finance/pnl`)
- `web/app/admin/finance/cashflow/page.tsx` - Cashflow report (`/admin/finance/cashflow`)
- `web/app/admin/finance/balance-sheet/page.tsx` - Balance sheet (simplified) (`/admin/finance/balance-sheet`)
- `web/app/admin/finance/taxes/page.tsx` - GST summary, instalments, calendar, exports (`/admin/finance/taxes`)

**Backend Routers:**
- `backend/app/api/routes_admin_finance.py` - Expense categories, expenses, budgets, P&L, cashflow, snapshots, summary
- `backend/app/api/routes_admin.py` - Invoice reconciliation endpoints
- `backend/app/api/routes_payments.py` - Payment processing

**Key Services:**
- `backend/app/domain/finance/service.py` - Expense/budget CRUD + summaries, cashflow, snapshots
- `backend/app/domain/invoices/service.py` - Invoice/payment logic

**Key Tables:**
- `finance_expense_categories` - Expense category catalog
- `finance_expenses` - Expense ledger (by day)
- `finance_budgets` - Monthly category budgets
- `finance_cash_snapshots` - Optional cash balance snapshots
- `finance_tax_instalments` - Manual GST instalment tracking
- `finance_tax_exports` - GST export audit log
- `invoices` - Invoice records
- `payments` - Payment records
- `stripe_events` - Stripe webhooks

**Permissions Required:**
- `finance.view` - View finance reports
- `finance.manage` - Manage expenses/budgets
- `invoices.view` - View invoices
- `payments.record` - Record payments

**Feature Key:** `module.finance`

---

### 9. Pricing

**Purpose:** Service pricing configuration, rate management

**Key Pages:**
- `web/app/admin/settings/pricing/page.tsx` - Pricing settings

**Backend Routers:**
- `backend/app/api/routes_admin_pricing.py` - `/v1/admin/pricing/*`

**Key Services:**
- `backend/app/domain/pricing/service.py` - Pricing calculations
- `backend/app/domain/pricing_settings/service.py` - Price config management

**Key Tables:**
- `pricing_configs` (or JSON file: `pricing/economy_v1.json`)

**Permissions Required:**
- `pricing.manage` - Manage pricing

**Feature Key:** `module.pricing`

---

### 10. Marketing

**Purpose:** Marketing analytics, manual email campaigns, promotional codes, and discount governance

**Key Pages:**
- `web/app/admin/marketing/promo-codes/page.tsx` - Promo code management
- `web/app/admin/marketing/analytics/page.tsx` - Lead source analytics + manual spend entry
- `web/app/admin/marketing/email-campaigns/page.tsx` - Manual email campaigns list + segment management
- `web/app/admin/marketing/email-campaigns/[campaignId]/page.tsx` - Campaign detail + scheduling

**Backend Routers:**
- `backend/app/api/routes_admin_marketing.py` - `/v1/admin/marketing/promo-codes`
- `backend/app/api/routes_admin_marketing.py` - `/v1/admin/marketing/analytics/lead-sources`
- `backend/app/api/routes_admin_marketing.py` - `/v1/admin/marketing/spend`
- `backend/app/api/routes_admin_marketing.py` - `/v1/admin/marketing/email-segments`
- `backend/app/api/routes_admin_marketing.py` - `/v1/admin/marketing/email-campaigns`
- `backend/app/api/routes_admin_marketing.py` - `/v1/admin/marketing/referrals/leaderboard`

**Key Services:**
- `backend/app/domain/marketing/service.py` - Promo code CRUD + validation
- `backend/app/domain/marketing/service.py` - Lead source analytics + spend tracking
- `backend/app/domain/marketing/service.py` - Email segment + campaign CRUD
- `backend/app/domain/marketing/service.py` - Referral leaderboard aggregation (`list_referral_leaderboard`)

**Key Tables:**
- `promo_codes` - Promo definitions and restrictions
- `promo_code_redemptions` - Redemption log for limits and per-customer rules
- `marketing_spend` - Manual monthly spend by lead source
- `email_segments` - Manual email recipient definitions
- `email_campaigns` - Manual email campaigns with schedule metadata
- `referral_credits` - Referral credit ledger (triggered by org settings `referral_credit_trigger`)

**Permissions Required:**
- `settings.manage` - Manage marketing settings and promo codes

**Feature Key:** `module.marketing`

---

### 11. Leads

**Purpose:** Lead capture, qualification, conversion tracking

**Key Pages:**
- `web/app/page.tsx` - Public lead capture form
- `web/app/admin/leads/page.tsx` - Lead pipeline list + status updates
- `web/app/admin/leads/[lead_id]/page.tsx` - Lead detail (contact, notes, timeline, schedule CTA)

**Backend Routers:**
- `backend/app/api/routes_leads.py` - `/v1/leads/*`
- `backend/app/api/routes_public.py` - `/v1/public/leads` (public submission)
- `backend/app/api/routes_admin.py` - `/v1/admin/leads` (list, detail, update, timeline, quotes)

**Key Services:**
- `backend/app/domain/leads/service.py` - Lead CRUD, status management, quote helpers

**Key Tables:**
- `leads` - Lead records (status, loss reason, attribution fields, notes)
- `lead_quotes` - Lead quote log (amount, currency, service type, status, expiry, sent timestamp)
- `lead_quote_followups` - Manual quote follow-up notes

**Permissions Required:**
- `contacts.view` - View leads
- `contacts.edit` - Update leads

**Feature Key:** `module.leads`

---

### 12. Inventory

**Purpose:** Cleaning supplies inventory management

**Data model:**
- `inventory_categories` - Product categories (org-scoped, sortable)
- `inventory_items` - Inventory items (category FK, SKU, unit, active flag, stock fields)
- `inventory_suppliers` - Supplier directory (contact info, ordering terms, minimum order)
- `purchase_orders` - Purchase order headers (status, totals, timestamps)
- `purchase_order_items` - Purchase order line items (qty, unit cost, totals)

**Key Tables:**
- `inventory_categories` (category_id UUID pk, org_id, name, sort_order)
- `inventory_items` (item_id UUID pk, org_id, category_id nullable FK, sku, name, unit, current_qty, min_qty, location_label, active)
- `inventory_suppliers` (supplier_id UUID pk, org_id, name, email, phone, address, terms, delivery_days, min_order_cents, notes, created_at)
- `purchase_orders` (po_id UUID pk, org_id, supplier_id, status, ordered_at, received_at, notes, subtotal_cents, tax_cents, shipping_cents, total_cents)
- `purchase_order_items` (po_item_id UUID pk, po_id, item_id, qty, unit_cost_cents, line_total_cents)

**Indexes:**
- `(org_id, name)` for search
- `(org_id, active)` for filtering

**Backend Routers:**
- `backend/app/api/routes_admin_inventory.py` - `/v1/admin/inventory/*` (Categories, Items, Suppliers, Purchase Orders)

**Key Services:**
- `backend/app/domain/inventory/service.py` - Category/Item CRUD, supplier CRUD, purchase order lifecycle

**Key Schemas:**
- `backend/app/domain/inventory/schemas.py` - Request/response models

**Permissions Required:**
- `inventory.view` or `core.view` - List and view categories/items
- `inventory.manage` or `admin.manage` - Create, update, delete categories/items
- `inventory.view` - Low stock list endpoint (`/v1/admin/inventory/low_stock`)
- `inventory.manage` or `admin.manage` - Create, update, mark ordered, and mark received purchase orders

**Expected Status Codes:**
- `401` - Missing/invalid admin auth
- `403` - Authenticated but missing permission
- `400` - Validation errors (e.g., invalid category)
- `404` - Missing or cross-org resources

**Feature Key:** `module.inventory`

**Cascade Behavior:**
- Deleting a category **preserves** items (category_id set to NULL)
- FK constraint: `ondelete="SET NULL"`
- ORM relationship: `passive_deletes=True`, no `delete-orphan`
- SQLite tests require PRAGMA foreign_keys=ON; use shared fixtures.

**Where to Change:**

#### Category CRUD
- API: `backend/app/api/routes_admin_inventory.py` - `/v1/admin/inventory/categories/*`
- Service: `backend/app/domain/inventory/service.py` - `list_categories()`, `create_category()`, `update_category()`, `delete_category()`
- Models: `backend/app/domain/inventory/db_models.py` - `InventoryCategory`

#### Item CRUD
- API: `backend/app/api/routes_admin_inventory.py` - `/v1/admin/inventory/items/*`
- Service: `backend/app/domain/inventory/service.py` - `list_items()`, `create_item()`, `update_item()`, `delete_item()`
- Models: `backend/app/domain/inventory/db_models.py` - `InventoryItem`

#### Low Stock Monitoring
- API: `backend/app/api/routes_admin_inventory.py` - `/v1/admin/inventory/low_stock`
- Service: `backend/app/domain/inventory/service.py` - `list_low_stock_items()`
- Semantics: `need_qty = max(0, min_qty - current_qty)` with ordering by `need_qty` desc, then `name` asc
- Default filter: `only_below_min=true` returns items where `current_qty < min_qty`

#### Supplier CRUD
- API: `backend/app/api/routes_admin_inventory.py` - `/v1/admin/inventory/suppliers/*`
- Service: `backend/app/domain/inventory/service.py` - `list_suppliers()`, `create_supplier()`, `update_supplier()`, `delete_supplier()`
- Models: `backend/app/domain/inventory/db_models.py` - `InventorySupplier`

#### Purchase Orders
- API: `backend/app/api/routes_admin_inventory.py` - `/v1/admin/inventory/purchase-orders/*`
- Service: `backend/app/domain/inventory/service.py` - `list_purchase_orders()`, `create_purchase_order()`, `mark_purchase_order_ordered()`, `mark_purchase_order_received()`
- Models: `backend/app/domain/inventory/db_models.py` - `PurchaseOrder`, `PurchaseOrderItem`
- UI note: draft purchase orders default missing totals to `0` until all line inputs are valid.
- Notes: `PATCH /v1/admin/inventory/purchase-orders/{po_id}` clears notes when sent `notes: ""` (omit `notes` to keep existing).

#### Search and Pagination
- Implement in service layer using SQLAlchemy filters
- Category search: name (ilike)
- Item search: name or SKU (ilike)
- Supplier search: name, email, or phone (ilike)
- Pagination: page + page_size with total count from subquery

**Key Pages:**
- `web/app/admin/inventory/page.tsx` - Inventory items list UI (`/admin/inventory`)
- `web/app/admin/inventory/suppliers/page.tsx` - Inventory suppliers UI (`/admin/inventory/suppliers`)

**Status:** API complete with CRUD, org-scoping, RBAC, search, and pagination

---

### 13. Training

**Purpose:** Worker training, certifications, onboarding

**Key Pages:**
- `web/app/admin/workers/[id]/page.tsx` - Worker profile training status card
- `web/app/admin/training/courses/page.tsx` - Training course list + create/edit
- `web/app/admin/training/courses/[course_id]/page.tsx` - Course detail + assignments
- `web/app/admin/training/calendar/page.tsx` - Training calendar sessions + attendee blocking

**Backend Routes:**
- `backend/app/api/routes_admin.py::/v1/admin/training/workers/{worker_id}/status`
- `backend/app/api/routes_admin.py::/v1/admin/training/workers/{worker_id}/records`
- `backend/app/api/routes_admin.py::/v1/admin/training/courses`
- `backend/app/api/routes_admin.py::/v1/admin/training/courses/{course_id}`
- `backend/app/api/routes_admin.py::/v1/admin/training/courses/{course_id}/assignments`
- `backend/app/api/routes_admin.py::/v1/admin/training/courses/{course_id}/assign`
- `backend/app/api/routes_admin.py::/v1/admin/training/workers/{worker_id}/assignments`
- `backend/app/api/routes_admin.py::/v1/admin/training/assignments/{assignment_id}`
- `backend/app/api/routes_admin.py::/v1/admin/training/sessions`
- `backend/app/api/routes_admin.py::/v1/admin/training/sessions/{session_id}`
- `backend/app/api/routes_admin.py::/v1/admin/training/sessions/{session_id}/attendees`
- `backend/app/api/routes_admin.py::/v1/admin/training/workers`

**Key Services:**
- `backend/app/domain/training/service.py` - Training requirement status logic
- `backend/app/domain/training/service.py` - Course and assignment CRUD

**Key Tables:**
- `training_requirements` (training catalog + renewal rules)
- `worker_training_records` (worker completions + expiry)
- `training_courses` (course catalog)
- `training_assignments` (worker assignments + status)
- `training_sessions` (calendar sessions, org TZ → UTC storage)
- `training_session_attendees` (session attendees + attendance status)
- `worker_onboarding` (migration 0072)
- `worker_certificates` (migration 0072)

**Where to Change Worker Status Logic:**
- Status computation and next-due logic: `backend/app/domain/training/service.py::build_training_status_payload()`
- Training UI rendering: `web/app/admin/workers/[id]/page.tsx`

**Where to Change Courses & Assignments:**
- API + service logic: `backend/app/api/routes_admin.py` and `backend/app/domain/training/service.py`
- Course list UI: `web/app/admin/training/courses/page.tsx`
- Course detail + assignments UI: `web/app/admin/training/courses/[course_id]/page.tsx`

**Training Calendar Sessions & Schedule Blocking:**
- Sessions are managed in `backend/app/domain/training/service.py` and create `availability_blocks` (`block_type=training`)
  for each attendee so schedule/dispatch respects training time.
- Calendar UI: `web/app/admin/training/calendar/page.tsx` (create/update/cancel sessions, manage attendees).

**Training Date/Status Rules:**
- Admin training form uses **local time** inputs and converts them to UTC ISO for storage.
- If `expires_at` is missing but `renewal_months` is set, status is derived from the computed next-due date.

**Training Roadmap (Scope Anchors):**
- **Implemented now:** Worker training status, training courses + assignments, and training calendar sessions/blocks.
- **Later (feature-gated placeholders, OFF by default):** LMS-style training library, quizzes, and certificate templates
  (`training.library`, `training.quizzes`, `training.certs`) with placeholder admin routes:
  `/admin/training/library`, `/admin/training/quizzes`, `/admin/training/cert-templates`.

**Feature Key:** `module.training`

---

### 14. Notifications

**Purpose:** Notification center inbox, email digests, alert rules

**Key Pages:**
- `web/app/admin/notifications/page.tsx` - Admin notification inbox UI

**Backend Routers:**
- `backend/app/api/routes_admin.py` - `/v1/admin/notifications*` feed + read endpoints

**Key Services:**
- `backend/app/domain/notifications_center/service.py` - Inbox feed + read tracking
- `backend/app/domain/notifications/service.py` - Email notifications
- `backend/app/domain/notifications_digests/service.py` - Digest settings + payload generation

**Key Tables:**
- `notifications_events` - Inbox events
- `notifications_reads` - Per-user read state
- `notifications_rules_presets` - Preset rule configuration (enable/recipients/escalation delay)
- `notifications_digest_settings` - Digest schedules + recipients (daily/weekly/monthly)
- `notifications_digest_state` - Per-org last-sent period tracking to prevent repeat sends
- `email_events` - Email delivery tracking

**Permissions Required:**
- `core.view` - View notifications

**Feature Key:** `module.notifications_center`

**Where to change:**
- Feed filtering, cursor logic, and read tracking: `backend/app/domain/notifications_center/service.py`
- Preset rules configuration + emission: `backend/app/domain/notifications_center/service.py`
- Preset rules API (Owner-only): `backend/app/api/routes_admin.py`
- Digest settings API (Owner-only): `backend/app/api/routes_admin.py`
- Digest job runner: `backend/app/jobs/notifications_digests.py` + `backend/app/jobs/run.py`
- Digest send gating state: `backend/app/domain/notifications_digests/service.py`
- Preset keys: `no_show`, `payment_failed`, `negative_review`, `low_stock`, `high_value_lead`
- Trigger points:
  - `payment_failed` — Stripe webhook payment failure handling (`backend/app/api/routes_payments.py::_handle_invoice_event`)
  - `negative_review` — Admin-created feedback with rating <= 2 (`backend/app/api/routes_admin.py::admin_clients_add_feedback`)
  - `low_stock` — Inventory item updates emit `type=low_stock` when crossing from ok -> low; repeats only after recovery (low -> ok -> low). (`backend/app/domain/inventory/service.py::update_item`)
  - `high_value_lead`, `no_show` — placeholders until leads/check-in hooks exist
- API endpoints and RBAC: `backend/app/api/routes_admin.py`
- Event/read schema: `backend/app/domain/notifications_center/db_models.py` + Alembic migration
- Admin UI, CTA link mapping, and filters: `web/app/admin/notifications/page.tsx`

---

### 15. Settings

**Purpose:** Organization-wide settings, integrations, policies

**Key Pages:**
- `web/app/admin/settings/org/page.tsx` - General settings
- `web/app/admin/settings/booking-policies/page.tsx` - Cancellation/deposit policies
- `web/app/admin/settings/pricing/page.tsx` - Pricing config
- `web/app/admin/settings/modules/page.tsx` - Feature toggles
- `web/app/admin/settings/integrations/page.tsx` - Third-party integrations
- `web/app/admin/settings/availability-blocks/page.tsx` - Team availability

**Backend Routers:**
- `backend/app/api/routes_admin_settings.py` - `/v1/admin/settings/*`

**Key Services:**
- `backend/app/domain/org_settings/service.py` - Org settings CRUD
- `backend/app/domain/feature_modules/service.py` - Module visibility

**Key Tables:**
- `org_settings` - Key-value settings storage (migration 0085)
- `feature_modules` - Module visibility toggles (migration 0084)
- `booking_policies` - Cancellation/deposit rules

**Permissions Required:**
- `settings.manage` - Update settings
- `policies.manage` - Update policies
- `pricing.manage` - Update pricing

**Feature Key:** `module.settings`

---

### 16. Integrations

**Purpose:** Third-party integrations (Stripe, Twilio, SendGrid, etc.)

**Key Pages:**
- `web/app/admin/settings/integrations/page.tsx` - Integration config

**Backend Routers:**
- `backend/app/api/routes_admin_settings.py` - `/v1/admin/settings/integrations`
- `backend/app/api/routes_payments.py` - `/v1/payments/stripe/*` (webhooks)

**Key Services:**
- `backend/app/infra/stripe_client.py` - Stripe API client
- `backend/app/infra/communication.py` - Twilio adapter
- `backend/app/infra/email.py` - SendGrid/SMTP adapter

**Key Tables:**
- `integrations_google_accounts` - OAuth account storage (encrypted refresh tokens)
- `integrations_gcal_calendars` - Calendar connection + sync mode
- `integrations_gcal_sync_state` - Sync cursor + last sync metadata
- `schedule_external_blocks` - External calendar blocks
- `integrations_gcal_event_map` - Booking-to-event mapping for exports

**Permissions Required:**
- `settings.manage` - Configure integrations

**Feature Key:** `module.integrations`

---

## RBAC (Roles & Permissions)

**Purpose:** Role-based access control, permission management

**Key Pages:**
- `web/app/admin/iam/roles/page.tsx` - Role management

**Backend Routers:**
- `backend/app/api/routes_admin_iam.py` - `/v1/admin/iam/*`
- `backend/app/api/routes_iam.py` - `/v1/iam/*`

**Key Services:**
- `backend/app/domain/iam/permissions.py` - Permission catalog
- `backend/app/domain/iam/service.py` - Role CRUD

**Key Tables:**
- `roles` (migration 0085_iam_roles_permissions)
- `user_roles` (mapping table)

**Permissions Catalog (20 total):**

| Key | Description | Group |
|-----|-------------|-------|
| `core.view` | Read-only admin access | core |
| `bookings.view` | View bookings/schedule | bookings |
| `bookings.edit` | Update booking details | bookings |
| `bookings.assign` | Assign workers/teams | bookings |
| `bookings.status` | Update job status | bookings |
| `schedule.blocking.manage` | Manage availability blocks | schedule |
| `contacts.view` | View client details | contacts |
| `contacts.edit` | Update client details | contacts |
| `invoices.view` | View invoices | finance |
| `invoices.edit` | Create/update invoices | finance |
| `payments.record` | Record payments | finance |
| `finance.view` | Finance analytics | finance |
| `finance.manage` | Manage finance expenses and budgets | finance |
| `pricing.manage` | Pricing configuration | settings |
| `policies.manage` | Booking policies | settings |
| `settings.manage` | Org settings | settings |
| `users.manage` | User/role management | iam |
| `exports.run` | Data exports | ops |
| `reports.view` | Operational reports | analytics |
| `admin.manage` | High-risk admin endpoints | admin |

**Built-in Roles:**

| Role | Permissions | Use Case |
|------|-------------|----------|
| **owner** | All 20 permissions | Full system access |
| **admin** | All 20 permissions | Full system access |
| **dispatcher** | view, bookings.*, contacts.*, reports.view | Manage schedule/jobs |
| **accountant** | view, bookings.view, invoices.*, payments.*, finance.view, exports.run | Finance operations |
| **finance** | (same as accountant) | Finance operations |
| **viewer** | view, bookings.view, invoices.view, contacts.view, reports.view | Read-only |
| **worker** | bookings.view, bookings.status | Worker portal |

**Where to Change:**

#### Add New Permission
1. Add to `PERMISSION_CATALOG` in `backend/app/domain/iam/permissions.py`
2. Update role definitions if needed
3. Restart API (no migration required)

#### Add New Role
1. Add to `ROLE_DEFINITIONS` in `backend/app/domain/iam/permissions.py`
2. Or create via admin UI: `/v1/admin/iam/roles`

#### Permission Guards
- Decorator: `@require_permission_keys("invoices.edit")`
- Location: `backend/app/api/admin_auth.py`
- Example: `backend/app/api/routes_admin.py` (see invoice routes)

#### Legacy Permission Mapping
- `LEGACY_ADMIN_PERMISSION_MAP` in `permissions.py`
- Backward compatibility for old roles

---

## Supporting Modules

### Clients

**Tables:**
- `client_users` - Client accounts
- `client_addresses` - Address book (migration 0077)
- `client_feedback` - Reviews/ratings (migration 0078)
- `client_notes` - Service notes (migration 0073)

**Routes:**
- `/v1/admin/ui/clients` - Client CRUD
- `/v1/client/*` - Client portal

**Service:** `backend/app/domain/clients/service.py`

---

### Workers

**Tables:**
- `workers` - Worker records
- `worker_skills` (migration 0070)
- `worker_ratings` (migration 0070)
- `worker_reviews` (migration 0071)
- `worker_notes` (migration 0071)
- `worker_onboarding` (migration 0072)
- `worker_certificates` (migration 0072)

**Routes:**
- `/v1/admin/ui/workers` - Worker CRUD
- `/v1/worker/*` - Worker portal

**Service:** `backend/app/domain/workers/service.py`

---

### Chat

**Tables:**
- `chat_threads` (migration 0074)
- `chat_messages`
- `chat_participants`

**Routes:**
- `/v1/chat/*` - Chat API

**Service:** `backend/app/domain/chat_threads/service.py`

---

### Time Tracking

**Tables:**
- `time_entries` (migration 0013)

**Routes:**
- `/v1/time-tracking/*`

**Service:** `backend/app/domain/time_tracking/service.py`

---

### Bot (AI Assistant)

**Routes:**
- `/v1/bot/*` - AI bot conversation

**Service:** `backend/app/domain/bot/service.py`

---

## Quick Reference: Where to Find Code

| Task | Backend Location | Frontend Location |
|------|------------------|-------------------|
| Schedule week view | `routes_admin.py::/v1/admin/ui/schedule` | `web/app/admin/schedule/page.tsx` |
| Invoice detail | `routes_admin.py::/v1/admin/ui/invoices/{id}` | `web/app/admin/invoices/[id]/page.tsx` |
| Worker password reset | `routes_admin.py::/v1/admin/ui/workers/{id}` | `web/app/admin/workers/[id]/page.tsx` |
| Availability blocking | `routes_admin_settings.py::/v1/admin/settings/availability-blocks` | `web/app/admin/settings/availability-blocks/page.tsx` |
| RBAC roles | `routes_admin_iam.py::/v1/admin/iam/roles` | `web/app/admin/iam/roles/page.tsx` |
| Feature toggles | `routes_admin_settings.py::/v1/admin/settings/modules` | `web/app/admin/settings/modules/page.tsx` |
| Public lead form | `routes_public.py::/v1/public/leads` | `web/app/page.tsx` |

---

## Related Documentation

- [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) - High-level architecture
- [FILE_OVERVIEW.md](./FILE_OVERVIEW.md) - File structure map
- [CONTENT_GUIDE.md](./CONTENT_GUIDE.md) - Coding conventions
- [API_ENTRYPOINTS.md](./API_ENTRYPOINTS.md) - API reference
- [docs/FEATURE_MODULES.md](./docs/FEATURE_MODULES.md) - Feature module system
