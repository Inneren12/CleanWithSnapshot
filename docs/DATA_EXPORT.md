# GDPR/CCPA Self-Serve Data Exports

This document describes the self-serve data export workflow used to satisfy GDPR/CCPA “Right of Access” requests. It covers the public endpoints, export contents, security model, retention, and operator troubleshooting.

## Endpoints

### Request an export (subject or admin)
```
POST /v1/data-rights/export-request
```
Body (admin use only):
```json
{
  "lead_id": "lead-uuid",
  "email": "subject@example.com"
}
```

- **Subject**: authenticated client portal users can request their own export (no body required).
- **Admin**: requires an authenticated SaaS token with `exports.run` permission. Admins must specify `lead_id` or `email`.
- Response: `export_id`, `status`, and `created_at`.

### List export status
```
GET /v1/data-rights/exports
```
Query params (admin only):
- `lead_id`
- `email`
- `limit` (default 50)
- `offset` (default 0)

Subject requests are implicitly scoped to the requesting client.

### Download export bundle
```
GET /v1/data-rights/exports/{export_id}/download
```
Returns a short-lived, signed redirect for object storage backends (S3/R2/Cloudflare) or streams the file directly for local storage with authenticated access control.

## Export contents

The bundle is stored as a JSON payload containing:
- Metadata: `export_id`, `org_id`, `subject_id`, `subject_type`, `subject_email`, `generated_at`.
- Subject data:
  - Leads and contact details.
  - Bookings and scheduling metadata.
  - Invoices and payments (no internal tokens).
  - Photo attachment metadata (no cross-tenant records).

Sensitive keys are redacted, and internal secrets (tokens, signatures) are excluded.

## Completeness tests

The test suite enforces a canonical export contract to ensure GDPR/CCPA bundles stay complete and scoped to
the subject:

- **Contract coverage:** tests assert the exported top-level sections and required fields per section
  (`leads`, `bookings`, `invoices`, `payments`, `photos`) to guarantee minimum schema coverage.
- **Subject scope:** fixtures generate data in multiple modules for a subject and confirm all records are present.
- **Cross-org isolation:** parallel fixtures in another org validate that no cross-tenant data appears.
- **Secret redaction:** fixtures include token-like keys to verify export redaction replaces them with `[REDACTED]`.

### Updating the contract safely

When adding a new exportable domain module or field:

1. Update the export builder to include the new section/fields.
2. Extend the export contract in `backend/tests/test_data_export_completeness.py` with the new section/keys.
3. Add fixture data for the new section to keep the completeness test deterministic.

## Security model

- **Authentication required** for all endpoints (client portal token or SaaS token).
- **Authorization**
  - Subject access is limited to their own exports.
  - Admin access requires the `exports.run` permission.
  - All queries are scoped by `org_id` to prevent cross-tenant access.
- **Short-lived delivery**
  - Signed URLs are generated for object storage downloads.
  - Local storage downloads are protected by authenticated access control.
- **Rate limiting & abuse protection**
  - **Export requests** are limited per subject and org using a two-tier policy: burst (`data_export_request_rate_limit_per_minute`, default 1/min) and sustained (`data_export_request_rate_limit_per_hour`, default 5/hour).
  - **Downloads** are limited per export subject (`data_export_download_rate_limit_per_minute`, default 10/min).
  - **Denied download attempts** (subject mismatch or missing permission) are throttled after repeated failures and can trigger a temporary lockout window. Defaults:
    - `data_export_download_failure_limit_per_window` (default 3 in 5 minutes)
    - `data_export_download_lockout_limit_per_window` (default 5 in 30 minutes)
  - All limits can be tuned via environment settings or per-organization overrides in org settings.
  - Rate-limited responses return HTTP 429 with `Retry-After` and machine code `DATA_EXPORT_RATE_LIMITED`.
- **Audit logging**
  - Export lifecycle events are recorded in the immutable admin audit trail with request correlation IDs.
  - Events: `DATA_EXPORT_REQUESTED`, `DATA_EXPORT_COMPLETED`, `DATA_EXPORT_FAILED`, `DATA_EXPORT_DOWNLOADED`, `DATA_EXPORT_DOWNLOAD_DENIED`.
  - Audit context includes `org_id`, `export_id`, `subject_id` (identifier only), `actor_type`, `actor_id`, `request_id`, and server-generated timestamps.
  - Admin actions include explicit `on_behalf_of` metadata when acting for a subject.

### Querying export audit events
Export audits are stored in the admin audit log and can be queried via:

```
GET /v1/admin/audit/actions?resource_type=data_export&from_ts=<ISO>&to_ts=<ISO>&limit=<n>&offset=<n>
```

Filter the response by `action` to isolate export events (for example `DATA_EXPORT_DOWNLOADED`). Each record includes a server-side `created_at` timestamp and metadata for actor/subject attribution.

### Compliance rationale (GDPR/CCPA evidence)
The immutable export audit trail provides verifiable evidence of:
- **Who** initiated or accessed an export (`actor_type`, `actor_id`).
- **What** was acted on (`export_id`, `subject_id`, `org_id`).
- **When** the action occurred (`created_at` timestamp).
- **Outcome** of processing and access attempts (completed/failed/downloaded/denied).

This supports GDPR/CCPA accountability requirements and incident investigations without storing exported content in audit logs.

## Retention policy

Export bundles are retained for `data_export_retention_days` (default: 7 days). After this window, the `data-export-retention` job deletes stored bundles and removes database records. Update retention settings in `app.settings` to align with policy requirements.

## Cooldown behavior

If a matching export was generated recently, the request endpoint returns the existing export instead of creating a new record. The cooldown window is controlled by `data_export_cooldown_minutes` (default: 30). This prevents repeated regeneration spam while keeping exports available for re-download during the retention window.

## Operator troubleshooting

If an export remains pending:
- Confirm the `data-rights-export` job is scheduled and running.
- Check the export record status and `error_code` for failures.
- Verify storage backend credentials and permissions.

If a download fails:
- Confirm the export status is `completed`.
- Verify the storage backend configuration and signed URL TTL (`data_export_signed_url_ttl_seconds`).
- Ensure the requesting identity matches the subject or has `exports.run` permission.
- Check rate limit and lockout settings if 429 responses are returned (`data_export_*` settings).
