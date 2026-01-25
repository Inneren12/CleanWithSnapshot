# Admin Action Audit Logging

## Overview
Admin action auditing provides an immutable, centralized record of privileged activity for compliance reviews, incident response, and forensic investigations. The audit trail distinguishes **WRITE** actions (mutations) from **READ** actions (sensitive access) and stores only metadata required for accountability.

## Definitions
**WRITE actions**
- Create, update, or delete any entity.
- Configuration changes, integrations, and feature settings changes.
- Role, permission, or access control changes.

**READ actions**
- Viewing PII (clients, users, leads, bookings).
- Viewing financial data (invoices, payments, finance reports).
- Viewing credentials metadata (integration configuration metadata, not secrets).
- Exporting data (CSV exports, data rights exports).

Only **sensitive READ actions** are audited; non-sensitive reads are intentionally excluded to reduce noise.

## What gets stored
- `action_type`: `READ` or `WRITE`
- `resource_type` + `resource_id` (when available)
- `sensitivity_level`: `normal`, `sensitive`, or `critical`
- Actor attribution (`admin_id`, `role`, `auth_method`)
- Optional `context` (e.g., reason string or system context)

**Data minimization:** Audit records **do not store returned data** for READ actions. Any payloads captured for WRITE actions are sanitized to remove sensitive values.

## Sensitive READ examples
| Resource | Example endpoint | Sensitivity |
| --- | --- | --- |
| User PII | `/v1/admin/users` | sensitive |
| Client PII | `/v1/admin/clients` | sensitive |
| Bookings | `/v1/admin/bookings` | sensitive |
| Leads | `/v1/admin/leads` | sensitive |
| Invoices | `/v1/admin/invoices` | sensitive |
| Finance reports | `/v1/admin/finance/*` | sensitive |
| Exports | `/v1/admin/exports/*` | critical |
| Data exports | `/v1/admin/data/export` | critical |
| Integration metadata | `/v1/admin/integrations/*` | critical |

## Querying admin audits
Use the read-only endpoint:
```
GET /v1/admin/audit/actions
```
Filters:
- `admin_id`
- `action_type` (`READ` | `WRITE`)
- `resource_type`
- `from_ts`, `to_ts` (ISO-8601)
- `limit`, `offset`

This endpoint is RBAC-protected and requires admin privileges.

## Compliance rationale
- **Immutability**: Audit records cannot be updated or deleted at the database level.
- **Non-bypassable**: Admin routes and background job flows route through centralized audit helpers or middleware.
- **Least data**: Only metadata is stored for sensitive reads; secrets and PII values are redacted.
