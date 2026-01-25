# Audit Retention Policy (PR-GOV-05 v2)

## Purpose
This policy defines the **automated, immutable audit log retention controls** for CleanWithSnapshot,
including legal holds and verified purge behavior. The retention system is designed to support SOC-style
requirements for evidence preservation, tamper resistance, and controlled disposal of audit data.

## Scope
The policy applies to server-side audit logs in the following categories:

- **Admin action audits** (`admin_audit_logs`)
- **Configuration audits** (`config_audit_logs`)
- **Feature flag audits** (`feature_flag_audit_logs`)
- **Integration audits** (`integration_audit_logs`)

These logs are immutable during retention and can only be purged by the system retention job after the
retention period expires and no legal hold applies.

## Retention periods (default, configurable)
Retention values are defined in application settings and can be adjusted for compliance needs:

| Audit category | Setting | Default |
| --- | --- | --- |
| Admin action audits | `audit_retention_admin_days` | 3 years (1095 days) |
| Config/feature/integration audits | `audit_retention_config_days` | 7 years (2555 days) |

Defaults are conservative to support compliance and investigation needs.

## Immutability guarantees
Audit logs are immutable during retention:

- ORM safeguards raise errors on update/delete attempts.
- Database triggers block `UPDATE`/`DELETE` for audit tables.
- Purge deletes are only allowed when the retention job sets a protected DB session flag.

## Legal hold
Legal holds override retention-based deletion:

- Holds can be scoped by **org**, **time range**, and **investigation ID**.
- A hold blocks deletion of any audit record within its scope, regardless of age.
- Holds are stored in `audit_legal_holds` and are themselves non-deletable.

## Automated purge job
The scheduled job `audit-retention`:

1. Scans audit tables in batches.
2. Validates record age against retention policy.
3. Skips records under active legal hold.
4. Deletes eligible records using a system-only purge flag.
5. Records an immutable audit entry in `audit_purge_events`.

### Dry-run mode
Operators can enable dry-run behavior to verify eligibility without deletion:

- `audit_retention_dry_run = true`
- The job records a purge event with counts but performs no deletes.

## Auditability of purge operations
All purge runs generate an immutable record with:

- **Actor**: `system` / `audit-retention-job`
- **Retention policy snapshot**
- **Per-table counts** (eligible, purged, held)
- **Run timestamps**

This provides evidence of controlled, auditable disposal.

## Metrics
The retention system exports metrics for monitoring:

- `audit_records_purged_total`
- `audit_records_on_legal_hold_total`

## Compliance justification (SOC-style)
The controls defined here provide:

- **Integrity**: Audit logs are tamper-resistant and immutable during retention.
- **Availability**: Records are retained for a defined, conservative period.
- **Accountability**: All purge actions are themselves audited.
- **Legal hold enforcement**: Deletion is blocked when legal holds apply.
- **Automation**: Purge behavior is enforced without manual intervention.
