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
