# Contribution & Coding Guide

This guide covers coding conventions, patterns, and best practices for contributing to CleanWithSnapshot.

---

## Table of Contents

1. [Critical Constraints](#critical-constraints)
2. [Backend Patterns](#backend-patterns)
3. [Frontend Patterns](#frontend-patterns)
4. [API Conventions](#api-conventions)
5. [Database Patterns](#database-patterns)
6. [Testing Expectations](#testing-expectations)
7. [Security Guidelines](#security-guidelines)
8. [Common Tasks](#common-tasks)

---

## Critical Constraints

### ❌ DO NOT Modify Package Manifests

**STRICT POLICY:** Do not change `package.json` or `package-lock.json` anywhere in the repository without explicit approval.

**Rationale:**
- Frontend dependencies are locked for stability
- Dependency changes require security review
- Build reproducibility is critical for production

**If you need a new dependency:**
1. Propose it in a separate discussion/issue
2. Get approval from maintainers
3. Make dependency change in a separate PR

### 🔐 Never Hardcode Secrets

**Policy:** Admin credentials, API keys, and secret keys must be provided via environment variables or configuration
(`ADMIN_BASIC_USERNAME`, `ADMIN_BASIC_PASSWORD`, `VIEWER_BASIC_USERNAME`, `VIEWER_BASIC_PASSWORD`, etc.).

**Enforced by tests:** `tests/test_repo_security_scan.py::test_no_hardcoded_secrets` fails when runtime code contains
hardcoded passwords or secret keys.

---

## Backend Patterns

### Code Organization

**Follow domain-driven design:**

```
backend/app/domain/{module}/
├── db_models.py    # SQLAlchemy ORM models
├── schemas.py      # Pydantic request/response schemas
├── service.py      # Business logic layer
├── statuses.py     # Enum definitions (optional)
└── permissions.py  # Module permissions (optional)
```

**Example module structure:**

```python
# db_models.py
from sqlalchemy.orm import Mapped, mapped_column
from app.infra.db import Base

class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))  # REQUIRED
    status: Mapped[str] = mapped_column(String(50))
    # ...

# schemas.py
from pydantic import BaseModel

class BookingCreate(BaseModel):
    team_id: int
    starts_at: datetime
    # ...

class BookingResponse(BaseModel):
    id: uuid.UUID
    status: str
    # ...

# service.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

async def create_booking(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: BookingCreate,
) -> BookingResponse:
    # Business logic here
    pass
```

### Async/Await Everywhere

**All I/O operations must be async:**

```python
# ✅ Correct
async def get_booking(session: AsyncSession, booking_id: uuid.UUID) -> Booking:
    result = await session.execute(select(Booking).where(Booking.id == booking_id))
    return result.scalar_one()

# ❌ Wrong - blocking I/O
def get_booking(session: Session, booking_id: uuid.UUID) -> Booking:
    return session.query(Booking).filter(Booking.id == booking_id).first()
```

### Multi-Tenant Isolation

**CRITICAL:** Every query MUST filter by `org_id`:

```python
# ✅ Correct - org_id filtering
async def get_bookings_for_org(session: AsyncSession, org_id: uuid.UUID) -> list[Booking]:
    result = await session.execute(
        select(Booking).where(Booking.org_id == org_id)
    )
    return list(result.scalars())

# ❌ SECURITY ISSUE - missing org_id filter
async def get_all_bookings(session: AsyncSession) -> list[Booking]:
    result = await session.execute(select(Booking))  # LEAKS DATA ACROSS ORGS
    return list(result.scalars())
```

**Defense in depth:** PostgreSQL RLS policies provide backup, but never rely on them alone.

### Permission Guards

**Protect admin endpoints with permission decorators:**

```python
from app.api.admin_auth import require_permission_keys

@router.post("/v1/admin/ui/invoices/new")
@require_permission_keys("invoices.edit")
async def create_invoice(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    # Only users with invoices.edit permission can access
    admin_identity = request.state.admin_identity
    org_id = admin_identity.org_id
    # ...
```

**Available permissions:** See `backend/app/domain/iam/permissions.py::PERMISSION_CATALOG`

### Error Handling

**Use RFC 7807 Problem Details for errors:**

```python
from app.api.problem_details import problem_details, PROBLEM_TYPE_DOMAIN

# ✅ Correct
if not booking:
    return problem_details(
        request=request,
        status=404,
        title="Booking Not Found",
        detail=f"Booking {booking_id} does not exist or does not belong to your organization",
        type_=PROBLEM_TYPE_DOMAIN,
    )

# ❌ Wrong - HTTPException
raise HTTPException(status_code=404, detail="Not found")
```

**Error types:**
- `PROBLEM_TYPE_VALIDATION` - Request validation errors (422)
- `PROBLEM_TYPE_DOMAIN` - Business logic errors (400, 404)
- `PROBLEM_TYPE_RATE_LIMIT` - Rate limit exceeded (429)
- `PROBLEM_TYPE_SERVER` - Server errors (500)

**Custom domain errors:**

```python
from app.domain.errors import DomainError

raise DomainError(
    title="Invalid Booking Status",
    detail="Cannot cancel a booking that is already completed",
    errors=[{"field": "status", "message": "Invalid transition"}],
)
```

### Service Layer Pattern

**Keep routes thin, move logic to services:**

```python
# ✅ Good - route delegates to service
@router.post("/v1/admin/ui/bookings/create")
@require_permission_keys("bookings.edit")
async def create_booking_endpoint(
    request: Request,
    data: BookingCreate,
    session: AsyncSession = Depends(get_db_session),
):
    admin_identity = request.state.admin_identity
    booking = await booking_service.create_booking(
        session=session,
        org_id=admin_identity.org_id,
        data=data,
    )
    await session.commit()
    return booking

# ❌ Bad - business logic in route
@router.post("/v1/admin/ui/bookings/create")
async def create_booking_endpoint(...):
    booking = Booking(
        id=uuid.uuid4(),
        org_id=org_id,
        status="pending",
        # ... tons of logic here
    )
    session.add(booking)
    await session.commit()
```

### Request Context

**Access request context via `request.state`:**

```python
# Org context
org_id = request.state.current_org_id  # Set by middleware

# Admin identity
admin_identity = request.state.admin_identity
role = admin_identity.role
permissions = admin_identity.permissions
org_id = admin_identity.org_id

# Worker identity
worker_identity = request.state.worker_identity
username = worker_identity.username
org_id = worker_identity.org_id

# SaaS identity
saas_identity = request.state.saas_identity
user_id = saas_identity.user_id
org_id = saas_identity.org_id

# Request ID (for logging)
request_id = request.state.request_id
```

---

## Frontend Patterns

### App Router (Next.js 14)

**Use App Router conventions:**

```
web/app/admin/
├── page.tsx          # /admin (page component)
├── layout.tsx        # Admin layout wrapper
├── invoices/
│   ├── page.tsx      # /admin/invoices (list)
│   └── [id]/
│       └── page.tsx  # /admin/invoices/{id} (detail)
```

**AdminNav usage:** The `AdminNav` component accepts only `links` and optional `activeKey` props; do not pass a `title`.

### Client vs Server Components

**Default to Server Components, use Client Components when needed:**

```tsx
// ✅ Server Component (default)
export default async function InvoicesPage() {
  const invoices = await fetch(`${API_BASE_URL}/v1/admin/ui/invoices`)
  return <InvoiceList invoices={invoices} />
}

// ✅ Client Component (when interactive)
'use client'

import { useState } from 'react'

export default function InvoiceForm() {
  const [status, setStatus] = useState('draft')
  // ...
}
```

**Use Client Components for:**
- Interactive state (`useState`, `useReducer`)
- Browser APIs (`localStorage`, `window`, etc.)
- Event handlers
- `useSearchParams` (wrap in Suspense!)

### Suspense for useSearchParams

**IMPORTANT:** Wrap `useSearchParams()` in Suspense to avoid hydration errors:

```tsx
'use client'

import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'

function InvoiceFilterInner() {
  const searchParams = useSearchParams()
  const status = searchParams.get('status')
  // ...
}

export default function InvoiceFilter() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <InvoiceFilterInner />
    </Suspense>
  )
}
```

Any page using `useSearchParams` must render a client component inside a `Suspense` boundary when using the App Router.

### API Authentication

**Send admin credentials via localStorage + Authorization header:**

```typescript
// Get credentials from localStorage
const username = localStorage.getItem('admin_basic_username')
const password = localStorage.getItem('admin_basic_password')

// Encode as Basic Auth
const auth = btoa(`${username}:${password}`)

// Send with request
const response = await fetch(`${API_BASE_URL}/v1/admin/ui/invoices`, {
  headers: {
    'Authorization': `Basic ${auth}`,
  },
})
```

### Feature Visibility

**Check feature visibility before rendering:**

```typescript
import { isVisible } from '@/lib/featureVisibility'

const profile = { role: 'dispatcher', permissions: [...], org_id: '...' }
const config = { org_feature_enabled: { 'module.invoices': true } }
const userPrefs = { user_hidden: [] }

if (isVisible('module.invoices', { profile, config, userPrefs })) {
  // Render invoices module
}
```

**Precedence:** Org enabled → Role has permission → Not user-hidden

---

## API Conventions

### Naming

**URL path conventions:**

```
/v1/admin/ui/invoices           # List
/v1/admin/ui/invoices/new       # Create form (GET)
/v1/admin/ui/invoices/create    # Create action (POST)
/v1/admin/ui/invoices/{id}      # Detail (GET), Update (POST), Delete (DELETE)

/v1/public/leads                # Public endpoints
/v1/worker/jobs                 # Worker portal
/v1/client/bookings             # Client portal
```

**Method conventions:**
- `GET` - Read, no side effects
- `POST` - Create, update (with idempotency), state changes
- `DELETE` - Delete
- `PUT` - Full replacement (rarely used; prefer POST)

### Permission Key Naming

**Follow namespace pattern:**

```
{domain}.{action}

Examples:
- bookings.view
- bookings.edit
- bookings.assign
- invoices.view
- invoices.edit
- settings.manage
```

**Groups:**
- `core` - Core read access
- `bookings` - Booking operations
- `contacts` - Client/lead management
- `finance` - Invoice/payment operations
- `settings` - Organization settings
- `iam` - User/role management
- `ops` - Operational tasks (exports, etc.)
- `admin` - High-risk admin operations

### Feature Key Naming

**Follow namespace pattern:**

```
module.{name}                   # Top-level module
{module}.{feature}              # Sub-feature

Examples:
- module.schedule
- module.invoices
- schedule.optimization_ai      # AI suggestions in schedule
- invoices.bulk_actions         # Bulk operations
```

### Response Shapes

**Consistent response format:**

```python
# Success (200)
{
  "id": "uuid",
  "status": "completed",
  "created_at": "2026-01-15T10:00:00Z"
}

# Error (4xx/5xx) - RFC 7807 Problem Details
{
  "type": "https://api.panidobro.com/problems/domain-error",
  "title": "Booking Not Found",
  "status": 404,
  "detail": "Booking abc123 does not exist",
  "errors": [
    {"field": "booking_id", "message": "Not found"}
  ]
}
```

**Never return:**
- Plain text errors
- HTML error pages
- Inconsistent JSON shapes

---

## Database Patterns

### SQLAlchemy Models

**Use modern mapped columns (SQLAlchemy 2.0):**

```python
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, String, Index
import uuid
from datetime import datetime

class Booking(Base):
    __tablename__ = "bookings"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Multi-tenant isolation (REQUIRED)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)

    # Foreign keys
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("client_users.id"), nullable=True)

    # Data columns
    status: Mapped[str] = mapped_column(String(50))
    starts_at: Mapped[datetime]
    duration_minutes: Mapped[int]

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    team: Mapped["Team"] = relationship()

    # Indexes
    __table_args__ = (
        Index("ix_bookings_org_id", "org_id"),
        Index("ix_bookings_starts_at", "starts_at"),
        Index("ix_bookings_status", "status"),
    )
```

**Key patterns:**
- Use `Mapped[Type]` for type hints
- UUID primary keys for new tables
- `org_id` on every multi-tenant table
- Nullable FKs: `Mapped[Type | None]`
- Indexes on frequently queried columns

### Migrations

**Create migrations for schema changes:**

```bash
cd backend

# Auto-generate migration
alembic revision --autogenerate -m "add worker skills table"

# Review generated migration in alembic/versions/
# Edit if needed (Alembic doesn't catch everything)

# Test migration
alembic upgrade head

# Test downgrade (if supported)
alembic downgrade -1
```

**Migration best practices:**
- Review auto-generated migrations (don't trust blindly)
- Add indexes for foreign keys
- Test on a copy of prod data
- Forward-only in production (no downgrades)

See [DB_MIGRATIONS.md](./DB_MIGRATIONS.md) for details.

---

## Testing Expectations

### Backend Tests

**Write unit tests for new features:**

```python
# tests/test_bookings.py
import pytest
from app.domain.bookings.service import create_booking

@pytest.mark.asyncio
async def test_create_booking(db_session, org_id):
    booking = await create_booking(
        session=db_session,
        org_id=org_id,
        data=BookingCreate(team_id=1, starts_at=datetime(2026, 1, 15, 10, 0)),
    )
    assert booking.status == "pending"
    assert booking.org_id == org_id
```

**Test markers:**
- No marker = unit test (runs in CI with SQLite)
- `@pytest.mark.postgres` = PostgreSQL-specific test (skipped in CI)
- `@pytest.mark.smoke` = end-to-end smoke test (requires Docker)

**Run tests:**

```bash
cd backend

# Unit tests only (CI mode)
pytest -v -m "not smoke and not postgres" --ignore=tests/smoke

# Coverage (CI policy - report only)
pytest -v -m "not smoke and not postgres" --ignore=tests/smoke --cov=backend/app --cov-report=xml --cov-report=term

# All tests (local with PostgreSQL)
pytest -v

# Specific file
pytest tests/test_bookings.py -v

# Specific test
pytest tests/test_bookings.py::test_create_booking -v
```

### Frontend Tests

**TypeScript type checking:**

```bash
cd web

# Type check (required for CI)
npx tsc --noEmit

# Build test
npm run build
```

**No Jest/Vitest tests yet** - focus on type safety + build validation.

### Coverage Policy (Phase 0)

**Current rule:** CI collects pytest-cov XML + terminal reports for `backend/app` and uploads the artifact.

**Enforcement:** Report-only (no `--cov-fail-under` threshold yet). We will set a baseline threshold after the
first few CI runs establish a stable coverage percentage.

---

## Security Guidelines

### Authentication

**Never log passwords or tokens:**

```python
# ✅ Good
logger.info("user_login", extra={"username": username})

# ❌ BAD - logs password
logger.info("user_login", extra={"username": username, "password": password})
```

**Hash passwords with Argon2id:**

```python
from app.infra.auth import hash_password, verify_password

# Hash
password_hash = hash_password("user_password")

# Verify
is_valid = verify_password("user_password", password_hash)
```

### OWASP Top 10

**Prevent common vulnerabilities:**

| Vulnerability | Prevention |
|---------------|------------|
| **SQL Injection** | Use SQLAlchemy ORM (parameterized queries) |
| **XSS** | Next.js auto-escapes JSX, CSP headers enforced |
| **CSRF** | CSRF tokens on state-changing requests |
| **Auth broken** | Multi-factor auth (MFA), strong password hashing |
| **Insecure data** | PostgreSQL RLS, org_id filtering |
| **Logging sensitive data** | Never log passwords, tokens, PII |
| **SSRF** | Validate URLs before fetching |
| **Deserialization** | Use Pydantic schemas, not pickle |
| **Components** | Dependency scanning (Dependabot) |
| **Logging/Monitoring** | Structured logs, audit trails |

**Security headers (enforced by middleware):**

```python
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Content-Security-Policy: default-src 'self'; ...
```

### Bandit Suppressions

**Allowed suppressions:** `# nosec` (optionally with a rule ID like `# nosec B105`).

**Use only when:**
- The finding is a known false positive or acceptable risk.
- You can add a short, inline justification (e.g., `# nosec B105 - test fixture uses dummy secret`).
- The suppression is narrowly scoped to the exact line that triggers Bandit.

**Not allowed:**
- Blanket suppressions across files or modules.
- Suppressing findings without a justification comment.

### Audit Logging

**Log admin actions:**

```python
# Admin actions are automatically logged by AdminAuditMiddleware
# No manual logging needed for admin routes

# Manual audit logging (if needed)
from app.domain.admin_audit.service import log_admin_action

await log_admin_action(
    session=session,
    org_id=org_id,
    admin_role=admin_identity.role,
    action="booking.cancel",
    resource_type="booking",
    resource_id=booking_id,
    metadata={"reason": "client request"},
)
```

---

## Common Tasks

### Add a New API Route

1. **Choose router file** (or create new):
   - Admin UI: `routes_admin.py`
   - Settings: `routes_admin_settings.py`
   - Worker: `routes_worker.py`
   - Public: `routes_public.py`

2. **Add route with permission guard:**

```python
@router.post("/v1/admin/ui/bookings/bulk-cancel")
@require_permission_keys("bookings.edit")
async def bulk_cancel_bookings(
    request: Request,
    booking_ids: list[uuid.UUID],
    session: AsyncSession = Depends(get_db_session),
):
    admin_identity = request.state.admin_identity

    # Call service layer
    result = await booking_service.bulk_cancel(
        session=session,
        org_id=admin_identity.org_id,
        booking_ids=booking_ids,
    )

    await session.commit()
    return result
```

3. **Register router** (if new file):

```python
# backend/app/main.py
from app.api.routes_your_module import router as your_router

app.include_router(your_router)
```

### Add a New Permission

1. **Add to permission catalog:**

```python
# backend/app/domain/iam/permissions.py

PERMISSION_CATALOG: list[PermissionDefinition] = [
    # ... existing permissions
    PermissionDefinition(
        key="reports.export",
        label="Export reports",
        description="Export reports to CSV/PDF",
        group="analytics",
    ),
]
```

2. **Update roles** (if needed):

```python
ROLE_DEFINITIONS: dict[str, RoleDefinition] = {
    "accountant": RoleDefinition(
        key="accountant",
        name="Accountant",
        description="...",
        permissions={
            "core.view",
            # ... existing permissions
            "reports.export",  # Add new permission
        },
    ),
}
```

3. **Use in routes:**

```python
@router.post("/v1/admin/reports/export")
@require_permission_keys("reports.export")
async def export_report(...):
    # ...
```

### Add a New Feature Module

1. **Add module key:**

```python
# backend/app/domain/feature_modules/service.py

MODULE_KEYS = [
    "module.dashboard",
    # ... existing modules
    "module.reports",  # Add new module
]
```

2. **Frontend visibility check:**

```typescript
// web/app/admin/lib/featureVisibility.ts

// No code change needed - feature key is dynamic
```

3. **Settings UI:**

Module toggles automatically appear in `/admin/settings/modules` once key is added.

### Add a New Migration

See [DB_MIGRATIONS.md](./DB_MIGRATIONS.md) for detailed guide.

**Quick steps:**

```bash
cd backend

# 1. Edit domain models (e.g., add column to Booking)
# 2. Auto-generate migration
alembic revision --autogenerate -m "add booking priority field"

# 3. Review generated migration in alembic/versions/
# 4. Test
alembic upgrade head

# 5. Commit migration file
git add backend/alembic/versions/00XX_*.py
git commit -m "feat(db): add booking priority field"
```

### Add a New Frontend Page

1. **Create page component:**

```typescript
// web/app/admin/reports/page.tsx
export default function ReportsPage() {
  return (
    <div>
      <h1>Reports</h1>
      {/* ... */}
    </div>
  )
}
```

2. **Add navigation link:**

```typescript
// web/app/admin/layout.tsx (or nav component)
<a href="/admin/reports">Reports</a>
```

3. **Check feature visibility:**

```typescript
import { isVisible } from '@/lib/featureVisibility'

if (isVisible('module.reports', { profile, config, userPrefs })) {
  <a href="/admin/reports">Reports</a>
}
```

---

## Code Review Checklist

Before submitting a PR, ensure:

- [ ] **No package.json changes** (unless explicitly approved)
- [ ] **Multi-tenant isolation** - All queries filter by org_id
- [ ] **Permission guards** - Admin routes have `@require_permission_keys()`
- [ ] **Error handling** - Use `problem_details()` for errors
- [ ] **Async/await** - All I/O is async
- [ ] **Tests** - Unit tests for new features
- [ ] **Type checks** - `npx tsc --noEmit` passes
- [ ] **Build** - `npm run build` succeeds
- [ ] **Migrations** - Reviewed auto-generated migrations
- [ ] **Security** - No password logging, no SQL injection, no XSS
- [ ] **Audit logs** - Admin actions logged (if manual)
- [ ] **Documentation** - Updated if adding new modules/features

---

## Related Documentation

- [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) - High-level architecture
- [MODULES.md](./MODULES.md) - Feature modules map
- [FILE_OVERVIEW.md](./FILE_OVERVIEW.md) - Repository structure
- [DB_MIGRATIONS.md](./DB_MIGRATIONS.md) - Migration guide
- [API_ENTRYPOINTS.md](./API_ENTRYPOINTS.md) - API reference
- [OPERATIONS.md](./OPERATIONS.md) - Deployment guide
- [docs/ADMIN_GUIDE.md](./docs/ADMIN_GUIDE.md) - Admin features
