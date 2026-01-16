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

**Key Services:**
- N/A (dashboard aggregates data from other modules)

**Ops dashboard bands:**
- Booking status band model: `backend/app/domain/ops/schemas.py::OpsDashboardBookingStatusBand`.
- Band definitions: `backend/app/domain/ops/service.py::BOOKING_STATUS_BANDS` (edit here to change ranges).

**Ops dashboard data sources:**
- `critical_alerts` draws from invoices and bookings in `backend/app/api/routes_admin.py::_build_ops_critical_alerts()`.
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
- `web/app/admin/teams/` (if exists)

**Backend Routers:**
- `backend/app/api/routes_admin.py` - `/v1/admin/ui/teams/*`

**Key Services:**
- `backend/app/domain/workers/service.py` - Worker/team CRUD

**Key Tables:**
- `teams` - Team records
- `workers` - Worker records (FK to team)
- `team_working_hours` - Regular schedules
- `team_blackout` - Unavailability periods

**Permissions Required:**
- `core.view` - View teams
- `users.manage` - Manage workers/teams

**Feature Key:** `module.teams`

**Where to Change:**

#### Worker Management
- API: `backend/app/api/routes_admin.py::/v1/admin/ui/workers`
- Service: `backend/app/domain/workers/service.py`
- Guide: [docs/ADMIN_GUIDE.md](./docs/ADMIN_GUIDE.md#worker-password-management)

---

### 6. Quality

**Purpose:** Quality checks, inspections, checklists

**Key Pages:**
- TBD (not fully implemented)

**Backend Routers:**
- `backend/app/api/routes_checklists.py` - `/v1/checklists/*`

**Key Services:**
- `backend/app/domain/checklists/service.py` - Checklist CRUD

**Key Tables:**
- `checklists` - Checklist templates
- `checklist_items` - Individual check items

**Permissions Required:**
- `bookings.view` - View checklists
- `bookings.edit` - Update checklists

**Feature Key:** `module.quality`

---

### 7. Analytics

**Purpose:** Reports, KPIs, operational dashboards

**Key Pages:**
- `web/app/admin/analytics/` (if exists)

**Backend Routers:**
- `backend/app/api/routes_admin.py` - Analytics endpoints

**Key Services:**
- `backend/app/domain/analytics/service.py` - Event aggregation, KPI calculation

**Key Tables:**
- `events` - Analytics events
- `bookings` - Job data
- `invoices` - Financial data

**Permissions Required:**
- `reports.view` - View reports
- `finance.view` - Finance analytics

**Feature Key:** `module.analytics`

---

### 8. Finance

**Purpose:** Financial reporting, payment reconciliation

**Key Pages:**
- `web/app/admin/finance/` (if exists)

**Backend Routers:**
- `backend/app/api/routes_admin.py` - Finance endpoints
- `backend/app/api/routes_payments.py` - Payment processing

**Key Services:**
- `backend/app/domain/invoices/service.py` - Invoice/payment logic

**Key Tables:**
- `invoices` - Invoice records
- `payments` - Payment records
- `stripe_events` - Stripe webhooks

**Permissions Required:**
- `finance.view` - View finance reports
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

**Purpose:** Marketing campaigns, promotional codes

**Key Pages:**
- TBD (not fully implemented)

**Backend Routers:**
- TBD

**Key Tables:**
- TBD

**Permissions Required:**
- TBD

**Feature Key:** `module.marketing`

---

### 11. Leads

**Purpose:** Lead capture, qualification, conversion tracking

**Key Pages:**
- `web/app/page.tsx` - Public lead capture form
- `web/app/admin/leads/` - Lead management (if exists)

**Backend Routers:**
- `backend/app/api/routes_leads.py` - `/v1/leads/*`
- `backend/app/api/routes_public.py` - `/v1/public/leads` (public submission)

**Key Services:**
- `backend/app/domain/leads/service.py` - Lead CRUD, status management

**Key Tables:**
- `leads` - Lead records
- `lead_statuses` - Status definitions

**Permissions Required:**
- `contacts.view` - View leads
- `contacts.edit` - Update leads

**Feature Key:** `module.leads`

---

### 12. Inventory

**Purpose:** Cleaning supplies inventory management

**Key Pages:**
- TBD (not fully implemented)

**Feature Key:** `module.inventory`

---

### 13. Training

**Purpose:** Worker training, certifications, onboarding

**Key Pages:**
- TBD (partially implemented)

**Key Tables:**
- `worker_onboarding` (migration 0072)
- `worker_certificates` (migration 0072)

**Feature Key:** `module.training`

---

### 14. Notifications

**Purpose:** Notification center, email digests, alert rules

**Key Pages:**
- `web/app/admin/notifications/` (if exists)

**Backend Routers:**
- `backend/app/api/routes_admin.py` - Notification endpoints (if exists)

**Key Services:**
- `backend/app/domain/notifications/service.py` - Email notifications

**Key Tables:**
- `email_events` - Email delivery tracking
- `notification_rules` (if exists)

**Permissions Required:**
- `core.view` - View notifications

**Feature Key:** `module.notifications_center`

**Note:** Partially implemented (email notifications exist, full notification center pending)

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

**Permissions Catalog (19 total):**

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
| **owner** | All 19 permissions | Full system access |
| **admin** | All 19 permissions | Full system access |
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
