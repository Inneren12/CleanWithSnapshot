# Feature Flag Governance & Audit Trail

This document defines how feature flag changes are audited, governed, and reviewed for compliance and incident response.

## What counts as a feature flag change

The following actions are audited:

- **Create**: a new feature flag definition or explicit override is added.
- **Enable / disable**: toggling a flag on or off.
- **Rollout change**: percentage adjustments (currently captured as `0%` or `100%` because the org-level flags are boolean).
- **Targeting rule changes**: any change to targeting rules summary.
- **Delete / retire**: removal of an override or retirement in automation flows.
- **Activate / expire**: lifecycle state transitions for a flag definition.
- **Override**: policy-approved changes to expired/retired flags.

Flag evaluation (reads) is **not** audited. Audit logging only applies to mutation paths.

## Audit record fields

Each feature flag change writes a single immutable audit record containing:

- **When**: `occurred_at` is server-generated to preserve ordering.
- **Who**: `actor_type`, `actor_id`, `actor_role`, `auth_method`, `actor_source`.
- **Where**: `org_id` for org-scoped flags.
- **What**: `flag_key`, `action`, `before_state`, `after_state`.
- **How much / why**: `rollout_context` includes `enabled`, `percentage`, `targeting_rules`, and optional `reason`.
- **Traceability**: `request_id` links changes to requests and logs.

Audit records are immutable (no update/delete) at the database level.

## Lifecycle stages

1. **Create**: a flag definition is created with required metadata.
2. **Activate**: the definition moves to `active` for rollout.
3. **Rollout**: org-level overrides enable/disable the flag with context.
4. **Expire**: the flag reaches `expires_at` or is explicitly expired.
5. **Retire**: the flag is fully retired and overrides are removed.

## Metadata requirements

Every feature flag definition includes:

- **Owner**: accountable team or individual.
- **Purpose**: business or technical justification.
- **Created at**: server-generated timestamp.
- **Expires at**: required for new flags; legacy flags may be null until backfilled.
- **Lifecycle state**: `draft`, `active`, `expired`, or `retired`.

New flags **cannot** be created without `owner`, `purpose`, and `expires_at`.

## Expiration policy (deterministic behavior)

- Expired or retired flags **auto-disable** during evaluation.
- Expired or retired flags **cannot** be modified or rolled out without an explicit override.
- Overrides require `override_reason` and are audited as `override`.

## Policy gates

- `expires_at` must be within the configured horizon (default: 90 days) unless an override is supplied.
- Any change to expired/retired flags requires an override and emits an audit entry.

## Admin API endpoints

- `GET /v1/admin/settings/feature-flags` lists flag definitions and lifecycle metadata.
  - Filter by `state=expired|retired|draft|active`.
  - `expiring_within_days=7|14|30` lists flags expiring soon.
- `POST /v1/admin/settings/feature-flags` creates a new flag definition (metadata required).
- `PATCH /v1/admin/settings/feature-flags/{flag_key}` updates metadata or lifecycle state.
- `PATCH /v1/admin/settings/features` updates org overrides and enforces lifecycle gates.

## Covered mutation paths

The centralized audit service is enforced for all feature flag mutation paths, including:

- Admin UI and API updates (`PATCH /v1/admin/settings/features`)
- API clients calling the feature module service directly
- Automation or scripts (use the same service with `actor_type = system/automation`)
- Retirement flows removing explicit overrides

Every mutation must pass through the feature flag service so the audit write cannot be bypassed.

## Reviewing audit history

Admins can query audit history via:

```
GET /v1/admin/settings/audit/feature-flags?flag_key=module.schedule&start=2026-01-01T00:00:00Z&end=2026-01-31T00:00:00Z&limit=50&offset=0
```

Filters:

- `flag_key`: specific flag key
- `org_id`: org-scoped filtering
- `start` / `end`: ISO timestamps

Results are paginated; use `next_offset` to page forward.

## Redaction policy

Targeting rules are stored only as sanitized summaries. User identifiers and secrets are redacted before storage.

## Failure policy (fail-closed)

If the audit write fails, the feature flag change **fails**. This prevents undocumented rollouts and ensures incident traceability.
