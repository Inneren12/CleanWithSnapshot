# Organization User Quotas

## Overview
The platform supports a per-organization **maximum users** quota to enforce hard caps on active memberships. This limit is configured per organization and enforced before creating or reactivating a user membership.

## Configuration
Quota is stored in `organization_settings.max_users`.

- `NULL`: **Unlimited** (default for existing organizations)
- `0`: **No users allowed** (explicit block)
- `N > 0`: **Hard cap** on active memberships

Recommended rollout for new orgs: explicitly set a value during provisioning (leave `NULL` to preserve existing behavior).

## Enforcement behavior
- Enforcement happens **before** user creation or membership activation.
- All creation paths use the same hard gate (admin UI, IAM API, and any background import flow that creates memberships).
- When the quota is exceeded, the request returns **HTTP 409 Conflict** with:
  - Machine-readable error code: `ORG_USER_QUOTA_EXCEEDED`
  - Human-readable message: "Organization user quota exceeded"
- Quota violations are logged to the admin audit log with org ID, attempted action, current count, and max_users.

## Read-side visibility
- Admin UI: `GET /v1/admin/settings/org` returns `current_users_count` and `max_users`.
- Operators/Debug: `GET /v1/admin/orgs/{org_id}/user-quota` returns the same snapshot.

The count reflects **active memberships** and is optimized with an index on `(org_id, is_active)`.

## Metrics
- `org_user_quota_rejections_total`: Incremented when a create attempt exceeds the quota.

> Note: Metrics intentionally avoid org/user identifiers to keep label cardinality low.

## Examples

### Set a cap of 10 users
```
PATCH /v1/admin/settings/org
{
  "max_users": 10
}
```

### Disable all new users
```
PATCH /v1/admin/settings/org
{
  "max_users": 0
}
```

### Unlimited (default)
```
PATCH /v1/admin/settings/org
{
  "max_users": null
}
```

# Organization Storage Quotas

## Overview
The platform enforces a per-organization **storage quota** that tracks billable stored bytes and blocks new storage allocations when the limit would be exceeded.

### Storage usage definition
**Storage usage** = sum of sizes (bytes) of billable stored objects associated with an org.

**Included categories (explicit):**
- Order photos (booking photos uploaded via admin/worker/client flows)
- Booking photo evidence (quality photo uploads)
- Document PDFs (invoices, receipts, service agreements)

**Excluded categories (explicit):**
- Temporary multipart upload parts
- Derived thumbnails or cached derivatives
- Transient exports returned directly in API responses (CSV/JSON)

## Configuration
Quota is stored in `organization_settings.max_storage_bytes` with usage tracked in `organization_settings.storage_bytes_used`.

- `NULL`: **Unlimited** (default for existing organizations)
- `0`: **No new storage allowed**
- `N > 0`: **Hard cap** in bytes

## Enforcement behavior
- Enforcement happens **before** finalizing storage writes.
- All storage-producing paths use a shared reservation gate:
  1) **Reserve** bytes before upload/write (creates a pending reservation).
  2) **Finalize** reservation after confirming the stored size.
  3) **Release** reservations on failures or expiry.
- When the quota is exceeded, the request returns **HTTP 409 Conflict** with:
  - Machine-readable error code: `ORG_STORAGE_QUOTA_EXCEEDED`
  - Human-readable message: "Organization storage quota exceeded"
  - Remaining bytes in the error payload (if a limit is configured).

## Read-side visibility
- Admin UI: `GET /v1/admin/settings/org` returns:
  - `storage_bytes_used`
  - `max_storage_bytes`
  - `storage_usage_percent`
- Operator/Debug: `GET /v1/admin/orgs/{org_id}/storage-quota` returns:
  - `storage_bytes_used`, `storage_bytes_pending`, `max_storage_bytes`, `storage_usage_percent`

## Reconciliation
A daily job recomputes usage from DB file records and repairs drift:
- Order photos (`order_photos.size_bytes`)
- Booking photo evidence (`booking_photos.size_bytes`)
- Document PDFs (`documents.pdf_bytes`)

Drift repairs are logged to the admin audit log as `storage_usage_reconciled`.

## Reservation cleanup
Pending reservations expire and are released automatically by the storage quota cleanup job.

## Metrics
- `storage_quota_rejections_total`
- `storage_bytes_used` (gauge)
- `storage_reservations_pending` (gauge)

> Note: Metrics intentionally avoid org identifiers to keep label cardinality low.

## Examples

### Set a 5 GB storage cap
```
PATCH /v1/admin/settings/org
{
  "max_storage_bytes": 5368709120
}
```

### Disable all new storage
```
PATCH /v1/admin/settings/org
{
  "max_storage_bytes": 0
}
```

### Unlimited (default)
```
PATCH /v1/admin/settings/org
{
  "max_storage_bytes": null
}
```
