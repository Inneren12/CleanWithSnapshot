# Quarterly Access Review

This guide documents the quarterly access review process, how to run the built-in snapshot tooling, and how to interpret anomalies.

## Overview
The access review snapshot provides a deterministic, multi-tenant report of admin users, roles, permissions, MFA status, and recent privileged activity. The report is generated as **JSON** and **Markdown**, and includes a SHA-256 artifact hash for integrity verification.

## How to run the snapshot

### Org-scoped review (default)
```bash
python backend/scripts/access_review_snapshot.py \
  --scope org \
  --org-id <org_uuid> \
  --as-of 2024-03-31T23:59:59Z \
  --output-dir ./access-review
```

### Global review (system admins only)
```bash
python backend/scripts/access_review_snapshot.py \
  --scope global \
  --as-of 2024-03-31T23:59:59Z \
  --output-dir ./access-review
```

### About `--as-of`
The `--as-of` timestamp defines the evidence cutoff for the snapshot. Only activity **at or before** the timestamp
is included. Lookback windows (inactive thresholds, break-glass, role-change checks) are computed as
`[as_of - lookback_days, as_of]`, preventing evidence drift when you regenerate the report later with the same
`--as-of` value.

### Optional: Persist run metadata
```bash
python backend/scripts/access_review_snapshot.py \
  --scope org \
  --org-id <org_uuid> \
  --as-of 2024-03-31T23:59:59Z \
  --output-dir ./access-review \
  --store-run \
  --generated-by "security-reviewer@example.com"
```

This writes an `access_review_runs` record that includes `run_at`, `scope`, `generated_by`, and the artifact hash. Use it as an immutable pointer to the stored artifact.

## Anomaly rule configuration
By default, the tooling uses conservative thresholds. You can override the defaults via a JSON file or CLI flags.

Example JSON config:
```json
{
  "inactive_days": 90,
  "break_glass_lookback_days": 90,
  "role_change_lookback_days": 90,
  "owner_admin_allowlist": [
    "owner@example.com",
    "admin@example.com"
  ],
  "owner_admin_allowlist_by_org": {
    "00000000-0000-0000-0000-000000000001": ["owner@example.com"]
  },
  "mfa_required": true,
  "mfa_required_roles": ["owner", "admin"]
}
```

CLI overrides:
```bash
python backend/scripts/access_review_snapshot.py \
  --scope org \
  --org-id <org_uuid> \
  --inactive-days 60 \
  --break-glass-days 120 \
  --role-change-days 120
```

## Interpreting anomalies
The snapshot flags the following anomalies:

- **inactive_admin_account**: Admin account inactive beyond the configured threshold.
- **mfa_required_not_enabled**: MFA is required for the role, but the user has not enabled it.
- **owner_admin_role_unexpected**: Owner/Admin role assigned without being present in the allowlist.
- **break_glass_recent_use**: Break-glass sessions used in the lookback window.
- **recent_role_change**: Role changes detected via admin audit logs in the lookback window.

Each anomaly entry includes `rule`, `severity`, `org_id`, and (when applicable) `user_id` and `email`.

## Quarterly review workflow

1. **Generate snapshots**
   - Run org-scoped snapshots for each tenant, or a global snapshot if you are a system admin.
   - Use a fixed `--as-of` timestamp to make the output reproducible.

2. **Store artifacts**
   - Store the JSON and Markdown outputs in a controlled, ops-managed location.
   - Record the `artifact_hash` from the report alongside your storage record or ticket.
   - Optionally store run metadata in the `access_review_runs` table using `--store-run`.

3. **Review anomalies**
   - Investigate each anomaly and document the resolution (e.g., deactivate stale accounts, enforce MFA, validate owner/admin assignments).

4. **Sign-off**
   - Require sign-off from Security/Governance and the Org Owner (or delegated admin).
   - Attach the artifacts and anomaly resolution notes to the quarterly review record.

## Output guarantees
- No secrets (passwords, tokens, MFA secrets) are included in the snapshot.
- Output ordering is deterministic for the same inputs and `--as-of` timestamp.
- Reports include both JSON (machine-readable) and Markdown (review-friendly) formats.
