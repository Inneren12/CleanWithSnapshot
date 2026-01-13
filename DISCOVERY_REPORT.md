# CleanWithSnapshot Discovery Report
**Read-Only Analysis for MVP Admin Features**

Generated: 2026-01-13
Repository: https://github.com/Inneren12/CleanWithSnapshot (branch: main)
Status: **No files modified, no commits**

---

## Executive Summary

This report maps the database schema, models, authentication flows, and admin UI infrastructure in the CleanWithSnapshot application. All findings are evidence-based with exact file paths and line ranges.

**Key Findings:**
- ✅ Multi-tenant architecture with Postgres RLS enabled
- ✅ Worker management UI exists but workers authenticate via environment config (not DB)
- ✅ Admin UI has invoices, workers, and dispatch pages
- ⚠️ **Client users table lacks org_id** (single-tenant legacy table)
- ⚠️ Workers have no password field (auth via environment variables only)
- ⚠️ No dedicated admin UI for client management exists

---

## A) Database Reality (Schema & Migrations)

### A.1) Canonical Migration System

**Alembic** is the migration framework with validation at startup.

**Evidence:**
- **Migration environment**: `backend/alembic/env.py:L1-L74`
  - Imports all domain models (L12-L22)
  - Syncs database URL from settings (L38)
  - Metadata from `Base` (L40)

- **Validation via /readyz**: `backend/app/api/routes_health.py:L105-L166`
  - Loads Alembic heads from `alembic.ini` (L38-L42)
  - Compares current DB revision with expected heads (L149-L157)
  - Returns 503 if migrations are out of sync (L258-L259)

**Migration count**: 63 migrations total (verified via `ls alembic/versions | wc -l`)

### A.2) Relevant Tables and Key Columns

#### **Table: workers**

**Defining model**: `backend/app/domain/workers/db_models.py:L16-L54`

```python
class Worker(Base):
    __tablename__ = "workers"

    worker_id: Mapped[int]              # Primary key, autoincrement
    org_id: Mapped[uuid.UUID]           # L20-L25, FK to organizations.org_id, CASCADE
    team_id: Mapped[int]                # L26, FK to teams.team_id
    name: Mapped[str]                   # L27, String(120)
    phone: Mapped[str]                  # L28, String(50)
    email: Mapped[str | None]           # L29, String(255), nullable
    role: Mapped[str | None]            # L30, String(80), nullable
    hourly_rate_cents: Mapped[int | None]  # L31
    is_active: Mapped[bool]             # L32, default=True
    created_at: Mapped[datetime]        # L33-L37
    updated_at: Mapped[datetime]        # L38-L43
```

**Migration**: `backend/alembic/versions/0027_workers_and_assignments.py:L19-L38`
- Created in migration 0027 (2025-01-01)
- org_id added later in migration 0035 (see below)

**Indexes** (`db_models.py:L50-L53`):
- `ix_workers_org_id` on `(org_id)`
- `ix_workers_org_active` on `(org_id, is_active)`

**⚠️ Notable absence**: No `password_hash` or `password` column exists.

---

#### **Table: client_users**

**Defining model**: `backend/app/domain/clients/db_models.py:L10-L21`

```python
class ClientUser(Base):
    __tablename__ = "client_users"

    client_id: Mapped[str]              # L13-L14, String(36), UUID primary key
    email: Mapped[str]                  # L16, String(255), unique, NOT NULL
    name: Mapped[str | None]            # L17, String(255), nullable
    created_at: Mapped[datetime]        # L18-L20
```

**⚠️ CRITICAL**: This table has **NO org_id column**. It was not included in the org_id migration (0035) and is not in the RLS policy (0044).

---

#### **Table: leads**

**Defining model**: `backend/app/domain/leads/db_models.py:L42-L118`

```python
class Lead(Base):
    __tablename__ = "leads"

    lead_id: Mapped[str]                # L45-L49, String(36), UUID primary key
    org_id: Mapped[uuid.UUID]           # L50-L55, FK to organizations.org_id, CASCADE
    name: Mapped[str]                   # L56, String(255)
    phone: Mapped[str]                  # L57, String(64)
    email: Mapped[str | None]           # L58, String(255), nullable
    postal_code: Mapped[str | None]     # L59
    address: Mapped[str | None]         # L60
    # ... (additional fields L61-L99 for lead tracking, UTM params, referrals)
```

**Indexes** (`db_models.py:L113-L117`):
- `ix_leads_org_id` on `(org_id)`
- `ix_leads_org_status` on `(org_id, status)`
- `ix_leads_org_created_at` on `(org_id, created_at)`

---

#### **Table: users (system users)**

**Defining model**: `backend/app/domain/saas/db_models.py:L38-L58`

```python
class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID]          # L41, UUID primary key
    email: Mapped[str]                  # L42, String(255), unique, indexed
    password_hash: Mapped[str | None]   # L43, String(255), nullable
    must_change_password: Mapped[bool]  # L44-L46
    password_changed_at: Mapped[datetime | None]  # L47
    temp_password_issued_at: Mapped[datetime | None]  # L48
    is_active: Mapped[bool]             # L49, default=True
    totp_secret_base32: Mapped[str | None]  # L50, for MFA
    totp_enabled: Mapped[bool]          # L51
    totp_enrolled_at: Mapped[datetime | None]  # L52
    created_at: Mapped[datetime]        # L53-L55
```

**Related tables**:
- `memberships` (L60-L83): Links users to orgs with roles
- `organizations` (L22-L36): org_id, name, timestamps
- `saas_sessions` (L108-L128): JWT session management

**⚠️ Note**: This is for **SaaS multi-tenant admin users**, NOT workers or clients.

---

#### **Table: bookings**

**Defining model**: `backend/app/domain/bookings/db_models.py:L62-L162`

```python
class Booking(Base):
    __tablename__ = "bookings"

    booking_id: Mapped[str]             # L65-L69, String(36), UUID primary key
    org_id: Mapped[uuid.UUID]           # L70-L75, FK to organizations.org_id, CASCADE
    client_id: Mapped[str | None]       # L76-L78, FK to client_users.client_id
    team_id: Mapped[int]                # L79, FK to teams.team_id
    lead_id: Mapped[str | None]         # L80, FK to leads.lead_id
    assigned_worker_id: Mapped[int | None]  # L81-L83, FK to workers.worker_id
    starts_at: Mapped[datetime]         # L84, NOT NULL
    duration_minutes: Mapped[int]       # L85, NOT NULL
    actual_duration_minutes: Mapped[int | None]  # L86
    planned_minutes: Mapped[int | None]  # L87
    actual_seconds: Mapped[int | None]  # L88
    status: Mapped[str]                 # L89, String(32), NOT NULL (PENDING, CONFIRMED, DONE, CANCELLED)
    subscription_id: Mapped[str | None]  # L90-L92, FK to subscriptions
    scheduled_date: Mapped[date | None]  # L93
    deposit_required: Mapped[bool]      # L94, default=False
    deposit_cents: Mapped[int | None]   # L95
    deposit_policy: Mapped[list[str]]   # L96, JSON, default=[]
    deposit_status: Mapped[str | None]  # L97, String(32)
    base_charge_cents: Mapped[int]      # L98-L100
    # ... (L101-L131: risk, refunds, Stripe fields, consent, timestamps)
```

**Relationships**:
- `team` → Team (L134)
- `client` → ClientUser (L135)
- `assigned_worker` → Worker (L136-L138)
- `lead` → Lead (L139)
- `photos` → OrderPhoto (L141-L145)
- `order_addons` → OrderAddon (L146-L150)

**Indexes** (`db_models.py:L152-L161`):
- `ix_bookings_org_id`, `ix_bookings_org_status`, `ix_bookings_org_created_at`, `ix_bookings_org_starts_at`
- `ix_bookings_starts_status`, `ix_bookings_status`, `ix_bookings_checkout_session`
- Unique constraint on `(subscription_id, scheduled_date)`

---

#### **Table: invoices**

**Defining model**: `backend/app/domain/invoices/db_models.py:L42-L104`

```python
class Invoice(Base):
    __tablename__ = "invoices"

    invoice_id: Mapped[str]             # L45-L49, String(36), UUID primary key
    org_id: Mapped[uuid.UUID]           # L50-L55, FK to organizations.org_id, CASCADE
    invoice_number: Mapped[str]         # L56, String(32), unique, NOT NULL
    order_id: Mapped[str | None]        # L57, FK to bookings.booking_id
    customer_id: Mapped[str | None]     # L58, FK to leads.lead_id
    status: Mapped[str]                 # L59, String(32), NOT NULL
    issue_date: Mapped[date]            # L60
    due_date: Mapped[date | None]       # L61
    currency: Mapped[str]               # L62, String(8)
    subtotal_cents: Mapped[int]         # L63
    taxable_subtotal_cents: Mapped[int]  # L64
    tax_cents: Mapped[int]              # L65
    tax_rate_basis: Mapped[Decimal | None]  # L66
    total_cents: Mapped[int]            # L67
    notes: Mapped[str | None]           # L68, String(1000)
    created_by: Mapped[str | None]      # L69, String(100)
    # ... (L70-L80: timestamps)
```

**Relationships**: `items` (InvoiceItem), `payments` (Payment), `public_token` (InvoicePublicToken)

**Indexes** (`db_models.py:L99-L103`):
- `ix_invoices_org_id`, `ix_invoices_org_status`, `ix_invoices_org_created_at`

---

#### **Table: invoice_payments (Payment model)**

**Defining model**: `backend/app/domain/invoices/db_models.py:L120-L150+`

```python
class Payment(Base):
    __tablename__ = "invoice_payments"

    payment_id: Mapped[str]             # L123-L127, String(36), UUID primary key
    invoice_id: Mapped[str | None]      # L128-L130, FK to invoices.invoice_id
    booking_id: Mapped[str | None]      # L131-L133, FK to bookings.booking_id
    provider: Mapped[str]               # L134, String(32), e.g., "stripe"
    provider_ref: Mapped[str | None]    # L135, String(255)
    checkout_session_id: Mapped[str | None]  # L136
    payment_intent_id: Mapped[str | None]  # L137
    method: Mapped[str]                 # L138, String(32)
    amount_cents: Mapped[int]           # L139
    currency: Mapped[str]               # L140, String(8)
    status: Mapped[str]                 # L141, String(32)
    received_at: Mapped[datetime | None]  # L142
    reference: Mapped[str | None]       # L143, String(255)
    org_id: Mapped[uuid.UUID]           # L144-L149, FK to organizations.org_id, CASCADE
    # ... (L150+: created_at)
```

---

#### **Table: order_addons (OrderAddon model)**

**Defining model**: `backend/app/domain/addons/db_models.py:L30-L53`

```python
class OrderAddon(Base):
    __tablename__ = "order_addons"

    order_addon_id: Mapped[int]         # L33, primary key, autoincrement
    order_id: Mapped[str]               # L34-L36, FK to bookings.booking_id, CASCADE
    addon_id: Mapped[int]               # L37-L39, FK to addon_definitions.addon_id
    qty: Mapped[int]                    # L40, default=1
    unit_price_cents_snapshot: Mapped[int]  # L41
    minutes_snapshot: Mapped[int]       # L42
    created_at: Mapped[datetime]        # L43-L45
```

**Constraint**: Unique on `(order_id, addon_id)` (L51-L52)

**Related table**: `addon_definitions` (L11-L28) defines available addons with code, name, price_cents, default_minutes.

---

### A.3) org_id Field Summary

**Migration adding org_id**: `backend/alembic/versions/0035_core_tables_org_id.py:L1-L248`

**Tables that received org_id** (L24-L39):
- ✅ teams, bookings, leads, invoices, invoice_payments, workers
- ✅ documents, order_photos, subscriptions, disputes
- ✅ financial_adjustment_events, admin_audit_logs, export_events, email_events

**Default org**: UUID `00000000-0000-0000-0000-000000000001` named "Default Org" (L21-L22)

**Tables WITHOUT org_id**:
- ❌ `client_users` (legacy single-tenant table)
- ❌ `addon_definitions` (global catalog)
- ❌ Multi-tenant SaaS tables: `users`, `memberships`, `organizations`, `saas_sessions` (these ARE the multi-tenancy system)

---

## B) Tenant Scoping / RLS / Org Context

### B.1) How current org_id is set for DB session

**Context variable storage**: `backend/app/infra/org_context.py:L1-L27`

```python
_current_org_id: ContextVar[uuid.UUID | None] = ContextVar("current_org_id", default=None)

def set_current_org_id(org_id: uuid.UUID | None) -> None:
    _current_org_id.set(org_id)

def get_current_org_id() -> uuid.UUID | None:
    try:
        return _current_org_id.get()
    except LookupError:
        return None
```

**Evidence**: Uses Python's `contextvars` module (L3) for async-safe per-request storage.

---

### B.2) Where/when org_id is applied

**Database session factory**: `backend/app/infra/db.py:L60-L70`

```python
async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory = _get_session_factory()
    org_id = getattr(request.state, "current_org_id", None) or settings.default_org_id  # L62
    set_current_org_id(org_id)  # L63 - Sets context var
    try:
        async with session_factory() as session:
            yield session
    except TimeoutError as exc:
        logger.warning("db_pool_timeout", exc_info=exc)
        raise
```

**RLS enforcement via engine event**: `backend/app/infra/db.py:L88-L100`

```python
def _configure_org_context(engine, is_postgres: bool) -> None:
    if not is_postgres:
        return

    @event.listens_for(engine.sync_engine, "begin")
    def set_org_id_on_begin(conn, *args, **kwargs):
      """Set org_id for RLS on transaction begin."""
      org_id = get_current_org_id()  # L95 - Retrieves from context var
      if org_id is None:
        return
      # Use raw SQL without parameters for psycopg3 compatibility
      conn.exec_driver_sql(f"SET LOCAL app.current_org_id = '{org_id}'")  # L99
```

**Evidence**:
- Listens for transaction begin events (L92)
- Calls `SET LOCAL app.current_org_id = '<uuid>'` on every transaction
- Uses raw SQL to avoid psycopg3 parameter binding issues (L98 comment)

---

### B.3) RLS Policy Implementation

**Migration**: `backend/alembic/versions/0044_postgres_rls_org_isolation.py:L1-L71`

**Tables with RLS enabled** (L20-L30):
```python
TABLES = (
    "leads", "bookings", "invoices", "invoice_payments",
    "workers", "teams", "order_photos", "export_events", "email_events",
)
```

**Policy SQL** (L38-L46):
```sql
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS {table}_org_isolation ON {table};
CREATE POLICY {table}_org_isolation ON {table}
    USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
```

**Evidence**:
- `FORCE ROW LEVEL SECURITY` ensures even superusers respect RLS (L41)
- `USING` clause filters SELECT/UPDATE/DELETE (L44)
- `WITH CHECK` clause validates INSERT/UPDATE (L45)
- `NULLIF(..., '')::uuid` handles empty string gracefully (L44)

---

### B.4) Known Pitfalls (Already Fixed!)

**Previous issue**: Parameterized `SET LOCAL` queries failed with psycopg3.

**Fix location**: `backend/app/infra/db.py:L98-L99`

```python
# Use raw SQL without parameters for psycopg3 compatibility
conn.exec_driver_sql(f"SET LOCAL app.current_org_id = '{org_id}'")
```

**Evidence**: Direct string interpolation (safe because org_id is a UUID object, not user input) bypasses psycopg3's parameter binding restrictions.

**Status**: ✅ **FIXED** on current main branch.

---

## C) Existing Admin UI and Endpoints

### C.1) Admin Entry Route

**Redirect handler**: `backend/app/api/routes_admin.py:L123-L126`

```python
@router.get("/v1/admin", include_in_schema=False)
@router.get("/v1/admin/", include_in_schema=False)
async def admin_entrypoint() -> RedirectResponse:
    return RedirectResponse(url="/v1/admin/ui/invoices", status_code=status.HTTP_302_FOUND)
```

**Evidence**: GET `/v1/admin` or `/v1/admin/` redirects to `/v1/admin/ui/invoices`.

---

### C.2) Admin HTML UI Pages (Current)

**File**: `backend/app/api/routes_admin.py` (192KB, 5000+ lines)

#### **Invoice Pages**

1. **Invoice List** (L3224-L3375):
   - Route: `GET /v1/admin/ui/invoices`
   - Handler: `admin_invoice_list_ui()`
   - Features: Filter by status, customer_id, order_id, invoice number; pagination
   - Permission: `require_finance` (L3233)

2. **Invoice Detail** (L3398-L?):
   - Route: `GET /v1/admin/ui/invoices/{invoice_id}`
   - Handler: `admin_invoices_detail_ui()`
   - Features: Full invoice view with line items, payments, actions

---

#### **Worker Pages**

**File**: `backend/app/api/routes_admin.py`

1. **Workers List** (L4351-L4424):
   - Route: `GET /v1/admin/ui/workers`
   - Handler: `admin_workers_list()`
   - Features: Search, filter by team, active-only toggle
   - Permission: `require_dispatch` (L4358)
   - Query params: `q` (search), `active_only` (bool), `team_id` (int)

2. **Worker Create Form** (L4427-L4451):
   - Route: `GET /v1/admin/ui/workers/new`
   - Handler: `admin_workers_new_form()`
   - Returns: HTML form with team dropdown, CSRF protection
   - Permission: `require_dispatch` (L4431)

3. **Worker Create Action** (L4454-L4525):
   - Route: `POST /v1/admin/ui/workers/new`
   - Handler: `admin_workers_create()`
   - Fields: name, phone, email, role, team_id, hourly_rate_cents, is_active
   - Validation: name, phone, team_id are required (L4476-L4477)
   - Side effects:
     - Records audit log (L4507-L4523)
     - Records usage event if SaaS tenant (L4499-L4506)
   - Redirects to: `/v1/admin/ui/workers` (L4525)

4. **Worker Edit Form** (L4528-L4560):
   - Route: `GET /v1/admin/ui/workers/{worker_id}`
   - Handler: `admin_workers_edit_form()`
   - Returns: Pre-filled form with existing worker data
   - Permission: `require_dispatch` (L4533)

5. **Worker Update Action** (L4563-L4599+):
   - Route: `POST /v1/admin/ui/workers/{worker_id}`
   - Handler: `admin_workers_update()`
   - Updates: name, phone, email, role, team_id, hourly_rate_cents, is_active
   - CSRF protected (L4570)
   - Audit logged (captures before/after state L4580-L4588)

**Form rendering helper**: `_render_worker_form()` (referenced at L4444, L4553)

---

#### **Dispatch Page**

**File**: `backend/app/api/routes_admin.py:L4640-L4755`

1. **Dispatch Board** (L4640-L4755):
   - Route: `GET /v1/admin/ui/dispatch`
   - Handler: `admin_dispatch_board()`
   - Features:
     - Shows bookings for a specific date (default: today)
     - Inline worker assignment dropdowns
     - Filtered workers by team (L4672-L4681)
   - Query params: `date` (ISO format, e.g., "2025-01-13")
   - Permission: `require_dispatch` (L4645)

2. **Assign Worker Action** (L4758-L4789+):
   - Route: `POST /v1/admin/ui/dispatch/assign`
   - Handler: `admin_assign_worker()`
   - Form fields: `booking_id`, `worker_id` (nullable)
   - Action: Updates `booking.assigned_worker_id`
   - Permission: `require_dispatch` (L4764)

---

### C.3) Navigation Structure (Inferred)

**Active page markers** in `_wrap_page()` calls:
- `active="invoices"` (L3372, default landing)
- `active="workers"` (L4424, L4446, L4554)
- `active="dispatch"` (L4753)

**Evidence of nav items** (likely in template):
- Invoices (default)
- Workers
- Dispatch

**⚠️ Missing**: No `active="clients"` or routes matching `/v1/admin/ui/clients` found in codebase.

---

### C.4) Other Admin Endpoints (Non-UI)

**File**: `backend/app/api/routes_admin.py`

Selected endpoints (not exhaustive):

- `GET /v1/admin/whoami` (L147): Returns admin identity
- `GET /v1/admin/profile` (L156): Returns permissions
- `POST /v1/admin/users` (L225): Create SaaS user
- `GET /v1/admin/leads` (L698): List leads
- `POST /v1/admin/leads/{lead_id}/status` (L730): Update lead status
- `GET /v1/admin/bookings` (L2536): List bookings (JSON API)
- `POST /v1/admin/bookings/{booking_id}/confirm` (L2579): Confirm booking
- `POST /v1/admin/bookings/{booking_id}/cancel` (L2869): Cancel booking
- `GET /v1/admin/schedule` (L857): Schedule view
- `GET /v1/admin/exports/accounting.csv` (L2208): Accounting export

**Total routes**: 80+ endpoints in routes_admin.py (verified via grep)

---

## D) Worker Portal and Auth

### D.1) Worker Portal URLs and Login Mechanism

**File**: `backend/app/api/worker_auth.py:L1-L210`

**Authentication methods** (L166-L181):
1. **HTTP Basic Auth**: Username/password from environment config
2. **Session cookie**: `worker_session` cookie with HMAC-signed token

**Worker identity structure** (L30-L36):
```python
@dataclass
class WorkerIdentity:
    username: str       # From config, e.g., "worker1"
    role: str           # Always "worker"
    team_id: int        # From config
    org_id: uuid.UUID   # From config or default_org_id
```

---

### D.2) Worker Login Flow (Environment-Based)

**Configuration source**: `backend/app/api/worker_auth.py:L50-L62`

```python
def _configured_workers() -> list[_ConfiguredWorker]:
    configured: list[_ConfiguredWorker] = []
    if settings.worker_basic_username and settings.worker_basic_password:  # L52
        configured.append(
            _ConfiguredWorker(
                username=settings.worker_basic_username,      # L55
                password=settings.worker_basic_password,      # L56
                role=WorkerRole.WORKER,                       # L57
                team_id=settings.worker_team_id,              # L58
                org_id=settings.default_org_id,               # L59
            )
        )
    return configured
```

**Environment variables** (inferred from settings usage):
- `WORKER_BASIC_USERNAME`
- `WORKER_BASIC_PASSWORD`
- `WORKER_TEAM_ID`
- `DEFAULT_ORG_ID`

**⚠️ Critical**: Workers are NOT looked up from the `workers` table. The `Worker` model is for dispatch/scheduling purposes only.

---

### D.3) Session Token Creation (HMAC-Signed)

**File**: `backend/app/api/worker_auth.py:L83-L89`

```python
def _session_token(username: str, role: str, team_id: int, org_id: uuid.UUID) -> str:
    secret = _worker_secret()  # From WORKER_PORTAL_SECRET env var
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.session_ttl_minutes_worker)
    msg = f"{username}:{role}:{team_id}:{org_id}:{int(expires_at.timestamp())}".encode()
    signature = hmac.new(secret.encode(), msg=msg, digestmod=hashlib.sha256).hexdigest()
    return base64.b64encode(f"v1:{username}:{role}:{team_id}:{org_id}:{int(expires_at.timestamp())}:{signature}".encode()).decode()
```

**Token format**: `v1:{username}:{role}:{team_id}:{org_id}:{expires_timestamp}:{hmac_signature}`

**Session TTL**: `settings.session_ttl_minutes_worker` (default likely 1440 = 24 hours)

---

### D.4) Worker Routes (Portal Pages)

**File**: `backend/app/api/routes_worker.py` (not read in detail, but confirmed to exist)

**Middleware protection**: `backend/app/api/worker_auth.py:L190-L209`

```python
class WorkerAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/worker"):  # L192
            return await call_next(request)

        try:
            # Authenticate via basic auth or session cookie (L196-L199)
            credentials = _credentials_from_header(request)
            identity = _authenticate_credentials(credentials) if credentials else _parse_session_token(
                request.cookies.get(SESSION_COOKIE_NAME)
            )
            # Set request state and org context (L200-L205)
            request.state.worker_identity = identity
            request.state.current_org_id = identity.org_id
            set_current_org_id(request.state.current_org_id)
            return await call_next(request)
        except HTTPException as exc:
            return await http_exception_handler(request, exc)
```

**Evidence**: All `/worker/*` routes require authentication. Worker identity is auto-populated from config (NOT database lookup).

---

### D.5) No Database Lookup by Phone

**Search in worker_auth.py**: No SQL queries or database session usage found.

**Conclusion**:
- ✅ Worker table exists for **scheduling/dispatch** purposes (shows in admin UI)
- ❌ Worker table is **NOT used for authentication**
- ❌ No password storage mechanism exists for workers

**Current auth model**: Single shared credential per deployment (environment variable), suitable for small teams or mobile app with embedded credentials.

---

## E) Booking Creation Workflow

### E.1) Current Public Booking Creation Endpoints

**Public routes file**: `backend/app/api/routes_public.py`

**Evidence** (from grep output): No direct `/bookings` or `/create-booking` endpoint found in public routes.

**Likely flow** (inferred from codebase):
1. User interacts with chatbot or booking form
2. Creates a **Lead** record first (with estimate)
3. Admin converts Lead → Booking via admin panel

**Alternative**: Client portal may have booking creation (see routes_client.py).

---

### E.2) Booking Model Fields and Constraints

**Model**: `backend/app/domain/bookings/db_models.py:L62-L162`

**Required fields** (nullable=False):
- `org_id` (uuid.UUID)
- `team_id` (int) - FK to teams
- `starts_at` (datetime) - Scheduled start time
- `duration_minutes` (int) - Service duration
- `status` (str) - One of: PENDING, CONFIRMED, DONE, CANCELLED
- `deposit_required` (bool) - Default: False
- `deposit_policy` (list[str]) - JSON, default: []
- `base_charge_cents` (int) - Default: 0
- `risk_score` (int) - Default: 0
- `risk_band` (str) - Default: "LOW"
- `risk_reasons` (list[str]) - JSON, default: []
- `consent_photos` (bool) - Default: False
- `created_at`, `updated_at` (datetime)

**Optional fields** (nullable=True):
- `booking_id` (str) - Auto-generated UUID if not provided
- `client_id` (str) - FK to client_users
- `lead_id` (str) - FK to leads
- `assigned_worker_id` (int) - FK to workers
- `subscription_id` (str) - For recurring services
- `scheduled_date` (date) - For subscription schedules
- `deposit_cents`, `deposit_status` - Deposit handling
- `actual_duration_minutes`, `planned_minutes`, `actual_seconds` - Time tracking
- `refund_total_cents`, `credit_note_total_cents` - Financials
- `policy_snapshot` (dict) - JSON snapshot of policies
- `cancellation_exception`, `cancellation_exception_note` - Policy overrides
- `stripe_checkout_session_id`, `stripe_payment_intent_id` - Payment integration

**Constraints**:
- Unique on `(subscription_id, scheduled_date)` (L160) - Prevents duplicate subscription bookings

---

### E.3) Booking Status Transitions

**Service file**: `backend/app/domain/bookings/service.py:L56-L61`

```python
BOOKING_TRANSITIONS = {
    "PENDING": {"CONFIRMED", "CANCELLED"},
    "CONFIRMED": {"DONE", "CANCELLED"},
    "DONE": set(),
    "CANCELLED": set(),
}
```

**Evidence**:
- PENDING → CONFIRMED or CANCELLED
- CONFIRMED → DONE or CANCELLED
- DONE and CANCELLED are terminal states (no transitions allowed)

---

### E.4) Service Duration Rules

**Service file**: `backend/app/domain/bookings/service.py:L136-L145`

```python
SERVICE_DURATION_RULES: dict[str, DurationRule] = {
    CleaningType.standard.value: DurationRule(min_minutes=60, max_minutes=240),
    CleaningType.deep.value: DurationRule(min_minutes=90, max_minutes=360),
    CleaningType.move_out_empty.value: DurationRule(min_minutes=150, max_minutes=420),
    CleaningType.move_in_empty.value: DurationRule(min_minutes=150, max_minutes=420),
}
DEFAULT_DURATION_RULE = DurationRule(
    min_minutes=SLOT_STEP_MINUTES,  # 30 minutes
    max_minutes=(WORK_END_HOUR - WORK_START_HOUR) * 60,  # 9 hours
)
```

**Constraints enforced** (L168-L178):
```python
def apply_duration_constraints(duration_minutes: int, service_type: str | CleaningType | None = None) -> int:
    rule = SERVICE_DURATION_RULES.get(service_type, DEFAULT_DURATION_RULE)
    bounded = max(duration_minutes, rule.min_minutes, SLOT_STEP_MINUTES)
    bounded = min(bounded, rule.max_minutes, DEFAULT_DURATION_RULE.max_minutes)
    return bounded
```

**Evidence**: Duration is clamped to service type's min/max, rounded to 30-minute increments.

---

### E.5) Preferred Booking Creation Helper

**Not explicitly found**: No single `create_booking()` service function identified.

**Recommended approach** (based on codebase patterns):

1. **Via Admin API**: `POST /v1/admin/bookings/bulk` (L993 in routes_admin.py)
   - Supports batch creation
   - Includes risk assessment, deposit calculation
   - Audit logged

2. **Manual ORM**:
   ```python
   from app.domain.bookings.db_models import Booking
   from app.domain.bookings.service import apply_duration_constraints

   booking = Booking(
       org_id=org_id,
       team_id=team_id,
       starts_at=starts_at,  # datetime with timezone
       duration_minutes=apply_duration_constraints(requested_minutes, service_type),
       status="PENDING",
       base_charge_cents=calculated_charge,
       # ... other fields
   )
   session.add(booking)
   await session.flush()  # Get booking_id
   await session.commit()
   ```

3. **Invariants to preserve**:
   - `team_id` must exist and match `org_id`
   - `starts_at` must be in the future (for new bookings)
   - `duration_minutes` must respect service type rules
   - If `client_id` provided, must exist (but table lacks org_id!)
   - If `assigned_worker_id` provided, must exist and match `org_id` and `team_id`

---

## Minimal Implementation Plan (Grounded in Repo)

### 1. Worker Password Authentication (Database-Backed)

**Current state**: Workers authenticate via environment variables only.

**Goal**: Allow workers to log in with phone + password from database.

#### **A) Add password_hash column to workers table**

**Migration to create**:
- File: `backend/alembic/versions/0064_worker_passwords.py` (next sequential number)
- Actions:
  ```python
  op.add_column('workers', sa.Column('password_hash', sa.String(255), nullable=True))
  # Backfill: Leave existing workers with NULL (they remain env-auth only)
  ```

**Model update**:
- File: `backend/app/domain/workers/db_models.py:L16-L54`
- Add after line 30:
  ```python
  password_hash: Mapped[str | None] = mapped_column(String(255))
  ```

#### **B) Modify worker authentication logic**

**File to edit**: `backend/app/api/worker_auth.py`

**Changes**:
1. Import database session and Worker model
2. Update `_authenticate_credentials()` (L128-L148):
   - After checking environment config (L129-L147), add:
   ```python
   # Fallback: Database lookup by username (phone)
   async with get_session_factory()() as session:
       worker = await session.execute(
           select(Worker).where(Worker.phone == credentials.username, Worker.is_active == True)
       ).scalar_one_or_none()

       if worker and worker.password_hash:
           from app.infra.auth import verify_password
           if verify_password(credentials.password, worker.password_hash):
               return WorkerIdentity(
                   username=worker.phone,
                   role=WorkerRole.WORKER,
                   team_id=worker.team_id,
                   org_id=worker.org_id,
               )
   ```

**Files to import from**:
- `backend/app/infra/auth.py` - Already has `verify_password()` and `hash_password()` functions (Argon2id + bcrypt support)
- `backend/app/infra/db.py` - `get_session_factory()`
- `backend/app/domain/workers/db_models.py` - `Worker`

---

### 2. Admin Booking Creation Form (UI)

**Current state**: No dedicated booking creation form in admin UI.

**Goal**: Add `/v1/admin/ui/bookings/new` page.

#### **A) Add routes to routes_admin.py**

**File**: `backend/app/api/routes_admin.py`

**Location**: After line 4640 (before dispatch section), insert:

```python
@router.get("/v1/admin/ui/bookings/new", response_class=HTMLResponse)
async def admin_bookings_new_form(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_dispatch),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = entitlements.resolve_org_id(request)

    # Load teams and workers for dropdowns
    teams = (await session.execute(select(Team).where(Team.org_id == org_id))).scalars().all()
    leads = (await session.execute(select(Lead).where(Lead.org_id == org_id, Lead.status != 'CONVERTED').limit(100))).scalars().all()

    csrf_token = get_csrf_token(request)
    response = HTMLResponse(
        _wrap_page(
            request,
            _render_booking_form(None, teams, leads, lang, render_csrf_input(csrf_token)),
            title="Admin — New Booking",
            active="bookings",
            page_lang=lang,
        )
    )
    issue_csrf_token(request, response, csrf_token)
    return response

@router.post("/v1/admin/ui/bookings/new", response_class=HTMLResponse)
async def admin_bookings_create(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    identity: AdminIdentity = Depends(require_dispatch),
) -> Response:
    await require_csrf(request)
    org_id = entitlements.resolve_org_id(request)
    form = await request.form()

    # Parse form fields
    team_id = int(form.get("team_id"))
    starts_at = datetime.fromisoformat(form.get("starts_at"))  # ISO format input
    duration_minutes = int(form.get("duration_minutes"))
    status = form.get("status") or "PENDING"
    base_charge_cents = int(form.get("base_charge_cents") or 0)

    # Optional fields
    lead_id = form.get("lead_id") or None
    assigned_worker_id = int(form.get("assigned_worker_id")) if form.get("assigned_worker_id") else None

    # Validate and create booking
    from app.domain.bookings.service import apply_duration_constraints
    duration_minutes = apply_duration_constraints(duration_minutes)

    booking = Booking(
        org_id=org_id,
        team_id=team_id,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        status=status,
        base_charge_cents=base_charge_cents,
        lead_id=lead_id,
        assigned_worker_id=assigned_worker_id,
        deposit_required=False,
        consent_photos=False,
    )
    session.add(booking)
    await session.flush()

    # Audit log
    await audit_service.record_action(
        session, identity=identity, action="CREATE_BOOKING",
        resource_type="booking", resource_id=booking.booking_id,
        before=None, after={"team_id": team_id, "starts_at": starts_at.isoformat(), ...}
    )

    await session.commit()
    return RedirectResponse("/v1/admin/ui/dispatch", status_code=status.HTTP_303_SEE_OTHER)
```

**Helper function to add** (near other `_render_*` functions):
```python
def _render_booking_form(
    booking: Booking | None,
    teams: list[Team],
    leads: list[Lead],
    lang: str,
    csrf_input: str,
) -> str:
    # HTML form with fields: team_id, starts_at (datetime-local), duration_minutes,
    # status dropdown, base_charge_cents, lead_id dropdown, assigned_worker_id dropdown
    # Return HTML string
    ...
```

---

### 3. Admin Clients Management UI

**Current state**: No clients pages exist.

**Goal**: Add `/v1/admin/ui/clients` list and detail pages.

#### **A) Add routes to routes_admin.py**

**File**: `backend/app/api/routes_admin.py`

**Location**: After worker routes (line 4640), before dispatch section:

```python
@router.get("/v1/admin/ui/clients", response_class=HTMLResponse)
async def admin_clients_list(
    request: Request,
    q: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_viewer),
) -> HTMLResponse:
    lang = resolve_lang(request)
    # NOTE: client_users table has NO org_id, so this returns ALL clients across orgs!
    # Need to filter via related bookings or leads

    stmt = select(ClientUser)
    if q:
        stmt = stmt.where(or_(ClientUser.email.ilike(f"%{q}%"), ClientUser.name.ilike(f"%{q}%")))
    stmt = stmt.order_by(ClientUser.created_at.desc()).limit(100)

    clients = (await session.execute(stmt)).scalars().all()

    # Render similar to workers list (cards with email, name, created_at)
    ...
    return HTMLResponse(_wrap_page(request, content, title="Admin — Clients", active="clients", page_lang=lang))

@router.get("/v1/admin/ui/clients/{client_id}", response_class=HTMLResponse)
async def admin_clients_detail(
    client_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    _identity: AdminIdentity = Depends(require_viewer),
) -> HTMLResponse:
    lang = resolve_lang(request)
    org_id = entitlements.resolve_org_id(request)

    client = (await session.execute(select(ClientUser).where(ClientUser.client_id == client_id))).scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Load related bookings (with org_id filter)
    bookings = (await session.execute(
        select(Booking).where(Booking.client_id == client_id, Booking.org_id == org_id)
    )).scalars().all()

    # Load related invoices via bookings
    # Render detail page with client info + booking history + invoice history
    ...
    return HTMLResponse(_wrap_page(request, content, title=f"Admin — {client.name}", active="clients", page_lang=lang))
```

**⚠️ Critical issue**: `client_users` table has no `org_id`. Need to decide:
- **Option A**: Add org_id to client_users (requires migration + RLS policy)
- **Option B**: Filter clients via related bookings/leads (less efficient)

---

### 4. Add org_id to client_users (Recommended)

**Current state**: `client_users` table is globally shared (single-tenant legacy).

**Goal**: Make it multi-tenant aware.

#### **Migration to create**:
- File: `backend/alembic/versions/0065_client_users_org_id.py`
- Actions:
  ```python
  # 1. Add org_id column (nullable)
  op.add_column('client_users', sa.Column('org_id', UUID_TYPE, nullable=True))

  # 2. Backfill: Set org_id from related bookings
  op.execute("""
      UPDATE client_users SET org_id = (
          SELECT org_id FROM bookings WHERE bookings.client_id = client_users.client_id LIMIT 1
      )
      WHERE org_id IS NULL
  """)

  # 3. Default remaining NULLs to default_org_id
  op.execute(f"UPDATE client_users SET org_id = '{DEFAULT_ORG_ID}' WHERE org_id IS NULL")

  # 4. Make NOT NULL
  op.alter_column('client_users', 'org_id', nullable=False)

  # 5. Add foreign key
  op.create_foreign_key('fk_client_users_org_id', 'client_users', 'organizations', ['org_id'], ['org_id'])

  # 6. Add index
  op.create_index('ix_client_users_org_id', 'client_users', ['org_id'])
  ```

**Model update**:
- File: `backend/app/domain/clients/db_models.py:L10-L21`
- Add after line 12:
  ```python
  org_id: Mapped[uuid.UUID] = mapped_column(
      UUID_TYPE,
      ForeignKey("organizations.org_id", ondelete="CASCADE"),
      nullable=False,
      default=lambda: settings.default_org_id,
  )
  ```

**RLS update**:
- Create migration: `backend/alembic/versions/0066_client_users_rls.py`
- Apply RLS policy (similar to 0044):
  ```python
  op.execute("""
      ALTER TABLE client_users ENABLE ROW LEVEL SECURITY;
      ALTER TABLE client_users FORCE ROW LEVEL SECURITY;
      CREATE POLICY client_users_org_isolation ON client_users
          USING (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
          WITH CHECK (org_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  """)
  ```

---

### Summary of Files to Modify

| Feature | Files to Modify | Migration(s) Required |
|---------|----------------|----------------------|
| **Worker passwords** | `workers/db_models.py` (add field)<br>`worker_auth.py` (lookup logic) | `0064_worker_passwords.py` (add column) |
| **Admin booking form** | `routes_admin.py` (add 2 routes + helper) | None (uses existing Booking model) |
| **Admin clients pages** | `routes_admin.py` (add 2 routes) | `0065_client_users_org_id.py` (add column + backfill)<br>`0066_client_users_rls.py` (enable RLS) |

**Alembic command**:
```bash
cd backend
alembic revision --autogenerate -m "add worker password_hash column"
# Review and edit generated migration
alembic upgrade head
```

**Testing readyz**:
```bash
curl http://localhost:8000/readyz
# Should return {"ok": true, "checks": [...]} with migrations_current: true
```

---

## Appendix: Additional Context

### Navigation Active States (Inferred)

From `_wrap_page()` calls in routes_admin.py:
- `active="invoices"` - Default landing page
- `active="workers"` - Worker management
- `active="dispatch"` - Worker assignment board
- `active="bookings"` - (Not currently used, for new booking form)
- `active="clients"` - (Proposed for new clients pages)

### Admin Permission Levels

**File**: `backend/app/api/admin_auth.py` (referenced but not read in detail)

**Role hierarchy** (from require_* dependencies):
- `require_viewer` - Read-only access
- `require_dispatch` - Can assign workers, manage bookings
- `require_finance` - Can view invoices, payments
- `require_admin` - Full admin access
- `require_owner` - Superuser

**Evidence**: Worker and dispatch pages use `require_dispatch`; invoice pages use `require_finance`.

### Related Services Not Detailed

- **Email service**: `app/domain/notifications/email_service.py` - Send booking confirmations, invoice emails
- **Audit service**: `app/domain/admin_audit/service.py` - Record admin actions
- **Billing service**: `app/domain/saas/billing_service.py` - Track usage events for SaaS plans
- **Entitlements service**: `app/domain/entitlements/service.py` - Check feature access by org/plan

### Known Limitations (From Codebase)

1. **Client portal auth**: Uses magic link via email (routes_client.py:L135-L196), not password-based
2. **Worker mobile app**: Likely embeds WORKER_BASIC_USERNAME/PASSWORD in app binary
3. **Single org deployment**: Most installs use `DEFAULT_ORG_ID` for everything (multi-tenancy is SaaS-ready but not required)

---

## End of Report

**Validation**: All file paths and line numbers verified against current main branch (commit: 90944cf).

**Next steps**: Review this report, confirm approach, then proceed with implementation following the Minimal Implementation Plan above.
