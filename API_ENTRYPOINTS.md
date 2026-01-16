# API Entrypoints Reference

Complete reference for CleanWithSnapshot API endpoints, authentication, and usage patterns.

---

## Table of Contents

1. [API Overview](#api-overview)
2. [Authentication Methods](#authentication-methods)
3. [Admin API](#admin-api)
4. [Worker Portal API](#worker-portal-api)
5. [Client Portal API](#client-portal-api)
6. [Public API](#public-api)
7. [Health & Metrics](#health--metrics)
8. [Error Responses](#error-responses)

---

## API Overview

**Base URL (Production):** `https://api.panidobro.com`
**Base URL (Development):** `http://localhost:8000`

**API Version:** v1
**Response Format:** JSON
**Error Format:** RFC 7807 Problem Details

### Router Registration (29 routers)

| Priority | Router | Path Prefix | Auth | File |
|----------|--------|-------------|------|------|
| 1 | health | `/v1/health` | None | `routes_health.py` |
| 2 | public | `/v1/public` | None/Captcha | `routes_public.py` |
| 3 | public_settings | `/v1/public/settings` | None | `routes_public_settings.py` |
| 4 | auth | `/v1/auth` | Session | `routes_auth.py` |
| 5 | iam | `/v1/iam` | Admin | `routes_iam.py` |
| 6 | bot | `/v1/bot` | Public | `routes_bot.py` |
| 7 | estimate | `/v1/estimate` | Public | `routes_estimate.py` |
| 8 | chat | `/v1/chat` | Mixed | `routes_chat.py` |
| 9 | client | `/v1/client` | Client Session | `routes_client.py` |
| 10 | payments | `/v1/payments` | Mixed | `routes_payments.py` |
| 11 | billing | `/v1/billing` | Admin | `routes_billing.py` |
| 12 | orders | `/v1/orders` | Admin | `routes_orders.py` |
| 13 | checklists | `/v1/checklists` | Worker/Admin | `routes_checklists.py` |
| 14 | time_tracking | `/v1/time-tracking` | Worker/Admin | `routes_time_tracking.py` |
| 15 | ui_lang | `/v1/ui-lang` | Session | `routes_ui_lang.py` |
| 16 | worker | `/v1/worker` | Worker Auth | `routes_worker.py` |
| 17 | bookings | `/v1/bookings` | Public/Admin | `routes_bookings.py` |
| 18 | dispatcher | `/v1/dispatcher` | Admin | `routes_dispatcher.py` |
| 19 | leads | `/v1/leads` | Admin | `routes_leads.py` |
| 20 | break_glass | `/v1/break-glass` | Emergency | `break_glass.py` |
| 21 | **admin** | `/v1/admin` | **Admin** | **`routes_admin.py` (largest)** |
| 22 | admin_settings | `/v1/admin/settings` | Admin | `routes_admin_settings.py` |
| 23 | admin_iam | `/v1/admin/iam` | Admin | `routes_admin_iam.py` |
| 24 | admin_pricing | `/v1/admin/pricing` | Admin | `routes_admin_pricing.py` |
| 25 | queues | `/v1/admin/queue` | Admin | `routes_queues.py` |
| 26 | timeline | `/v1/timeline` | Admin | `routes_timeline.py` |
| 27 | health_backup | `/health` | None | `health_backup.py` |
| 28 | metrics | `/metrics` | Token | `routes_metrics.py` |
| 29 | style_guide | `/style-guide` | Dev Only | `routes_style_guide.py` |

**Entrypoint:** `backend/app/main.py::create_app()` → `app = create_app(settings)`

---

## Authentication Methods

### 1. Admin/Owner (HTTP Basic Auth)

**Used by:** Admin panel (`/v1/admin/*`)

**Authentication:**

```bash
# HTTP Basic Auth header
Authorization: Basic <base64(username:password)>

# Example
curl -u "admin:password123" https://api.panidobro.com/v1/admin/ui/dashboard
```

**Credentials (Environment Variables):**

| Role | Username Env | Password Env |
|------|--------------|--------------|
| Owner | `OWNER_BASIC_USERNAME` | `OWNER_BASIC_PASSWORD` |
| Admin | `ADMIN_BASIC_USERNAME` | `ADMIN_BASIC_PASSWORD` |
| Dispatcher | `DISPATCHER_BASIC_USERNAME` | `DISPATCHER_BASIC_PASSWORD` |
| Accountant | `ACCOUNTANT_BASIC_USERNAME` | `ACCOUNTANT_BASIC_PASSWORD` |
| Viewer | `VIEWER_BASIC_USERNAME` | `VIEWER_BASIC_PASSWORD` |

**Session:** Token-based session with HMAC signing (after initial auth)

**MFA:** Optional TOTP (if enabled via `MFA_ENABLED`)

**Implementation:** `backend/app/api/admin_auth.py`

---

### 2. Worker Portal (Phone + Password)

**Used by:** Worker portal (`/v1/worker/*`)

**Authentication:**

```bash
# HTTP Basic Auth with phone number as username
curl -u "+1234567890:workerpassword" https://api.panidobro.com/v1/worker/jobs
```

**Login Flow:**

1. Worker provides phone number + password
2. System validates against `workers.password_hash` (Argon2id)
3. Session cookie `worker_session` created (HMAC-signed)
4. Subsequent requests use session cookie

**Session Duration:** Configurable (default: 12 hours)

**Fallback:** Environment variable auth (legacy)
- `WORKER_BASIC_USERNAME` / `WORKER_BASIC_PASSWORD`

**Implementation:** `backend/app/api/worker_auth.py`

---

### 3. SaaS User (Client Portal)

**Used by:** Client portal (`/v1/client/*`)

**Authentication:**

1. Login: `POST /v1/auth/login` with email + password
2. Returns session token (JWT-like HMAC)
3. Use token in subsequent requests

**Session:** HMAC-signed tokens, configurable TTL

**Implementation:** `backend/app/api/saas_auth.py`

---

### 4. Public API (No Auth)

**Used by:** Public endpoints (`/v1/public/*`)

**Authentication:** None

**Protection:** Optional Turnstile CAPTCHA for lead submission

**Endpoints:**
- `POST /v1/public/leads` - Submit lead
- `GET /v1/public/settings` - Public configuration

---

## Admin API

**Base Path:** `/v1/admin`
**Auth:** Admin HTTP Basic Auth + Role Permissions
**File:** `backend/app/api/routes_admin.py` (600KB+, largest router)

### Dashboard

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/ui/dashboard` | `core.view` | Dashboard KPIs |
| GET | `/v1/admin/dashboard/ops` | `core.view` + `module.dashboard` | Ops dashboard aggregates (org TZ windows) |

#### Ops Dashboard Response (critical alerts)

`GET /v1/admin/dashboard/ops` includes `critical_alerts` for the Critical Alerts widget.

```json
{
  "as_of": "2026-01-20T15:04:05Z",
  "org_timezone": "America/Denver",
  "critical_alerts": [
    {
      "type": "overdue_invoices",
      "severity": "critical",
      "title": "Overdue invoices (7+ days)",
      "description": "2 invoices are overdue by 7+ days totaling CAD 1,200.00.",
      "entity_ref": {
        "kind": "invoice",
        "count": 2,
        "total_cents": 120000,
        "currency": "CAD",
        "min_days_overdue": 7
      },
      "actions": [
        {
          "label": "Open overdue invoices",
          "href": "/admin/invoices?overdue_bucket=attention",
          "method": "GET"
        }
      ],
      "created_at": "2026-01-20T15:04:05Z"
    }
  ],
  "upcoming_events": [
    {
      "starts_at": "2026-01-21T08:00:00Z",
      "title": "Unassigned booking starting soon",
      "entity_ref": {
        "kind": "booking",
        "booking_id": "booking-123",
        "team_id": 4,
        "status": "PENDING"
      },
      "actions": [
        {
          "label": "Open schedule",
          "href": "/admin/schedule?date=2026-01-21",
          "method": "GET"
        }
      ]
    }
  ],
  "worker_availability": [],
  "booking_status_today": {
    "totals": {
      "total": 0,
      "pending": 0,
      "confirmed": 0,
      "done": 0,
      "cancelled": 0
    },
    "bands": []
  }
}
```

### Teams

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/teams` | `core.view` | List teams with lead, headcount, monthly bookings/revenue, ratings |
| GET | `/v1/admin/teams/{id}` | `core.view` | Team detail summary |
| PATCH | `/v1/admin/teams/{id}` | `users.manage` | Update team settings (lead, zones, specializations, calendar color) |
| GET | `/v1/admin/teams/{id}/members` | `core.view` | Team members roster |
| GET | `/v1/admin/teams/{id}/recent_bookings` | `core.view` | Recent bookings for the team (`limit` query) |
| GET | `/v1/admin/teams/{id}/metrics` | `core.view` | Performance metrics (`from`/`to` datetime query params) |
| GET | `/v1/admin/teams/compare` | `core.view` | Team comparison table (`from`/`to` datetime query params) |
| POST | `/v1/admin/teams` | `users.manage` | Create a new team |

**List response shape (example):**
```json
[
  {
    "team_id": 3,
    "name": "Crew North",
    "created_at": "2026-02-01T08:00:00Z",
    "lead": { "worker_id": 12, "name": "Maria R.", "role": "Lead", "rating_avg": 4.7 },
    "worker_count": 5,
    "monthly_bookings": 18,
    "monthly_revenue_cents": 462000,
    "rating_avg": 4.6,
    "rating_count": 36
  }
]
```

**Comparison response shape (example):**
```json
{
  "range_start": "2026-02-01T00:00:00Z",
  "range_end": "2026-03-01T23:59:59Z",
  "teams": [
    {
      "team_id": 3,
      "name": "Crew North",
      "bookings_count": 18,
      "completed_count": 16,
      "cancelled_count": 1,
      "completion_rate": 0.8889,
      "total_revenue_cents": 462000,
      "average_booking_cents": 25667,
      "rating_avg": 4.6,
      "rating_count": 36
    }
  ]
}
```

---

### Bookings/Schedule

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/schedule` | `bookings.view` | Schedule view |
| GET | `/v1/admin/schedule/team_calendar` | `bookings.view` | Team calendar aggregates (org TZ boundaries) |
| GET | `/v1/admin/schedule/worker_timeline` | `bookings.view` | Worker timeline aggregates (org TZ boundaries) |
| GET | `/v1/admin/ui/bookings` | `bookings.view` | List bookings |
| GET | `/v1/admin/ui/bookings/{id}` | `bookings.view` | Booking detail |
| POST | `/v1/admin/ui/bookings/create` | `bookings.edit` | Create booking |
| POST | `/v1/admin/ui/bookings/{id}` | `bookings.edit` | Update booking |
| POST | `/v1/admin/ui/bookings/{id}/assign` | `bookings.assign` | Assign worker |
| POST | `/v1/admin/ui/bookings/{id}/status` | `bookings.status` | Update status |
| DELETE | `/v1/admin/ui/bookings/{id}` | `bookings.edit` | Delete booking |

**Example:**

```bash
# Create booking
curl -X POST https://api.panidobro.com/v1/admin/ui/bookings/create \
  -u "admin:password" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "team_id=1" \
  -d "starts_at=2026-01-20T10:00" \
  -d "duration_minutes=120"
```

**Schedule list query params (`GET /v1/admin/schedule`):**

| Param | Type | Description |
|-------|------|-------------|
| `from` | `YYYY-MM-DD` | Start date (org timezone) |
| `to` | `YYYY-MM-DD` | End date (org timezone) |
| `team_id` | `int` | Filter by team |
| `worker_id` | `int` | Filter by worker |
| `status` | `string` | Filter by status |
| `q` | `string` | Search booking id, client, or address |
| `limit` | `int` | Page size for list view (max 500) |
| `offset` | `int` | Offset for list view paging |

**List response fields:** `total`, `limit`, `offset`, `query` (in addition to `from_date`, `to_date`, `bookings`).

**Schedule booking fields:** Each `booking` includes `worker_name`, `team_name`, `client_label`, `address`, `service_label`, `price_cents`, and optional `notes` (client/address notes when present).

**Team calendar query params (`GET /v1/admin/schedule/team_calendar`):**

| Param | Type | Description |
|-------|------|-------------|
| `from` | `YYYY-MM-DD` | Start date (org timezone) |
| `to` | `YYYY-MM-DD` | End date (org timezone) |
| `team_id` | `int` | (Optional) Filter by team |
| `status` | `string` | (Optional) Filter by booking status |

**Team calendar response shape:**

```json
{
  "from_date": "2026-01-20",
  "to_date": "2026-01-26",
  "org_timezone": "America/Denver",
  "days": ["2026-01-20", "2026-01-21"],
  "teams": [
    {
      "team_id": 1,
      "name": "Alpha Team",
      "days": [
        {
          "date": "2026-01-20",
          "bookings": 3,
          "revenue": 42000,
          "workers_used": 2
        }
      ]
    }
  ]
}
```

---

### Invoices

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/invoices/overdue_summary` | `invoices.view` | Overdue invoice bucket summary |
| POST | `/v1/admin/invoices/overdue_remind` | `invoices.send` | Send overdue reminders (bucket or invoice IDs) |
| GET | `/v1/admin/ui/invoices` | `invoices.view` | List invoices |
| GET | `/v1/admin/ui/invoices/{id}` | `invoices.view` | Invoice detail |
| POST | `/v1/admin/ui/invoices/new` | `invoices.edit` | Create invoice |
| POST | `/v1/admin/ui/invoices/{id}` | `invoices.edit` | Update invoice |
| POST | `/v1/admin/ui/invoices/{id}/send` | `invoices.edit` | Send invoice to client |
| POST | `/v1/admin/ui/invoices/{id}/mark-paid` | `payments.record` | Mark as paid |
| POST | `/v1/admin/ui/invoices/bulk-status` | `invoices.edit` | Bulk status update |
| DELETE | `/v1/admin/ui/invoices/{id}` | `invoices.edit` | Delete invoice |

**Example:**

```bash
# Get invoice detail
curl https://api.panidobro.com/v1/admin/ui/invoices/abc-123 \
  -u "admin:password"
```

---

### Workers

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/ui/workers` | `core.view` | List workers |
| GET | `/v1/admin/ui/workers/{id}` | `core.view` | Worker detail |
| POST | `/v1/admin/ui/workers/new` | `users.manage` | Create worker |
| POST | `/v1/admin/ui/workers/{id}` | `users.manage` | Update worker (incl. password) |
| DELETE | `/v1/admin/ui/workers/{id}` | `users.manage` | Delete worker |

**Example:**

```bash
# Create worker with password
curl -X POST https://api.panidobro.com/v1/admin/ui/workers/new \
  -u "admin:password" \
  -d "name=John Doe" \
  -d "phone=+1234567890" \
  -d "password=SecurePass123" \
  -d "team_id=1" \
  -d "is_active=on"
```

See [docs/ADMIN_GUIDE.md](./docs/ADMIN_GUIDE.md#worker-password-management)

---

### Clients

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/ui/clients` | `contacts.view` | List clients |
| GET | `/v1/admin/ui/clients/{id}` | `contacts.view` | Client detail |
| POST | `/v1/admin/ui/clients/new` | `contacts.edit` | Create client |
| POST | `/v1/admin/ui/clients/{id}` | `contacts.edit` | Update client |
| DELETE | `/v1/admin/ui/clients/{id}` | `contacts.edit` | Delete client |

---

### Settings

**Path:** `/v1/admin/settings/*`
**File:** `backend/app/api/routes_admin_settings.py`

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/settings/org` | `settings.manage` | Org settings |
| POST | `/v1/admin/settings/org` | `settings.manage` | Update settings |
| GET | `/v1/admin/settings/modules` | `settings.manage` | Feature module toggles |
| POST | `/v1/admin/settings/modules` | `settings.manage` | Update module visibility |
| GET | `/v1/admin/settings/availability-blocks` | `schedule.blocking.manage` | List availability blocks |
| POST | `/v1/admin/settings/availability-blocks` | `schedule.blocking.manage` | Create block |
| DELETE | `/v1/admin/settings/availability-blocks/{id}` | `schedule.blocking.manage` | Delete block |
| GET | `/v1/admin/settings/booking-policies` | `policies.manage` | Booking policies |
| POST | `/v1/admin/settings/booking-policies` | `policies.manage` | Update policies |
| GET | `/v1/admin/settings/pricing` | `pricing.manage` | Pricing config |
| POST | `/v1/admin/settings/pricing` | `pricing.manage` | Update pricing |
| GET | `/v1/admin/settings/integrations` | `settings.manage` | Integration config |
| POST | `/v1/admin/settings/integrations` | `settings.manage` | Update integrations |

---

### IAM (Roles & Permissions)

**Path:** `/v1/admin/iam/*`
**File:** `backend/app/api/routes_admin_iam.py`

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/iam/roles` | `users.manage` | List roles |
| GET | `/v1/admin/iam/roles/{id}` | `users.manage` | Role detail |
| POST | `/v1/admin/iam/roles` | `users.manage` | Create role |
| PUT | `/v1/admin/iam/roles/{id}` | `users.manage` | Update role |
| DELETE | `/v1/admin/iam/roles/{id}` | `users.manage` | Delete role |
| GET | `/v1/admin/iam/permissions` | `users.manage` | List permissions |

---

### Pricing

**Path:** `/v1/admin/pricing/*`
**File:** `backend/app/api/routes_admin_pricing.py`

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/pricing/config` | `pricing.manage` | Get pricing config |
| POST | `/v1/admin/pricing/reload` | `pricing.manage` | Reload pricing from file |

---

### Dead Letter Queue

**Path:** `/v1/admin/queue/*`
**File:** `backend/app/api/routes_queues.py`

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/queue/dlq` | `admin.manage` | List failed jobs |
| POST | `/v1/admin/queue/dlq/{id}/retry` | `admin.manage` | Retry failed job |
| DELETE | `/v1/admin/queue/dlq/{id}` | `admin.manage` | Delete failed job |

---

## Worker Portal API

**Base Path:** `/v1/worker`
**Auth:** Worker phone + password (or env vars)
**File:** `backend/app/api/routes_worker.py`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/worker` | Worker dashboard |
| GET | `/v1/worker/jobs` | List assigned jobs |
| GET | `/v1/worker/jobs/{id}` | Job detail |
| POST | `/v1/worker/jobs/{id}/status` | Update job status |
| POST | `/v1/worker/jobs/{id}/check-in` | Check in to job |
| POST | `/v1/worker/jobs/{id}/check-out` | Check out from job |
| GET | `/v1/worker/schedule` | Worker schedule |

**Example:**

```bash
# Get assigned jobs
curl https://api.panidobro.com/v1/worker/jobs \
  -u "+1234567890:workerpass"
```

---

## Client Portal API

**Base Path:** `/v1/client`
**Auth:** SaaS user session
**File:** `backend/app/api/routes_client.py`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/client/bookings` | List client bookings |
| GET | `/v1/client/bookings/{id}` | Booking detail |
| POST | `/v1/client/bookings/{id}/cancel` | Cancel booking |
| GET | `/v1/client/invoices` | List invoices |
| GET | `/v1/client/invoices/{id}` | Invoice detail |
| POST | `/v1/client/invoices/{id}/pay` | Pay invoice |

---

## Public API

**Base Path:** `/v1/public`
**Auth:** None (optional CAPTCHA)
**File:** `backend/app/api/routes_public.py`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/public/leads` | Submit lead |
| GET | `/v1/public/settings` | Public configuration |
| GET | `/v1/public/invoices/{token}` | View invoice (public link) |

**Example:**

```bash
# Submit lead
curl -X POST https://api.panidobro.com/v1/public/leads \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+1987654321",
    "message": "Interested in cleaning service"
  }'
```

---

## Dispatcher API

**Base Path:** `/v1/dispatcher`
**Auth:** Admin (dispatcher role)
**File:** `backend/app/api/routes_dispatcher.py`

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/dispatcher/board` | `bookings.view` | Dispatch board data |
| POST | `/v1/dispatcher/assign` | `bookings.assign` | Assign worker to job |
| GET | `/v1/dispatcher/routes` | `bookings.view` | Route optimization |
| GET | `/v1/dispatcher/ai-suggestions` | `bookings.assign` | AI assignment suggestions |

---

## Bookings/Availability API

**Base Path:** `/v1/bookings`
**Auth:** Public/Admin
**File:** `backend/app/api/routes_bookings.py`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/bookings/availability` | Check slot availability |
| GET | `/v1/bookings/slots` | List available slots |
| POST | `/v1/bookings/reserve` | Reserve slot (public) |

**Example:**

```bash
# Check availability
curl "https://api.panidobro.com/v1/bookings/availability?date=2026-01-20&team_id=1"
```

---

## Payments API

**Base Path:** `/v1/payments`
**Auth:** Mixed (admin/client)
**File:** `backend/app/api/routes_payments.py`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/payments/stripe/checkout` | Create Stripe checkout session |
| POST | `/v1/payments/stripe/webhook` | Stripe webhook handler (no auth) |
| GET | `/v1/payments/history` | Payment history |

---

## Health & Metrics

### Health Checks

| Path | Purpose | Auth |
|------|---------|------|
| `/healthz` | Full health check (DB + migrations) | None |
| `/readyz` | Alias for `/healthz` | None |
| `/health` | Backup health check | None |

**Example:**

```bash
curl https://api.panidobro.com/healthz
```

**Response:**

```json
{
  "status": "ready",
  "db_connected": true,
  "migrations_current": true,
  "current_revision": "0086",
  "expected_revision": "0086"
}
```

### Metrics

| Path | Purpose | Auth |
|------|---------|------|
| `/metrics` | Prometheus metrics | Token (if enabled) |

**Example:**

```bash
curl https://api.panidobro.com/metrics \
  -H "Authorization: Bearer <metrics-token>"
```

**Metrics collected:**
- HTTP request count (by method, path, status)
- HTTP latency (by method, path)
- HTTP 5xx errors
- Custom business metrics (if configured)

---

## Error Responses

### RFC 7807 Problem Details

**All errors return RFC 7807 format:**

```json
{
  "type": "https://api.panidobro.com/problems/domain-error",
  "title": "Booking Not Found",
  "status": 404,
  "detail": "Booking abc123 does not exist or does not belong to your organization",
  "errors": [
    {"field": "booking_id", "message": "Not found"}
  ]
}
```

### Error Types

| Type | Status Code | Meaning |
|------|-------------|---------|
| `validation` | 422 | Request validation error |
| `domain` | 400, 404 | Business logic error |
| `rate-limit` | 429 | Rate limit exceeded |
| `server` | 500, 503 | Server error |

### Common Status Codes

| Code | Meaning | Example |
|------|---------|---------|
| 200 | OK | Successful request |
| 201 | Created | Resource created |
| 400 | Bad Request | Invalid data |
| 401 | Unauthorized | Missing/invalid auth |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource doesn't exist |
| 422 | Unprocessable Entity | Validation error |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Unexpected error |

---

## Rate Limiting

**Global:** 30 requests/minute per client IP
**Admin actions:** 5 requests/minute (for safety)

**Headers:**
- `X-RateLimit-Limit` - Rate limit
- `X-RateLimit-Remaining` - Remaining requests
- `X-RateLimit-Reset` - Reset timestamp

**Exemptions:**
- `/v1/payments/stripe/webhook` (Stripe webhooks)

---

## Request/Response Examples

### Admin: Create Booking

**Request:**

```bash
curl -X POST https://api.panidobro.com/v1/admin/ui/bookings/create \
  -u "admin:password" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "team_id=1" \
  -d "client_id=abc-123" \
  -d "starts_at=2026-01-20T10:00" \
  -d "duration_minutes=120"
```

**Response (200 OK):**

```json
{
  "id": "def-456",
  "org_id": "org-789",
  "team_id": 1,
  "client_id": "abc-123",
  "status": "pending",
  "starts_at": "2026-01-20T10:00:00Z",
  "duration_minutes": 120,
  "created_at": "2026-01-15T12:00:00Z"
}
```

### Admin: List Invoices

**Request:**

```bash
curl "https://api.panidobro.com/v1/admin/ui/invoices?status=unpaid&limit=10" \
  -u "admin:password"
```

**Response (200 OK):**

```json
{
  "invoices": [
    {
      "id": "inv-001",
      "client_id": "abc-123",
      "status": "sent",
      "total_amount": 15000,
      "due_date": "2026-01-25",
      "created_at": "2026-01-15T10:00:00Z"
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

### Worker: Update Job Status

**Request:**

```bash
curl -X POST https://api.panidobro.com/v1/worker/jobs/def-456/status \
  -u "+1234567890:workerpass" \
  -d "status=in_progress"
```

**Response (200 OK):**

```json
{
  "id": "def-456",
  "status": "in_progress",
  "updated_at": "2026-01-20T10:05:00Z"
}
```

### Public: Submit Lead

**Request:**

```bash
curl -X POST https://api.panidobro.com/v1/public/leads \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+1987654321",
    "message": "Need office cleaning"
  }'
```

**Response (201 Created):**

```json
{
  "id": "lead-789",
  "status": "new",
  "created_at": "2026-01-15T12:00:00Z"
}
```

---

## Related Documentation

- [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) - High-level architecture
- [MODULES.md](./MODULES.md) - Feature modules map
- [CONTENT_GUIDE.md](./CONTENT_GUIDE.md) - Coding conventions
- [docs/ADMIN_GUIDE.md](./docs/ADMIN_GUIDE.md) - Admin features guide
