# Access Review Policy (PR-GOV-11 v2)

## Scope
This policy governs quarterly access reviews for:
- **Admin users and roles** (Owner/Admin and any privileged roles).
- **Break-glass access** and use within the review window.
- **Role/permission changes** captured by admin audit logs.

The policy uses the built-in access review tooling and audit endpoints described in:
- `docs/ACCESS_REVIEW.md` (snapshot + evidence bundle tooling).
- `docs/ADMIN_ACTION_AUDIT.md` and `docs/GOVERNANCE_AUDIT.md` (audit evidence sources).

## Quarterly schedule
- **Frequency:** Once per calendar quarter.
- **Cutoff:** Use a fixed `--as-of` timestamp at **23:59:59Z** on the last day of the quarter.
- **Due date:** Evidence package and sign-off must be completed **within 10 business days** after quarter end.

## Roles and responsibilities
- **Access Review Owner (Security):**
  - Owns the quarterly program and final sign-off.
  - Ensures the review is completed on schedule.
  - Approves any exceptions/waivers.
- **Operations Reviewer (Ops):**
  - Runs the snapshot and evidence bundle tooling.
  - Verifies checksum integrity and archives evidence.
  - Implements remediation actions assigned to Ops.
- **Org Owner Approver (Owner):**
  - Reviews org-specific access anomalies.
  - Confirms expected role assignments and business justification.
  - Signs off on remediation completion for their org.

**Approvals required:** Security + Ops + Org Owner (or delegated admin) for each reviewed org (or for the global report if using global scope).

## Required tooling and evidence artifacts
All evidence must be generated using the built-in scripts and retained as a complete package.

1) **Snapshot generation** (`backend/scripts/access_review_snapshot.py`)
   - Use org scope per tenant, or global scope for system admins.
   - Always set `--as-of` to the quarter cutoff.

2) **Evidence bundle** (`backend/scripts/access_review_report.py`)
   - Use the snapshot JSON as input.
   - Use a fixed `--generated-at` timestamp and `--signed-by` value.

3) **Required evidence artifacts** (per org or global scope):
   - `snapshot.json`
   - `report.md`
   - `audit_extract.json` (role-change events in lookback window)
   - `metadata.json`
   - `checksums.txt` (including `manifest_sha256`)
   - Optional: `access_review_runs` record if `--store-run` is used

4) **Integrity verification**
   - Validate checksums (`sha256sum -c checksums.txt`).
   - Compare the manifest hash to `manifest_sha256`.

## Anomalies that require action
The review **must** investigate and resolve the following anomalies surfaced by the snapshot:
- `inactive_admin_account`
- `mfa_required_not_enabled`
- `owner_admin_role_unexpected`
- `break_glass_recent_use`
- `recent_role_change`

Resolution must be recorded in the quarterly review ticket, including the action taken and the approving role.

## Severity mapping and remediation SLAs
Apply the SLA based on the **highest-severity** anomaly affecting a user or org.

| Severity | Anomalies (default mapping) | Remediation SLA |
| --- | --- | --- |
| **Critical** | `break_glass_recent_use`, `owner_admin_role_unexpected` | **Same day** (by 23:59 local time) |
| **High** | `mfa_required_not_enabled`, `recent_role_change` | **7 days** |
| **Medium** | `inactive_admin_account` | **30 days** |

If the snapshot reports a higher severity for any anomaly, the higher severity **overrides** the defaults.

## Remediation requirements
- **Break-glass use:** Confirm incident ticket, verify business justification, and rotate credentials if unauthorized.
- **Unexpected Owner/Admin role:** Remove role or update allowlist with documented approval.
- **MFA not enabled:** Enforce MFA or suspend admin access until enabled.
- **Recent role change:** Validate change authorization using admin audit logs.
- **Inactive admin:** Deactivate account or document required access with owner approval.

All remediation actions must reference evidence from the snapshot and audit logs.

## Evidence retention
- **Retention period:** Minimum **7 years** for access review evidence packages.
- **Storage location:** Ops-managed, access-controlled archive (e.g., compliance storage bucket or `/opt/cleaning/evidence/access-reviews/`).
- **Tamper evidence:** Preserve the full bundle directory and the `manifest_sha256` value.
- **Legal holds:** If a legal hold exists, evidence retention is extended until the hold is released.

## Escalation path
1) **Ops Reviewer** triages and proposes remediation.
2) **Access Review Owner (Security)** approves remediation or escalates.
3) **Org Owner Approver** validates business justification for org-specific access.
4) **Executive escalation** if SLA breach or unresolved critical findings.

## Exceptions and waiver process
- Exceptions are **time-bound** and require **Security** approval.
- A waiver must include:
  - Scope (org/user/anomaly)
  - Business justification
  - Compensating controls
  - Expiration date (maximum 30 days for critical/high; 90 days for medium)
- Waivers must be stored with the quarterly evidence package and re-evaluated at the next review.
