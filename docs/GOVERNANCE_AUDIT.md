# Configuration Change Audit Logging (PR-GOV-01)

## Purpose
This policy documents the server-side, immutable audit trail for configuration changes. The audit trail is **non-bypassable**, records **who/what/when**, and captures **before/after** state for investigations, incident reviews, and compliance audits.

## What is audited (configuration change definition)
The following configuration mutations **always** generate exactly one audit entry:

- **Org settings** (timezone, currency, legal fields, branding, limits, etc.).
- **Feature flag overrides** (feature/module enablement for orgs).
- **Integration credentials/settings** (e.g., Google Calendar, QuickBooks connect/disconnect).
- **System-level toggles exposed via admin APIs** (when present).

Read-only access **does not** create audit records.

## What is not audited
- Read-only views of configuration.
- Non-config operational data changes (bookings, invoices, etc.).
- Derived or cached copies of configuration values.

## Audit data captured
Each immutable audit record includes:

- **when**: server-generated `occurred_at`
- **who**: actor type, actor id, role, auth method (basic/token/break-glass)
- **what**: config scope + config key
- **diff**: full `before_value` and `after_value`
- **correlation**: `request_id`

### Actor attribution
- **Admin actions**: `actor_type=admin`, `actor_id=<admin username>`, `actor_role=<role>`, `auth_method=<basic|token|break_glass>`.
- **System/automation actions**: `actor_type=system|automation`, `actor_id=NULL`, `actor_source=<job/migration identifier>`.

## Redaction rules
Audit logs must never store secrets in plaintext. Redaction is applied on write using the following rules:

- Any keys matching the explicit sensitive list are replaced with `[REDACTED]`.
- Keys ending with `_token`, `_secret`, `_password`, or `_key` are replaced with `[REDACTED]`.

This covers values such as `refresh_token`, `encrypted_refresh_token`, API keys, webhook secrets, and auth tokens.

## Immutability guarantees
- Audit rows **cannot** be updated or deleted via normal application flows.
- Database-level triggers block `UPDATE` and `DELETE` operations on the audit table.
- ORM-level safeguards raise errors on any mutation attempt.

## Failure policy (fail-closed)
Audit writes occur in the same DB transaction as the configuration change. If the audit write fails, the configuration change **fails** and is rolled back. This ensures a complete and consistent audit trail.

## How to review audit logs
Use the admin read-only endpoint:

```
GET /v1/admin/settings/audit/config?org_id=<org_uuid>&config_scope=<scope>&start=<ISO>&end=<ISO>&limit=<n>&offset=<n>
```

- Supports filtering by org, config scope, and time range.
- Paginates with `limit`, `offset`, and `next_offset`.

## Compliance notes
This audit trail provides immutable, server-side evidence of configuration change history suitable for SOC-style controls (e.g., change management, accountability, and incident reconstruction).
