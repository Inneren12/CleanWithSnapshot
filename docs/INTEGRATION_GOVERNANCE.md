# Integration Configuration Governance

## Scope
Integration configuration changes are **always** audited. This audit trail is immutable and is intended for security incident response and compliance review (SOC-style). The audit trail covers configuration mutations only; runtime API calls made by integrations are **not** part of this log.

**Integration configuration change** includes:
- Enabling/disabling an integration
- Creating or rotating API keys/tokens
- Changing webhook URLs or secrets
- Changing mode (test ↔ live)
- Deleting or decommissioning an integration

## What is captured
Each integration audit entry records:
- **When** the change occurred (`occurred_at`)
- **Who** performed the change (`actor_type`, `actor_id`, `actor_role`, `auth_method`, `actor_source`)
- **Where** the change applies (`org_id`, `integration_type`, `integration_scope`)
- **What** changed (`action`, `before_state`, `after_state`)
- **Redaction evidence** (`redaction_map`)
- **Request traceability** (`request_id`)

### Supported actions
The audit `action` is one of:
- `enable`
- `disable`
- `create`
- `update`
- `rotate_secret`
- `delete`

The action is derived from before/after state and secret rotation detection. For example, a token refresh in QuickBooks produces `rotate_secret`.

## Secret redaction
Secrets are **never** stored in plaintext in the audit log. Secret fields are replaced with `***REDACTED***` and accompanied by:
- `*_present` (boolean indicator)
- `*_fingerprint` (non-reversible SHA-256 fingerprint)

The `redaction_map` documents which fields were redacted and provides before/after fingerprints to support rotation checks without exposing the secret.

## Failure policy (fail-closed)
If the audit log write fails, the integration configuration change **fails**. This prevents unaudited integration configuration mutations and preserves the integrity of the audit trail.

## Covered mutation paths
The following mutation paths are audited through the centralized integration audit service:
- **Google Calendar**: connect, token updates, disconnect
- **QuickBooks**: connect, token updates, disconnect

These paths correspond to the admin integration configuration endpoints and background integration configuration updates.

## Read-only audit access
Audit logs are available via a read-only, RBAC-protected endpoint:

```
GET /v1/admin/integrations/audit
```

### Filters
- `org_id` (required to match caller org)
- `integration_type` (e.g., `google_calendar`, `quickbooks`)
- `start` / `end` (ISO-8601 timestamps)
- `limit` / `offset` (pagination)

## Incident response example
**Scenario:** A QuickBooks refresh token is suspected to be compromised.

1. Query the integration audit log for `integration_type=quickbooks` and the impacted `org_id`.
2. Identify the latest `rotate_secret` entry.
3. Verify the `*_fingerprint` changed after rotation and confirm which actor performed it.
4. If rotation did not occur after the suspected compromise window, initiate immediate rotation and review follow-on integration behavior.

## Compliance alignment
This audit log is immutable at the database level and is designed to support SOC-style change management and incident investigation requirements.
