# CleanWithSnapshot Project Overview

**Product Name:** CleanWithSnapshot / PaniDobro
**Type:** Multi-tenant SaaS application for cleaning service operations
**Tech Stack:** FastAPI backend + Next.js frontend + PostgreSQL + Redis

---

## What This Is

CleanWithSnapshot (marketed as "PaniDobro") is a comprehensive business management system for cleaning service companies. It handles:

- **Scheduling & Dispatch** - Team calendars, worker assignments, availability blocking
- **Invoicing & Payments** - Invoice creation, payment tracking, Stripe integration
- **Client Management** - Client records, addresses, notes, feedback
- **Worker Portal** - Job assignments, status updates, time tracking
- **Admin Panel** - Full operations dashboard with role-based access control
- **Lead Management** - Lead capture, status tracking, conversion
- **Multi-tenant Isolation** - Organization-level data separation with PostgreSQL RLS

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    USERS (Browser)                        │
└────────────┬─────────────────────────┬───────────────────┘
             │                         │
             │ HTTPS (443)             │ HTTPS (443)
             ▼                         ▼
┌────────────────────────┐  ┌────────────────────────────┐
│   Caddy Reverse Proxy   │  │   Caddy Reverse Proxy      │
│  (api.panidobro.com)    │  │   (panidobro.com)          │
└────────────┬────────────┘  └────────────┬───────────────┘
             │                             │
             │ :8000                       │ :3000
             ▼                             ▼
┌────────────────────────┐  ┌────────────────────────────┐
│   FastAPI Backend       │  │   Next.js 14 Frontend      │
│   Python 3.11           │  │   React 18, TypeScript     │
│   29 API routers        │  │   App Router (pages)       │
│   41 domain modules     │  │   Admin panel + public     │
└────────────┬────────────┘  └────────────────────────────┘
             │
             │ SQLAlchemy async
             ▼
┌────────────────────────┐  ┌────────────────────────────┐
│   PostgreSQL 16         │  │   Redis 7                  │
│   + Row-Level Security  │  │   Rate limiting, caching   │
│   + Alembic migrations  │  │                            │
└─────────────────────────┘  └────────────────────────────┘
```

### Key Components

| Component | Technology | Port | Purpose |
|-----------|-----------|------|---------|
| **API** | FastAPI (Python 3.11) | 8000 | REST API with 29 routers |
| **Web** | Next.js 14.2.5 | 3000 | Admin panel + public booking |
| **Database** | PostgreSQL 16 | 5432 | Primary data store with RLS |
| **Cache** | Redis 7 | 6379 | Rate limiting, sessions |
| **Proxy** | Caddy 2 | 80, 443 | Reverse proxy + auto-HTTPS |

---

## Environments

### Development

**Database URL:** `sqlite+aiosqlite:///:memory:` (for unit tests) or local PostgreSQL
**API URL:** `http://localhost:8000`
**Web URL:** `http://localhost:3000`
**CORS:** Permissive (`http://localhost:3000`)
**Email/SMS:** Disabled (noop adapters)

**Run locally:**

```bash
# Backend (from /backend directory)
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Web (from /web directory)
npm install
npm run dev
# Opens on http://localhost:3000
```

### Staging/Production

**Production URLs:**
- API: `https://api.panidobro.com`
- Web: `https://panidobro.com`

**Deployment:** Docker Compose with 5 services (see [OPERATIONS.md](./OPERATIONS.md))

**Key differences from dev:**
- Strict CORS enforcement
- Production secrets required (32+ char)
- Email/SMS enabled (SendGrid/Twilio)
- Stripe live mode
- PostgreSQL RLS enabled
- Rate limiting enforced

**Environment variables:** See [docs/ENV_AUDIT_REPORT.md](./docs/ENV_AUDIT_REPORT.md)

---

## How to Run Locally

### Prerequisites

- **Python 3.11+**
- **Node.js 22+**
- **PostgreSQL 16** (optional for dev; SQLite works for unit tests)
- **Redis** (optional for dev; rate limiting fails open without it)

The exact CI-matched versions are pinned in `.python-version` and `.nvmrc`. Load them locally with your version manager (e.g., `pyenv install --skip-existing $(cat .python-version)` and `nvm install`).

### Backend Setup

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Set minimal env vars (or use defaults)
export DATABASE_URL="postgresql+psycopg://user:pass@localhost/cleaning"
export APP_ENV="dev"

# Run migrations
alembic upgrade head

# Start API server
uvicorn app.main:app --reload --port 8000

# Verify health
curl http://localhost:8000/healthz
```

**Expected output:**
```json
{
  "status": "ready",
  "db_connected": true,
  "migrations_current": true
}
```

### Web Setup

```bash
cd web

# Install dependencies
npm install

# Set API URL
export NEXT_PUBLIC_API_BASE_URL="http://localhost:8000"

# Run dev server
npm run dev

# Opens on http://localhost:3000
```

### Admin Login

**Default credentials** (dev only):
- Username: `admin`
- Password: `admin123` (configurable via `ADMIN_BASIC_PASSWORD`)

**Production:** Set secure credentials via environment variables:
- `ADMIN_BASIC_USERNAME` / `ADMIN_BASIC_PASSWORD`
- `OWNER_BASIC_USERNAME` / `OWNER_BASIC_PASSWORD`

---

## Testing

### Backend Tests

```bash
cd backend

# Unit tests (SQLite, no Docker required)
pytest -v -m "not smoke and not postgres" --ignore=tests/smoke

# Smoke tests (requires Docker Compose stack)
pytest tests/smoke -v

# Specific test file
pytest tests/test_auth_security.py -v
```

**CI/CD:** See [.github/workflows/ci.yml](./.github/workflows/ci.yml)

### Frontend Type Check

```bash
cd web

# TypeScript validation
npx tsc --noEmit

# Build test
npm run build
```

---

## Key Features by Module

| Module | Purpose | Admin Route | Frontend Page |
|--------|---------|-------------|---------------|
| **Dashboard** | KPIs, recent activity | `/v1/admin/ui/dashboard` | `/admin` |
| **Schedule** | Team calendar, availability | `/v1/admin/ui/schedule` | `/admin/schedule` |
| **Invoices** | Invoice management | `/v1/admin/ui/invoices` | `/admin/invoices` |
| **Dispatcher** | Job assignments, routing | `/v1/dispatcher/*` | `/admin/dispatcher` |
| **Workers** | Worker management | `/v1/admin/ui/workers` | `/admin/workers` |
| **Clients** | Client records | `/v1/admin/ui/clients` | `/admin/clients` |
| **Settings** | Org configuration | `/v1/admin/settings/*` | `/admin/settings/*` |
| **IAM** | Roles & permissions | `/v1/admin/iam/*` | `/admin/iam/roles` |

See [MODULES.md](./MODULES.md) for detailed module documentation.

---

## Authentication Methods

### 1. Admin/Owner (HTTP Basic Auth)

**Login:** Browser basic auth prompt or `Authorization: Basic <base64>` header
**Roles:** owner, admin, dispatcher, accountant, finance, viewer
**Session:** Token-based with HMAC signing
**MFA:** Optional TOTP (if enabled)

### 2. Worker Portal (Phone + Password)

**Login:** Phone number + password (database-backed)
**Session:** Signed session cookie (`worker_session`)
**Fallback:** Environment variable auth (legacy)

### 3. SaaS User (Client Portal)

**Login:** Email/password (future)
**Session:** JWT-like HMAC tokens
**Multi-tenant:** Org-scoped isolation

### 4. Public API (No Auth)

**Endpoints:** Lead submission, public booking inquiry
**Protection:** Turnstile CAPTCHA (optional)

See [API_ENTRYPOINTS.md](./API_ENTRYPOINTS.md) for auth details.

---

## Database Migrations

**System:** Alembic (SQLAlchemy)
**Location:** `backend/alembic/versions/`
**Count:** 90+ migrations (as of 2026-01)
**Policy:** Forward-only (no downgrades)

**Common commands:**

```bash
cd backend

# Check current version
alembic current

# View pending migrations
alembic history

# Upgrade to latest
alembic upgrade head

# Create new migration
alembic revision -m "description"
```

**Health check validation:**
The `/healthz` endpoint validates migration status on every deploy.

See [DB_MIGRATIONS.md](./DB_MIGRATIONS.md) for detailed migration guide.

---

## Multi-Tenant Architecture

**Isolation:** Every core table has `org_id: UUID` column
**RLS:** PostgreSQL Row-Level Security policies enforce org boundaries (migration 0044)
**Default Org:** Configurable via `DEFAULT_ORG_ID` for single-tenant mode
**Worker Scope:** Workers are org-isolated (migration 0035)

**Exception:** `client_users` table missing `org_id` (legacy issue, backfilled in migration 0065)

---

## Configuration

### Critical Environment Variables

```bash
# Database
DATABASE_URL="postgresql+psycopg://user:pass@localhost/cleaning"

# Secrets (must be 32+ chars in prod)
AUTH_SECRET_KEY="<random-string>"
CLIENT_PORTAL_SECRET="<random-string>"
WORKER_PORTAL_SECRET="<random-string>"

# Admin credentials (at least one required in prod)
ADMIN_BASIC_USERNAME="admin"
ADMIN_BASIC_PASSWORD="<strong-password>"

# Optional: Email, SMS, Stripe
EMAIL_MODE="off"  # or "sendgrid", "smtp"
SMS_MODE="off"    # or "twilio"
STRIPE_SECRET_KEY="sk_test_..."

# Features
APP_ENV="dev"  # or "prod"
STRICT_CORS="false"  # "true" in prod
```

Full list: [docs/ENV_AUDIT_REPORT.md](./docs/ENV_AUDIT_REPORT.md)

---

## Deployment

### One-Button Deploy

```bash
cd /opt/cleaning  # or wherever repo is cloned
./ops/deploy.sh
```

**What it does:**
1. Fetches latest `main` branch
2. Builds Docker images
3. Starts stack (`docker compose up -d`)
4. Runs `alembic upgrade head`
5. Smoke tests API + web

**Rollback:**

```bash
git reset --hard <previous-sha>
./ops/deploy.sh
```

See [RUNBOOK.md](./RUNBOOK.md) and [docs/DEPLOY_RUNBOOK.md](./docs/DEPLOY_RUNBOOK.md)

---

## Health & Monitoring

### Health Endpoints

| Endpoint | Purpose | Auth Required |
|----------|---------|---------------|
| `/healthz` | Full health check (DB + migrations) | No |
| `/readyz` | Alias for `/healthz` | No |
| `/health` | Backup health check | No |
| `/metrics` | Prometheus metrics | Token (if enabled) |

**Example:**

```bash
curl https://api.panidobro.com/healthz
```

**Expected response:**

```json
{
  "status": "ready",
  "db_connected": true,
  "migrations_current": true,
  "current_revision": "0086",
  "expected_revision": "0086"
}
```

### Logs

- **Application logs:** JSON structured logs with context (org_id, user_id, role)
- **Admin audit logs:** Database table `admin_audit_logs`
- **Docker logs:** `docker compose logs -f api`

---

## Security Features

- **Row-Level Security:** PostgreSQL RLS enforces org isolation
- **CSRF Protection:** Token validation on state-changing requests
- **Rate Limiting:** 30 req/min global, 5 req/min for admin actions
- **Password Hashing:** Argon2id (or bcrypt fallback)
- **MFA:** TOTP for admin accounts (optional)
- **Audit Logging:** All admin actions logged to database
- **Idempotency:** Admin requests deduplicated via tokens
- **Security Headers:** XSS, CSRF, CSP headers enforced

---

## Next Steps

- **New contributors:** Read [CONTENT_GUIDE.md](./CONTENT_GUIDE.md) for coding conventions
- **Feature development:** See [MODULES.md](./MODULES.md) to find where to add code
- **Operations:** See [RUNBOOK.md](./RUNBOOK.md) for deployment and troubleshooting
- **Migrations:** See [DB_MIGRATIONS.md](./DB_MIGRATIONS.md) for schema changes
- **API routes:** See [API_ENTRYPOINTS.md](./API_ENTRYPOINTS.md) for endpoint reference

---

## Related Documentation

- [MODULES.md](./MODULES.md) - Feature modules and where code lives
- [FILE_OVERVIEW.md](./FILE_OVERVIEW.md) - Repository structure map
- [CONTENT_GUIDE.md](./CONTENT_GUIDE.md) - Coding conventions
- [OPERATIONS.md](./OPERATIONS.md) - Deployment and operations
- [DB_MIGRATIONS.md](./DB_MIGRATIONS.md) - Migration management
- [API_ENTRYPOINTS.md](./API_ENTRYPOINTS.md) - API reference
- [docs/ADMIN_GUIDE.md](./docs/ADMIN_GUIDE.md) - Admin features guide
- [RUNBOOK.md](./RUNBOOK.md) - Operations runbook
