# Repository File Overview

This document provides a tree-style map of the CleanWithSnapshot repository with descriptions of important files.

---

## Root Directory

```
CleanWithSnapshot/
├── backend/                    # FastAPI backend application
├── web/                        # Next.js frontend application
├── docs/                       # System documentation
├── design/                     # Design assets
├── scripts/                    # Utility scripts
├── ops/                        # Operations scripts
├── .github/                    # GitHub workflows and configuration
├── docker-compose.yml          # Production Docker Compose config
├── docker-compose.override.yml # Development overrides
├── Caddyfile                   # Reverse proxy configuration
├── RUNBOOK.md                  # Operations runbook
├── PROJECT_OVERVIEW.md         # High-level project guide (this doc set)
├── MODULES.md                  # Feature modules map (this doc set)
├── FILE_OVERVIEW.md            # This file
├── CONTENT_GUIDE.md            # Coding conventions (this doc set)
├── OPERATIONS.md               # Deployment guide (this doc set)
├── DB_MIGRATIONS.md            # Migration management (this doc set)
└── API_ENTRYPOINTS.md          # API reference (this doc set)
```

---

## Backend (`/backend`)

### Entrypoint & Core

| File | Purpose |
|------|---------|
| `app/main.py` | **Main entrypoint** - FastAPI app creation, middleware stack, router registration |
| `app/settings.py` | **Configuration** - Environment variable parsing, defaults, validation |
| `app/services.py` | **Service container** - Builds app services (email, storage, Stripe, etc.) |

### API Layer (`/backend/app/api`)

**Main route files (29 routers total):**

| File | Path Prefix | Purpose | Size |
|------|-------------|---------|------|
| `routes_admin.py` | `/v1/admin` | **Largest router** - Admin UI endpoints (dashboard, workers, invoices, clients, bookings) | 600KB+ |
| `routes_admin_settings.py` | `/v1/admin/settings` | Organization settings, policies, integrations | Medium |
| `routes_admin_iam.py` | `/v1/admin/iam` | Role & permission management | Small |
| `routes_admin_pricing.py` | `/v1/admin/pricing` | Pricing configuration | Small |
| `routes_admin_inventory.py` | `/v1/admin/inventory` | Inventory categories and items CRUD with RBAC | Small |
| `routes_dispatcher.py` | `/v1/dispatcher` | Dispatch board, route optimization, AI suggestions | 23KB |
| `routes_worker.py` | `/v1/worker` | Worker portal - job assignments, status updates | 82KB |
| `routes_client.py` | `/v1/client` | Client portal - bookings, invoices | 31KB |
| `routes_bookings.py` | `/v1/bookings` | Booking availability, slot search | 19KB |
| `routes_orders.py` | `/v1/orders` | Order/booking operations | 20KB |
| `routes_invoices.py` | N/A (in routes_admin.py) | Invoice CRUD, payment tracking | (merged) |
| `routes_payments.py` | `/v1/payments` | Stripe integration, webhook handlers | 48KB |
| `routes_leads.py` | `/v1/leads` | Lead management | Small |
| `routes_public.py` | `/v1/public` | Public lead submission, booking inquiry | Small |
| `routes_public_settings.py` | `/v1/public/settings` | Public configuration | Small |
| `routes_auth.py` | `/v1/auth` | SaaS user authentication flows | 12KB |
| `routes_iam.py` | `/v1/iam` | User/role management | 11KB |
| `routes_bot.py` | `/v1/bot` | AI bot conversation | 12KB |
| `routes_chat.py` | `/v1/chat` | Chat system | Small |
| `routes_checklists.py` | `/v1/checklists` | Job checklists | Small |
| `routes_time_tracking.py` | `/v1/time-tracking` | Time tracking | Small |
| `routes_billing.py` | `/v1/billing` | Billing management | Small |
| `routes_estimate.py` | `/v1/estimate` | Price estimates | Small |
| `routes_ui_lang.py` | `/v1/ui-lang` | Language preferences | Small |
| `routes_queues.py` | `/v1/admin/queue` | Dead letter queue management | Small |
| `routes_timeline.py` | `/v1/timeline` | Event timeline | Small |
| `break_glass.py` | `/v1/break-glass` | Emergency access | Small |
| `routes_health.py` | `/v1/health` | Health checks, migration validation | Small |
| `health_backup.py` | `/health` | Backup health endpoint | Small |
| `routes_metrics.py` | `/metrics` | Prometheus metrics | Small |

**Auth & middleware:**

| File | Purpose |
|------|---------|
| `admin_auth.py` | Admin authentication, permission guards, `@require_permission_keys()` |
| `worker_auth.py` | Worker authentication (phone + password or env vars) |
| `saas_auth.py` | SaaS user authentication, session middleware |
| `mfa.py` | Admin MFA enforcement (TOTP) |
| `admin_safety.py` | Admin action rate limiting (5 req/min) |
| `admin_audit.py` | Admin action audit logging middleware |
| `problem_details.py` | RFC 7807 error responses |

### Domain Layer (`/backend/app/domain`)

**41 domain modules** organized by business capability:

#### Core Business Domains

| Module | Files | Purpose |
|--------|-------|---------|
| `bookings/` | 5 files | **Booking/job management** - CRUD, scheduling, assignments, conflict detection |
| `invoices/` | 4 files | **Invoice management** - Creation, statuses, payment tracking |
| `workers/` | 2 files | **Worker management** - Employment data, teams |
| `clients/` | 2 files | **Client management** - Addresses, feedback, notes |
| `leads/` | 2 files | **Lead tracking** - Status management, referrals |

**Key files:**
- `bookings/service.py` - Booking CRUD, conflict detection, slot availability
- `bookings/db_models.py` - `Booking`, `BookingWorker` SQLAlchemy models
- `invoices/service.py` - Invoice CRUD, public token generation
- `invoices/statuses.py` - Invoice status enum (DRAFT, SENT, PAID, etc.)

#### Feature Domains

| Module | Files | Purpose |
|--------|-------|---------|
| `dispatcher/` | 4 files | **Dispatch board** - Route optimization, AI suggestions |
| `scheduling/availability/` | 2 files | **Availability blocking** - Team blackout periods |
| `feature_modules/` | 4 files | **Feature flags** - Org-level module toggles, UI preferences |
| `iam/` | 2 files | **Permissions** - Permission catalog, role definitions |
| `subscriptions/` | 2 files | **SaaS subscriptions** - Billing plans |
| `saas/` | 5 files | **Multi-tenant** - Org isolation, billing |
| `inventory/` | 3 files | **Inventory** - Categories, items (stock movements pending) |

**Key files:**
- `iam/permissions.py` - **Permission catalog** (19 permissions, 7 roles)
- `feature_modules/service.py` - Module visibility logic
- `dispatcher/ai_suggestions.py` - AI-powered assignment suggestions

#### Operational Domains

| Module | Files | Purpose |
|--------|-------|---------|
| `analytics/` | 2 files | Event logging, KPI aggregation |
| `notifications/` | 2 files | Email service (notifications) |
| `notifications_center/` | 3 files | Notification inbox events + reads |
| `time_tracking/` | 2 files | Worker time tracking |
| `checklists/` | 2 files | Job checklists |
| `nps/` | 2 files | Net Promoter Score collection |
| `disputes/` | 2 files | Dispute management |

#### Admin/Operations Domains

| Module | Files | Purpose |
|--------|-------|---------|
| `admin_audit/` | 2 files | Admin action audit logging |
| `admin_idempotency/` | 2 files | Admin request idempotency |
| `outbox/` | 2 files | Event outbox pattern for reliability |
| `break_glass/` | 2 files | Emergency access override |
| `data_rights/` | 2 files | GDPR data access/deletion |
| `export_events/` | 2 files | Data export to webhook/Google Sheets |

#### Supporting Domains

| Module | Files | Purpose |
|--------|-------|---------|
| `chat/` `chat_threads/` | 4 files | Customer support chat |
| `pricing/` `pricing_settings/` | 4 files | Service pricing management |
| `policy_overrides/` | 2 files | Per-booking policy exceptions |
| `reason_logs/` | 2 files | Event reason tracking |
| `message_templates/` | 1 file | Email/SMS templates |
| `documents/` | 1 file | Document management |
| `queues/` | 1 file | Background job queuing |
| `ops/` | 1 file | Operational helpers |
| `org_settings/` | 1 file | Organization settings storage |
| `config/` | 1 file | Configuration management |
| `bot/` | 1 file | AI bot logic |
| `integrations/` | 1 file | Third-party integrations |

**Common file structure per module:**
```
domain_module/
├── db_models.py    # SQLAlchemy ORM classes
├── schemas.py      # Pydantic request/response schemas
├── service.py      # Business logic layer
├── statuses.py     # Enum definitions (optional)
└── permissions.py  # Module-level permissions (optional)
```

### Infrastructure Layer (`/backend/app/infra`)

| File | Purpose |
|------|---------|
| `db.py` | **Database** - SQLAlchemy async session factory, connection pooling |
| `models.py` | **Central ORM registry** - All SQLAlchemy model imports (single source) |
| `auth.py` | Password hashing (Argon2id/bcrypt), verification |
| `security.py` | Rate limiting, client IP resolution |
| `email.py` | Email adapter resolution (SendGrid/SMTP/Noop) |
| `communication.py` | SMS/call adapter (Twilio/Noop) |
| `stripe_client.py` | Stripe API client wrapper |
| `stripe_resilience.py` | Circuit breaker for Stripe calls |
| `storage/` | File storage backends (local/R2/Cloudflare Images) |
| `metrics.py` | Prometheus metrics collection |
| `logging.py` | Structured logging setup (JSON logs with context) |
| `i18n.py` | Internationalization |
| `csrf.py` | CSRF token validation |
| `captcha.py` | Turnstile verification |
| `totp.py` | Two-factor authentication (TOTP) |
| `org_context.py` | Organization context management |
| `bot_store.py` | Bot conversation storage |

### Database Migrations (`/backend/alembic`)

| File/Folder | Purpose |
|-------------|---------|
| `alembic.ini` | Alembic configuration |
| `env.py` | Migration environment setup, imports all db_models |
| `versions/` | **90+ migration files** (0001 to 0086+) |

**Key migrations:**
- `0001_initial.py` - Initial schema
- `0035_core_tables_org_id.py` - Added org_id to core tables
- `0044_postgres_rls_org_isolation.py` - **PostgreSQL RLS policies**
- `0045_outbox_events.py` - Outbox pattern for reliability
- `0064_add_worker_password_hash.py` - Worker password authentication
- `0065_add_client_users_org_id.py` - Multi-tenant client isolation
- `0084_feature_modules_visibility.py` - Feature module toggles
- `0085_iam_roles_permissions.py` - RBAC roles & permissions
- `6a2b1c6f3c2b_availability_blocks.py` - Team availability blocking
- `a1b2c3d4e5f6_add_inventory_categories_and_items.py` - Inventory categories + items tables

### Tests (`/backend/tests`)

| File/Folder | Purpose |
|-------------|---------|
| `test_auth_security.py` | Authentication security tests |
| `test_booking_org_scope.py` | Multi-tenant isolation tests |
| `test_admin_config_and_portal.py` | Admin feature tests |
| `test_worker_portal.py` | Worker authentication tests |
| `test_stripe_webhook_events.py` | Payment webhook tests |
| `test_saas_auth.py` | SaaS user authentication tests |
| `test_migration_imports.py` | Migration validation tests |
| `smoke/` | **End-to-end smoke tests** (requires Docker) |
| `smoke/conftest.py` | Test fixtures |

**Test markers:**
- `@pytest.mark.smoke` - Smoke tests (requires Docker)
- `@pytest.mark.postgres` - PostgreSQL-specific tests
- No marker = unit test (runs with SQLite in CI)

### Other Backend Files

| File | Purpose |
|------|---------|
| `requirements.txt` | Python dependencies |
| `constraints.txt` | Dependency version constraints |
| `Dockerfile` | Backend Docker image build |

---

## Frontend (`/web`)

### App Structure (Next.js 14 App Router)

```
web/app/
├── page.tsx                    # Public homepage (lead capture + booking inquiry)
├── layout.tsx                  # Root layout
├── globals.css                 # Global styles
├── healthz/route.ts            # Health check endpoint
│
└── admin/                      # Admin panel (password protected)
    ├── page.tsx                # Admin dashboard
    ├── layout.tsx              # Admin layout
    ├── SchedulePageClient.tsx  # Schedule calendar component
    │
    ├── dispatcher/             # Dispatch board
    │   └── page.tsx
    │
    ├── notifications/          # Notification center inbox
    │   └── page.tsx
    │
    ├── schedule/               # Team scheduling
    │   └── page.tsx
    │
    ├── invoices/               # Invoice management
    │   ├── page.tsx            # Invoice list
    │   └── [id]/page.tsx       # Invoice detail
    │
    ├── training/               # Training admin
    │   └── courses/            # Training courses
    │       ├── page.tsx        # Course list
    │       └── [course_id]/page.tsx # Course detail + assignments
    │
    ├── iam/                    # IAM
    │   └── roles/              # Role management
    │       └── page.tsx
    │
    ├── settings/               # Organization settings
    │   ├── org/                # General settings
    │   │   └── page.tsx
    │   ├── booking-policies/   # Cancellation/deposit policies
    │   │   └── page.tsx
    │   ├── pricing/            # Pricing configuration
    │   │   └── page.tsx
    │   ├── modules/            # Feature toggles
    │   │   └── page.tsx
    │   ├── integrations/       # Third-party integrations
    │   │   └── page.tsx
    │   └── availability-blocks/ # Team availability
    │       └── page.tsx
    │
    ├── components/             # Reusable admin components
    │   └── ...
    │
    └── lib/                    # Admin utilities
        ├── featureVisibility.ts  # **Feature visibility logic**
        ├── orgSettings.ts        # Settings management
        └── ...
```

### Public Components (`/web/components`)

| File | Purpose |
|------|---------|
| `StepProgress.tsx` | Multi-step form progress indicator |
| `SummaryCard.tsx` | Booking summary display |
| `QuickChips.tsx` | Quick selection chips |
| `PrimaryCTA.tsx` | Primary call-to-action button |
| `ThankYou.tsx` | Form submission thank-you screen |
| `AlwaysVisibleHandoff.tsx` | Lead capture handoff component |

### Configuration

| File | Purpose |
|------|---------|
| `package.json` | **Dependencies** - Next.js 14.2.5, React 18.3.1, TypeScript 5.6.3 |
| `tsconfig.json` | TypeScript configuration |
| `next.config.js` | Next.js build configuration |
| `Dockerfile` | Frontend Docker image build |

---

## Documentation (`/docs`)

| File | Purpose | Size |
|------|---------|------|
| `ADMIN_GUIDE.md` | **Admin features guide** - Worker passwords, client mgmt, booking creation | 14KB |
| `ENV_AUDIT_REPORT.md` | **Environment variables** - Full env var documentation | 22KB |
| `GO_NO_GO.md` | Pre-deployment checklist | 15KB |
| `DEPLOY_RUNBOOK.md` | Deployment steps | 3KB |
| `DLQ_RUNBOOK.md` | Dead letter queue management | 3KB |
| `SMOKE.md` | Smoke testing guide | 13KB |
| `SERVER_PROD_CHECKLIST.md` | Server setup checklist | 13KB |
| `RELEASE_CHECKLIST.md` | Release process | 2KB |
| `CI_BRANCH_PROTECTION.md` | GitHub branch rules | 2KB |
| `OBSERVABILITY.md` | Logging, metrics, tracing | 1KB |
| `OPS_CHECKLIST.md` | Operations checklist | 1KB |
| `FEATURE_MODULES.md` | Feature flag documentation | 1KB |
| `ADMIN_ENTRYPOINTS.md` | Admin API endpoints | 1KB |

---

## Operations (`/ops`)

| File | Purpose |
|------|---------|
| `deploy.sh` | **One-button deploy** - Git pull, Docker build, migrations, smoke tests |
| `smoke.sh` | Smoke test runner (API + web health checks) |

---

## CI/CD (`.github/workflows`)

| File | Purpose |
|------|---------|
| `ci.yml` | **Main CI pipeline** - Backend tests, web build, typecheck, prod config validation |

**Jobs:**
1. `api` - Backend unit tests (Python 3.11, SQLite)
2. `web` - Frontend typecheck + build (Node 22)
3. `api-prod-config` - Production config validation
4. `infra` - Docker Compose validation

---

## Infrastructure

| File | Purpose |
|------|---------|
| `docker-compose.yml` | **Production stack** - PostgreSQL, Redis, API, Web, Caddy |
| `docker-compose.override.yml` | Development overrides |
| `Caddyfile` | **Reverse proxy** - HTTPS, domain routing |

**Services:**
- `db` - PostgreSQL 16
- `redis` - Redis 7
- `api` - FastAPI backend
- `web` - Next.js frontend
- `caddy` - Reverse proxy + auto-HTTPS

---

## Top 60 Important Files (Quick Reference)

### Backend (30 files)

| File | Why Important |
|------|---------------|
| `backend/app/main.py` | **App entrypoint** - Creates FastAPI app, registers routers |
| `backend/app/settings.py` | **Configuration** - Environment variables, defaults |
| `backend/app/api/routes_admin.py` | **Largest router** - Admin UI (600KB+) |
| `backend/app/api/admin_auth.py` | **Auth guards** - `@require_permission_keys()` |
| `backend/app/domain/iam/permissions.py` | **Permission catalog** - 19 permissions, 7 roles |
| `backend/app/domain/bookings/service.py` | **Booking logic** - CRUD, conflicts, slot availability |
| `backend/app/domain/invoices/service.py` | **Invoice logic** - CRUD, public tokens |
| `backend/app/domain/feature_modules/service.py` | **Feature flags** - Module visibility |
| `backend/app/domain/dispatcher/service.py` | **Dispatch** - Route optimization |
| `backend/app/domain/scheduling/availability/service.py` | **Availability blocking** |
| `backend/app/infra/db.py` | **Database** - Session factory |
| `backend/app/infra/models.py` | **ORM registry** - All model imports |
| `backend/alembic/env.py` | **Migrations** - Environment setup |
| `backend/alembic/versions/0044_*.py` | **RLS policies** - Multi-tenant isolation |
| `backend/alembic/versions/0085_*.py` | **RBAC** - Roles & permissions tables |
| `backend/alembic/versions/6a2b_*.py` | **Availability blocks** - Team blackout |

### Frontend (16 files)

| File | Why Important |
|------|---------------|
| `web/app/page.tsx` | **Public homepage** - Lead capture |
| `web/app/admin/page.tsx` | **Admin dashboard** |
| `web/app/admin/dashboard/ops/page.tsx` | **Ops dashboard** |
| `web/app/admin/schedule/page.tsx` | **Schedule view** |
| `web/app/admin/leads/page.tsx` | **Lead pipeline list** |
| `web/app/admin/invoices/page.tsx` | **Invoice list + overdue alerts** |
| `web/app/admin/invoices/[id]/page.tsx` | **Invoice detail** |
| `web/app/admin/inventory/page.tsx` | **Inventory items list** |
| `web/app/admin/inventory/suppliers/page.tsx` | **Inventory suppliers list** |
| `web/app/admin/training/courses/page.tsx` | **Training courses list** |
| `web/app/admin/training/courses/[course_id]/page.tsx` | **Training course detail** |
| `web/app/admin/iam/roles/page.tsx` | **Role management** |
| `web/app/admin/settings/modules/page.tsx` | **Feature toggles** |
| `web/app/admin/settings/availability-blocks/page.tsx` | **Availability blocking** |
| `web/app/admin/lib/featureVisibility.ts` | **Feature visibility** - Client-side checks |
| `web/package.json` | **Dependencies** |

### Infrastructure (10 files)

| File | Why Important |
|------|---------------|
| `docker-compose.yml` | **Production stack** |
| `Caddyfile` | **Reverse proxy** |
| `ops/deploy.sh` | **Deploy script** |
| `.github/workflows/ci.yml` | **CI pipeline** |
| `RUNBOOK.md` | **Operations guide** |

### Documentation (5 files)

| File | Why Important |
|------|---------------|
| `PROJECT_OVERVIEW.md` | **Project guide** (this doc set) |
| `MODULES.md` | **Feature modules** (this doc set) |
| `CONTENT_GUIDE.md` | **Coding conventions** (this doc set) |
| `docs/ADMIN_GUIDE.md` | **Admin features** |
| `docs/ENV_AUDIT_REPORT.md` | **Environment variables** |

---

## Where Code Lives: Quick Answers

### "Where is schedule week view implemented?"

**Backend:**
- Router: `backend/app/api/routes_admin.py::/v1/admin/ui/schedule`
- Service: `backend/app/domain/bookings/service.py::get_schedule()`
- Models: `backend/app/domain/bookings/db_models.py::Booking`

**Frontend:**
- Page: `web/app/admin/schedule/page.tsx`
- Component: `web/app/admin/SchedulePageClient.tsx`

### "Where are invoice bulk actions implemented?"

**Backend:**
- Router: `backend/app/api/routes_admin.py::/v1/admin/ui/invoices/bulk-*`
- Service: `backend/app/domain/invoices/service.py::bulk_update_status()`

**Frontend:**
- Page: `web/app/admin/invoices/page.tsx` (bulk action buttons)

### "How do I add a new admin route and guard it?"

1. Add route to `backend/app/api/routes_admin.py` or appropriate router
2. Add permission guard: `@require_permission_keys("your.permission")`
3. Register router in `backend/app/main.py::create_app()`
4. Add frontend page in `web/app/admin/your-feature/page.tsx`
5. Check feature visibility: `web/app/admin/lib/featureVisibility.ts`

### "How do I create/merge Alembic migrations?"

See [DB_MIGRATIONS.md](./DB_MIGRATIONS.md)

**Quick commands:**
```bash
cd backend

# Create new migration
alembic revision -m "description"

# Merge heads (if multiple branches)
alembic merge -m "merge heads" head1 head2

# Upgrade to latest
alembic upgrade head
```

### "Where is RBAC implemented?"

**Backend:**
- Permissions: `backend/app/domain/iam/permissions.py`
- Guards: `backend/app/api/admin_auth.py::@require_permission_keys()`
- Service: `backend/app/domain/iam/service.py`

**Frontend:**
- Roles UI: `web/app/admin/iam/roles/page.tsx`
- Visibility: `web/app/admin/lib/featureVisibility.ts`

### "Where is feature gating implemented?"

**Backend:**
- Service: `backend/app/domain/feature_modules/service.py`
- Models: `backend/app/domain/feature_modules/db_models.py`

**Frontend:**
- Settings: `web/app/admin/settings/modules/page.tsx`
- Checks: `web/app/admin/lib/featureVisibility.ts::isVisible()`

### "Where are notifications implemented?"

**Backend:**
- Service: `backend/app/domain/notifications/service.py` (email notifications)
- Routes: TBD (notification center pending)

**Frontend:**
- UI: TBD (partially implemented)

**Note:** Email notifications work; full notification center is partially implemented.

---

## Related Documentation

- [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) - High-level architecture
- [MODULES.md](./MODULES.md) - Feature modules map
- [CONTENT_GUIDE.md](./CONTENT_GUIDE.md) - Coding conventions
- [DB_MIGRATIONS.md](./DB_MIGRATIONS.md) - Migration management
- [API_ENTRYPOINTS.md](./API_ENTRYPOINTS.md) - API reference
- [OPERATIONS.md](./OPERATIONS.md) - Deployment guide
