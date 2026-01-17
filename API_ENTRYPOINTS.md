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

### Router Registration (30 routers)

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
| 25 | admin_finance | `/v1/admin/finance` | Admin | `routes_admin_finance.py` |
| 26 | queues | `/v1/admin/queue` | Admin | `routes_queues.py` |
| 27 | timeline | `/v1/timeline` | Admin | `routes_timeline.py` |
| 28 | health_backup | `/health` | None | `health_backup.py` |
| 29 | metrics | `/metrics` | Token | `routes_metrics.py` |
| 30 | style_guide | `/style-guide` | Dev Only | `routes_style_guide.py` |

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
| GET | `/v1/admin/activity` | `core.view` + `module.dashboard` | Live activity feed (polling) |

### Leads

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/leads` | `contacts.view` (or `leads.view`) | Lead pipeline list (status/query/date filters + pagination) |
| GET | `/v1/admin/leads/{lead_id}` | `contacts.view` (or `leads.view`) | Lead detail with contact info, requested service snapshot, notes, and timeline |
| PATCH | `/v1/admin/leads/{lead_id}` | `contacts.edit` (or `leads.edit`) | Update lead status, notes, or loss reason |
| POST | `/v1/admin/leads/{lead_id}/timeline` | `contacts.edit` (or `leads.edit`) | Add a lead timeline entry (quote sent, contacted, etc.) |
| GET | `/v1/admin/leads/{lead_id}/quotes` | `contacts.view` (or `leads.view`) | List quotes for a lead (includes follow-ups + expiry state) |
| POST | `/v1/admin/leads/{lead_id}/quotes` | `contacts.edit` (or `leads.edit`) | Create a lead quote (amount, service type, expiry, sent_at) |
| POST | `/v1/admin/leads/{lead_id}/quotes/{quote_id}/followups` | `contacts.edit` (or `leads.edit`) | Log a manual quote follow-up note |

**Query params:** `status`, `query`, `from`, `to`, `page`

**Status values:** `NEW`, `CONTACTED`, `QUOTED`, `WON`, `LOST`

**Loss reason:** Required when marking a lead as `LOST` via PATCH `/v1/admin/leads/{lead_id}`.

**Quote status values:** `DRAFT`, `SENT`, `EXPIRED`, `ACCEPTED`, `DECLINED` (amounts are stored in cents).

### Marketing

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/marketing/analytics/lead-sources` | `settings.manage` | Lead source analytics for a month (leads, bookings, revenue, spend) |
| GET | `/v1/admin/marketing/spend` | `settings.manage` | List manual spend entries for a month |
| PUT | `/v1/admin/marketing/spend` | `settings.manage` | Upsert manual spend for a source + month |
| GET | `/v1/admin/marketing/email-segments` | `settings.manage` | List email segments |
| POST | `/v1/admin/marketing/email-segments` | `settings.manage` | Create email segment |
| GET | `/v1/admin/marketing/email-segments/{segment_id}` | `settings.manage` | Get email segment |
| PATCH | `/v1/admin/marketing/email-segments/{segment_id}` | `settings.manage` | Update email segment |
| DELETE | `/v1/admin/marketing/email-segments/{segment_id}` | `settings.manage` | Delete email segment |
| GET | `/v1/admin/marketing/email-campaigns` | `settings.manage` | List email campaigns |
| POST | `/v1/admin/marketing/email-campaigns` | `settings.manage` | Create email campaign |
| GET | `/v1/admin/marketing/email-campaigns/{campaign_id}` | `settings.manage` | Get email campaign |
| PATCH | `/v1/admin/marketing/email-campaigns/{campaign_id}` | `settings.manage` | Update email campaign |
| DELETE | `/v1/admin/marketing/email-campaigns/{campaign_id}` | `settings.manage` | Delete email campaign |

```json
{
  "items": [
    {
      "lead_id": "c6e4c9c8-9f51-4ce9-a5e8-9b3b6d8b87c1",
      "name": "Avery Chen",
      "email": "avery@example.com",
      "phone": "780-555-0101",
      "status": "CONTACTED",
      "notes": "Requested follow-up tomorrow.",
      "source": "google",
      "campaign": "spring-clean",
      "keyword": "move out clean",
      "landing_page": "/quote",
      "created_at": "2026-02-01T12:00:00Z",
      "updated_at": "2026-02-02T09:30:00Z",
      "referrer": null,
      "referral_code": "ABCD1234",
      "referred_by_code": null,
      "referral_credits": 0,
      "postal_code": "T5J 0N3",
      "preferred_dates": []
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 25
}
```

**Lead detail response fields:** includes lead contact data plus `structured_inputs`, `estimate_snapshot`, and `timeline`
entries sorted by newest first. Each timeline entry includes `action`, `timestamp`, and optional `metadata.note`.

#### Ops Dashboard Response (critical alerts)

`GET /v1/admin/dashboard/ops` includes `critical_alerts` for the Critical Alerts widget.
`hero_metrics` and `revenue_week` summarize today and week-to-date totals in the org timezone.
`top_performers` summarizes the current month (org timezone boundaries) across workers, clients, teams, and services.
If org settings branding includes `weekly_revenue_goal_cents` (or `weekly_revenue_goal`), the `goal` object is included in `revenue_week`.

```json
{
  "as_of": "2026-01-20T15:04:05Z",
  "org_timezone": "America/Denver",
  "org_currency": "CAD",
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
  },
  "hero_metrics": {
    "bookings_today": 12,
    "revenue_today_cents": 184000,
    "workers_available": 4,
    "workers_total": 9,
    "worker_rating_avg": 4.7
  },
  "revenue_week": {
    "week_start": "2026-01-20",
    "week_end": "2026-01-26",
    "days": [
      { "date": "2026-01-20", "revenue_cents": 32000 },
      { "date": "2026-01-21", "revenue_cents": 45000 }
    ],
    "total_revenue_cents": 184000,
    "currency": "CAD",
    "goal": {
      "goal_cents": 200000,
      "remaining_cents": 16000
    }
  },
  "top_performers": {
    "month_start": "2026-01-01",
    "month_end": "2026-01-31",
    "total_revenue_cents": 720000,
    "workers": [
      {
        "worker_id": 12,
        "name": "Maria R.",
        "team_id": 4,
        "team_name": "Crew North",
        "bookings_count": 18,
        "revenue_cents": 240000
      }
    ],
    "clients": [
      {
        "client_id": "client-123",
        "name": "Acme Co.",
        "email": "billing@acme.co",
        "bookings_count": 6,
        "revenue_cents": 180000
      }
    ],
    "teams": [
      {
        "team_id": 4,
        "name": "Crew North",
        "bookings_count": 18,
        "revenue_cents": 240000
      }
    ],
    "services": [
      {
        "label": "deep_clean",
        "bookings_count": 9,
        "revenue_cents": 240000,
        "share_of_revenue": 0.33
      }
    ]
  }
}
```

#### Activity Feed Response

`GET /v1/admin/activity` returns the latest cross-module events for the dashboard activity feed.
Query parameters:
- `since` (optional ISO 8601 timestamp) filters events to those at/after the timestamp.
- `limit` (optional, default 20, max 100) limits returned items.

```json
{
  "as_of": "2026-01-20T15:04:05Z",
  "items": [
    {
      "event_id": "booking_created:booking-123",
      "kind": "booking_created",
      "title": "New booking created",
      "description": "Booking booking-123 · Status PENDING",
      "timestamp": "2026-01-20T14:58:12Z",
      "entity_ref": {
        "kind": "booking",
        "id": "booking-123",
        "status": "PENDING"
      },
      "action": {
        "label": "Open schedule",
        "href": "/admin/schedule?date=2026-01-21"
      }
    }
  ]
}
```

#### Notifications Center Feed

`GET /v1/admin/notifications` returns the inbox feed with filters and cursor pagination.
Query parameters:
- `filter` (`all`, `urgent`, `unread`) controls feed mode (default: `all`).
- `limit` (default 50, max 200) limits returned items.
- `cursor` (opaque) paginates older items.
- `from` / `to` (optional ISO 8601 timestamps) apply date range filters.

```json
{
  "items": [
    {
      "id": "5d4f9a6a-3d2d-4d62-a9ff-2b2e01c7c012",
      "created_at": "2026-01-30T09:15:00Z",
      "priority": "HIGH",
      "type": "payment_failed",
      "title": "Payment failed",
      "body": "Invoice INV-001 payment failed.",
      "entity_type": "invoice",
      "entity_id": "INV-001",
      "action_href": "/admin/invoices/INV-001",
      "action_kind": "open_invoice",
      "is_read": false,
      "read_at": null
    }
  ],
  "next_cursor": "MjAyNi0wMS0zMFQwOToxNTowMFp8NWQ0ZjlhNmEtM2QyZC00ZDYyLWE5ZmYtMmIyZTAxYzdjMDEy",
  "limit": 50
}
```

**Mark read endpoints:**
- `POST /v1/admin/notifications/{id}/read` marks a single event as read.
- `POST /v1/admin/notifications/read_all` marks all events read for the current user.

#### Notifications Rules Presets (Owner-only)

`GET /v1/admin/notifications/rules` returns preset notification rules configuration.
`PATCH /v1/admin/notifications/rules` updates preset configuration.
Requires Owner basic auth (role check).

**Preset keys:**
`no_show`, `payment_failed`, `negative_review`, `low_stock`, `high_value_lead`

```json
{
  "org_id": "b7d3ef62-6b4b-4f3b-9f48-6a89a80fb2d5",
  "presets": [
    {
      "preset_key": "payment_failed",
      "enabled": true,
      "notify_roles": ["owner", "finance"],
      "notify_user_ids": [],
      "escalation_delay_min": 30
    }
  ]
}
```

#### Notification Digests (Owner-only)

`GET /v1/admin/notifications/digests` returns digest settings (daily/weekly/monthly).
`PATCH /v1/admin/notifications/digests` updates digest schedules, enablement, and recipients.

Digest keys: `daily_summary`, `weekly_analytics`, `monthly_report`.
Schedules: `daily`, `weekly`, `monthly`.

```json
{
  "org_id": "b7d3ef62-6b4b-4f3b-9f48-6a89a80fb2d5",
  "digests": [
    {
      "digest_key": "daily_summary",
      "enabled": true,
      "schedule": "daily",
      "recipients": ["owner@example.com"]
    }
  ]
}
```

### Quality

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/quality/issues` | `quality.view` | List quality issues with filters (`status`, `severity`, `from`, `to`, `worker_id`, `client_id`) |
| GET | `/v1/admin/quality/issues/triage` | `quality.view` | Triage buckets (Critical/Medium/Low) + top items |
| GET | `/v1/admin/quality/issues/{id}` | `quality.view` | Issue detail with booking/worker/client links + response history |
| PATCH | `/v1/admin/quality/issues/{id}` | `quality.manage` | Update status, resolution, or assignee (updates `resolved_at` on close/resolution) |
| PATCH | `/v1/admin/quality/issues/{id}/tags` | `quality.manage` | Replace issue tag assignments (controlled vocabulary keys) |
| POST | `/v1/admin/quality/issues/{id}/respond` | `quality.manage` | Log outbound response or note (sets `first_response_at` on first response) |
| GET | `/v1/admin/quality/issues/common` | `quality.view` | Common issue tags analytics with affected workers (`from`/`to` date range, defaults to last 30 days) |
| GET | `/v1/admin/quality/reviews` | `quality.view` | List client reviews with filters (`stars`, `from`, `to`, `worker_id`, `client_id`, `has_issue`, `page`) |
| GET | `/v1/admin/quality/ratings/distribution` | `quality.view` | Rating distribution for a period (`from`, `to`, defaults to current month) |
| GET | `/v1/admin/quality/services/breakdown` | `quality.view` | Service-type quality breakdown (`from`, `to` date range, defaults to current month) |
| GET | `/v1/admin/quality/workers/leaderboard` | `quality.view` | Worker quality leaderboard (`from`, `to`, `include_trend`) |
| GET | `/v1/admin/quality/workers/{id}/summary` | `quality.view` | Worker quality summary (average rating, review count, complaint count, last review) |
| GET | `/v1/admin/quality/clients/{id}/summary` | `quality.view` | Client quality summary (average rating, review count, complaint count, last review) |
| POST | `/v1/admin/quality/reviews/{id}/reply` | `quality.manage` | Log reply to a review using a template or custom message |

**Review templates:** Stored in `backend/app/domain/quality/service.py` (`REVIEW_REPLY_TEMPLATES`) and returned with the reviews list response for UI selection.

**Worker leaderboard response shape (example):**
```json
{
  "from_date": "2026-01-01",
  "to_date": "2026-01-31",
  "as_of": "2026-02-01T02:15:00Z",
  "workers": [
    {
      "worker_id": 12,
      "worker_name": "Maria R.",
      "team_id": 4,
      "team_name": "Crew North",
      "average_rating": 4.6,
      "review_count": 18,
      "complaint_count": 1,
      "trend": {
        "previous_average_rating": 4.4,
        "previous_review_count": 12,
        "previous_complaint_count": 2,
        "average_rating_delta": 0.2,
        "review_count_delta": 6,
        "complaint_count_delta": -1
      }
    }
  ]
}
```

**Triage response shape (example):**
```json
{
  "as_of": "2026-01-20T15:04:05Z",
  "buckets": [
    {
      "severity": "critical",
      "total": 2,
      "items": [
        {
          "id": "7b0a1e2e-4e59-4b2e-9b3d-8c2d9c19f1c1",
          "summary": "Client reported missed area",
          "status": "open",
          "severity": "critical",
          "rating": 1,
          "created_at": "2026-01-20T14:58:12Z",
          "booking_id": "booking-123",
          "worker_id": 12,
          "client_id": "client-456"
        }
      ]
    }
  ]
}
```

**SLA timestamps:**
- `first_response_at` is set when the first outbound response is logged via `POST /respond` with `response_type="response"`.
- `resolved_at` is set when status transitions to `resolved` or `closed` (and cleared if re-opened).

### Inventory

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/inventory/categories` | `inventory.view` or `core.view` | List inventory categories with search and pagination |
| POST | `/v1/admin/inventory/categories` | `inventory.manage` or `admin.manage` | Create a new inventory category |
| PATCH | `/v1/admin/inventory/categories/{category_id}` | `inventory.manage` or `admin.manage` | Update an existing category |
| DELETE | `/v1/admin/inventory/categories/{category_id}` | `inventory.manage` or `admin.manage` | Delete a category (items' category_id set to NULL) |
| GET | `/v1/admin/inventory/items` | `inventory.view` or `core.view` | List inventory items with filters and pagination |
| GET | `/v1/admin/inventory/low_stock` | `inventory.view` | List low stock inventory items with need quantities |
| POST | `/v1/admin/inventory/items` | `inventory.manage` or `admin.manage` | Create a new inventory item |
| PATCH | `/v1/admin/inventory/items/{item_id}` | `inventory.manage` or `admin.manage` | Update an existing item |
| DELETE | `/v1/admin/inventory/items/{item_id}` | `inventory.manage` or `admin.manage` | Delete an inventory item |
| GET | `/v1/admin/inventory/suppliers` | `inventory.view` or `core.view` | List inventory suppliers with search and pagination |
| POST | `/v1/admin/inventory/suppliers` | `inventory.manage` or `admin.manage` | Create a new inventory supplier |
| PATCH | `/v1/admin/inventory/suppliers/{supplier_id}` | `inventory.manage` or `admin.manage` | Update an existing supplier |
| DELETE | `/v1/admin/inventory/suppliers/{supplier_id}` | `inventory.manage` or `admin.manage` | Delete an inventory supplier |
| GET | `/v1/admin/inventory/purchase-orders` | `inventory.view` or `core.view` | List purchase orders with status and supplier filters |
| POST | `/v1/admin/inventory/purchase-orders` | `inventory.manage` or `admin.manage` | Create a new purchase order |
| GET | `/v1/admin/inventory/purchase-orders/{po_id}` | `inventory.view` or `core.view` | Get a purchase order with line items |
| PATCH | `/v1/admin/inventory/purchase-orders/{po_id}` | `inventory.manage` or `admin.manage` | Update a draft purchase order |
| POST | `/v1/admin/inventory/purchase-orders/{po_id}/mark_ordered` | `inventory.manage` or `admin.manage` | Mark a purchase order as ordered |
| POST | `/v1/admin/inventory/purchase-orders/{po_id}/mark_received` | `inventory.manage` or `admin.manage` | Mark a purchase order as received (updates stock) |
| POST | `/v1/admin/inventory/consumption` | `inventory.manage` or `admin.manage` | Record inventory consumption (gated by `inventory.usage_analytics`) |
| GET | `/v1/admin/inventory/usage_analytics` | `inventory.view` or `core.view` | Usage analytics summary (gated by `inventory.usage_analytics`) |

**Auth:** Admin HTTP Basic (`ADMIN_BASIC_USERNAME`/`ADMIN_BASIC_PASSWORD`, `VIEWER_BASIC_USERNAME`/`VIEWER_BASIC_PASSWORD`).

**Category query params (`GET /v1/admin/inventory/categories`):**

| Param | Type | Description |
|-------|------|-------------|
| `query` | `string` | Search by category name (optional) |
| `page` | `int` | Page number (default: 1) |
| `page_size` | `int` | Items per page (default: 50, max: 100) |

**Item query params (`GET /v1/admin/inventory/items`):**

| Param | Type | Description |
|-------|------|-------------|
| `query` | `string` | Search by item name or SKU (optional) |
| `category_id` | `UUID` | Filter by category (optional) |
| `active` | `bool` | Filter by active status (optional) |
| `page` | `int` | Page number (default: 1) |
| `page_size` | `int` | Items per page (default: 50, max: 100) |

**Low stock query params (`GET /v1/admin/inventory/low_stock`):**

| Param | Type | Description |
|-------|------|-------------|
| `only_below_min` | `bool` | When true, return only items with `current_qty < min_qty` (default: true) |
| `page` | `int` | Page number (default: 1) |
| `page_size` | `int` | Items per page (default: 50, max: 100) |

**Supplier query params (`GET /v1/admin/inventory/suppliers`):**

| Param | Type | Description |
|-------|------|-------------|
| `query` | `string` | Search by supplier name, email, or phone (optional) |
| `page` | `int` | Page number (default: 1) |
| `page_size` | `int` | Items per page (default: 50, max: 100) |

**Purchase order query params (`GET /v1/admin/inventory/purchase-orders`):**

| Param | Type | Description |
|-------|------|-------------|
| `status` | `string` | Filter by status: `draft`, `ordered`, `received` (optional) |
| `supplier_id` | `UUID` | Filter by supplier (optional) |
| `page` | `int` | Page number (default: 1) |
| `page_size` | `int` | Items per page (default: 50, max: 100) |

**Purchase order update semantics (`PATCH /v1/admin/inventory/purchase-orders/{po_id}`):**
- Omit `notes` to leave the current notes unchanged.
- Send `notes: ""` (empty string) to clear notes (stored as `null`).
- Send a non-empty string to replace notes.

**Usage analytics query params (`GET /v1/admin/inventory/usage_analytics`):**

| Param | Type | Description |
|-------|------|-------------|
| `from` | `datetime` | Start of consumption window (optional) |
| `to` | `datetime` | End of consumption window (optional) |

**Usage analytics response shape:**
```json
{
  "total_consumption_cents": 12000,
  "cost_per_booking_avg_cents": 4000,
  "by_service_type": [
    {
      "service_type_id": 1,
      "bookings": 3,
      "consumption_cents": 9000,
      "cost_per_booking_cents": 3000
    }
  ],
  "top_items": [
    {
      "item_id": "1b2c3d4e-5f6a-7b8c-9d0e-1f2a3b4c5d6e",
      "consumption_cents": 5000,
      "qty": "6.00"
    }
  ]
}
```

**Category list response shape:**
```json
{
  "items": [
    {
      "category_id": "c6e4c9c8-9f51-4ce9-a5e8-9b3b6d8b87c1",
      "org_id": "b7d3ef62-6b4b-4f3b-9f48-6a89a80fb2d5",
      "name": "Cleaning Supplies",
      "sort_order": 1,
      "created_at": "2026-01-15T10:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 50
}
```

**Item list response shape:**
```json
{
  "items": [
    {
      "item_id": "d7f5e0d9-0g62-5df0-b6f9-0c4c7e9c98d2",
      "org_id": "b7d3ef62-6b4b-4f3b-9f48-6a89a80fb2d5",
      "category_id": "c6e4c9c8-9f51-4ce9-a5e8-9b3b6d8b87c1",
      "sku": "SKU001",
      "name": "Glass Cleaner",
      "unit": "bottles",
      "current_qty": "10.00",
      "min_qty": "5.00",
      "location_label": "Shelf A",
      "active": true,
      "created_at": "2026-01-15T10:00:00Z",
      "category_name": null
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 50
}
```

**Low stock list response shape:**
```json
{
  "items": [
    {
      "item_id": "1f5a1c2d-3e4f-5a6b-7c8d-9e0f1a2b3c4d",
      "org_id": "b7d3ef62-6b4b-4f3b-9f48-6a89a80fb2d5",
      "category_id": "c6e4c9c8-9f51-4ce9-a5e8-9b3b6d8b87c1",
      "sku": "SKU001",
      "name": "Glass Cleaner",
      "unit": "bottles",
      "current_qty": "2.00",
      "min_qty": "5.00",
      "need_qty": "3.00",
      "location_label": "Shelf A",
      "active": true,
      "created_at": "2026-01-15T10:00:00Z",
      "category_name": null
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 50
}
```

**Supplier list response shape:**
```json
{
  "items": [
    {
      "supplier_id": "8b7a6c5d-4e3f-2a1b-9c8d-7e6f5a4b3c2d",
      "org_id": "b7d3ef62-6b4b-4f3b-9f48-6a89a80fb2d5",
      "name": "Acme Supplies",
      "email": "orders@acme.test",
      "phone": "555-0100",
      "address": "123 Main St",
      "terms": "Net 30",
      "delivery_days": "Mon,Wed",
      "min_order_cents": 2500,
      "notes": "Primary vendor",
      "created_at": "2026-01-15T10:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 50
}
```

**Org scoping:** All endpoints are org-scoped. Categories and items from other organizations are not visible or accessible.

**Status codes:** `401` when auth is missing/invalid, `403` when authenticated but lacking permission, `400` for validation errors (ex: unknown category on item create/update), `404` for missing or cross-org resources.

**Cascade behavior:** Deleting a category sets `category_id` to NULL for all items in that category (does not delete items).

---

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

### Finance (Expenses & Budgets)

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/finance/expense-categories` | `finance.view` | List expense categories (search + pagination) |
| POST | `/v1/admin/finance/expense-categories` | `finance.manage` | Create expense category |
| PATCH | `/v1/admin/finance/expense-categories/{category_id}` | `finance.manage` | Update expense category |
| DELETE | `/v1/admin/finance/expense-categories/{category_id}` | `finance.manage` | Delete expense category |
| GET | `/v1/admin/finance/expenses` | `finance.view` | List expenses (filters + pagination) |
| POST | `/v1/admin/finance/expenses` | `finance.manage` | Create expense |
| PATCH | `/v1/admin/finance/expenses/{expense_id}` | `finance.manage` | Update expense |
| DELETE | `/v1/admin/finance/expenses/{expense_id}` | `finance.manage` | Delete expense |
| GET | `/v1/admin/finance/budgets` | `finance.view` | List budgets for a month/category |
| POST | `/v1/admin/finance/budgets` | `finance.manage` | Create budget |
| PATCH | `/v1/admin/finance/budgets/{budget_id}` | `finance.manage` | Update budget |
| DELETE | `/v1/admin/finance/budgets/{budget_id}` | `finance.manage` | Delete budget |
| GET | `/v1/admin/finance/expenses/summary` | `finance.view` | Totals by category with budget utilization |
| GET | `/v1/admin/finance/pnl` | `finance.view` | Profit & Loss report (revenue vs expenses) |

**Expense list query params:** `from`, `to`, `category_id`, `query`, `page`, `page_size`.

**Budget list query params:** `month` (`YYYY-MM`), `category_id`.

**Summary response shape (example):**
```json
{
  "from_date": "2026-01-01",
  "to_date": "2026-01-31",
  "total_cents": 15000,
  "total_tax_cents": 1500,
  "total_budget_cents": 30000,
  "percent_of_budget": 0.5,
  "categories": [
    {
      "category_id": "9f36...",
      "category_name": "Supplies",
      "total_cents": 5000,
      "tax_cents": 500,
      "budget_cents": 10000,
      "percent_of_budget": 0.5
    }
  ]
}
```

**P&L query params:** `from`, `to` (required), optional `format=csv`.

**P&L response shape (example):**
```json
{
  "from": "2026-01-01",
  "to": "2026-01-31",
  "revenue_cents": 15000,
  "expense_cents": 5300,
  "net_cents": 9700,
  "revenue_breakdown": [
    { "label": "card", "total_cents": 5000 }
  ],
  "expense_breakdown_by_category": [
    { "category_id": "9f36...", "category_name": "Supplies", "total_cents": 3300, "tax_cents": 300 }
  ],
  "data_sources": {
    "revenue": "invoice_payments (status=SUCCEEDED, received_at/created_at)",
    "expenses": "finance_expenses"
  }
}
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

### Training

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/training/workers/{worker_id}/status` | `training.view` (fallback `core.view`) | Worker training status (requirements + completion + expiry) |
| POST | `/v1/admin/training/workers/{worker_id}/records` | `training.manage` (fallback `admin.manage`) | Record a completion/certificate update |
| GET | `/v1/admin/training/courses` | `training.view` | List training courses |
| POST | `/v1/admin/training/courses` | `training.manage` | Create a training course |
| GET | `/v1/admin/training/courses/{course_id}` | `training.view` | Training course detail |
| PATCH | `/v1/admin/training/courses/{course_id}` | `training.manage` | Update a training course |
| DELETE | `/v1/admin/training/courses/{course_id}` | `training.manage` | Delete a training course |
| GET | `/v1/admin/training/courses/{course_id}/assignments` | `training.view` | List assignments for a course |
| POST | `/v1/admin/training/courses/{course_id}/assign` | `training.manage` | Assign workers to a course |
| GET | `/v1/admin/training/workers/{worker_id}/assignments` | `training.view` | List assignments for a worker |
| PATCH | `/v1/admin/training/assignments/{assignment_id}` | `training.manage` | Update assignment status/score |
| GET | `/v1/admin/training/sessions` | `training.view` | List training sessions (org timezone range) |
| POST | `/v1/admin/training/sessions` | `training.manage` | Create a training session + attendee blocks |
| GET | `/v1/admin/training/sessions/{session_id}` | `training.view` | Training session detail + attendees |
| PATCH | `/v1/admin/training/sessions/{session_id}` | `training.manage` | Update training session details |
| DELETE | `/v1/admin/training/sessions/{session_id}` | `training.manage` | Cancel a training session |
| POST | `/v1/admin/training/sessions/{session_id}/attendees` | `training.manage` | Replace attendee list for a session |
| GET | `/v1/admin/training/workers` | `training.view` | List workers for session attendance |

**Status response fields:** `requirements` entries include `key`, `title`, `required`, `completed_at`, `expires_at`, `next_due_at`, and `status` (`ok`, `due`, `overdue`).

**Record request body (example):**

```json
{
  "requirement_key": "whmis",
  "completed_at": "2026-02-10T15:00:00Z",
  "expires_at": "2027-02-10T15:00:00Z",
  "score": 92,
  "note": "Completed refresher course."
}
```

**Training sessions list query params:**
- `from` / `to`: `YYYY-MM-DD` in org timezone (defaults to current month in org TZ).

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

**Org settings fields (subset):**
- `referral_credit_trigger` controls when referral credits are awarded:
  - `deposit_paid` (deposit payment captured)
  - `booking_confirmed` (booking confirmed)
  - `booking_or_payment` (either event)

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

### Marketing (Promo Codes)

**Path:** `/v1/admin/marketing/promo-codes*`
**File:** `backend/app/api/routes_admin_marketing.py`

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/marketing/promo-codes` | `settings.manage` | List promo codes |
| POST | `/v1/admin/marketing/promo-codes` | `settings.manage` | Create promo code |
| GET | `/v1/admin/marketing/promo-codes/{id}` | `settings.manage` | Promo code detail |
| PATCH | `/v1/admin/marketing/promo-codes/{id}` | `settings.manage` | Update promo code |
| DELETE | `/v1/admin/marketing/promo-codes/{id}` | `settings.manage` | Delete promo code |
| POST | `/v1/admin/marketing/promo-codes/validate` | `settings.manage` | Validate promo code restrictions |

---

### Marketing (Referrals)

**Path:** `/v1/admin/marketing/referrals*`
**File:** `backend/app/api/routes_admin_marketing.py`

| Method | Path | Permission | Purpose |
|--------|------|------------|---------|
| GET | `/v1/admin/marketing/referrals/leaderboard` | `core.view` | Referral leaderboard |

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
