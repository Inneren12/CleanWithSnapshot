# Data Retention Enforcement

This document defines the centralized data retention framework that enforces retention policies via scheduled jobs. The framework is deterministic, auditable, and idempotent.

## Categories & Defaults

| Category | Description | Default retention | Config key | Enforcement notes |
| --- | --- | --- | --- | --- |
| application logs | Operational application logs stored in the database (reason logs). | 30 days | `retention_application_log_days` | Purged daily via data retention job. |
| analytics events | Analytics event logs used for reporting. | 90 days | `retention_analytics_event_days` | Purged daily via data retention job. |
| soft-deleted entities | Records marked as deleted (soft delete). | 30 days | `retention_soft_deleted_days` | Purged weekly via data retention job. |
| audit logs | Administrative/configuration audit logs. | 7 years (2555 days) | `retention_audit_log_days` | **Reference-only in this framework.** Purge enforcement remains in the dedicated audit retention job/policy. |

Retention policies are centrally defined in code (`app.settings`) and used by the retention engine.

## Scheduled Jobs

| Job | Schedule | Categories |
| --- | --- | --- |
| `data-retention-daily` | Daily | application logs, analytics events |
| `data-retention-weekly` | Weekly | soft-deleted entities, audit logs (reference-only) |

Schedulers should run these jobs daily/weekly. The jobs call the centralized retention service and do not delete data directly.

## Auditability & Metrics

Each retention run emits:
- A system audit log entry with category, retention days, cutoff, and deleted counts.
- A Prometheus counter: `retention_records_deleted_total{category}`.

## Failure & Retry Behavior

Retention runs are transactional per category. If a category fails, the transaction is rolled back so no partial deletion is committed. The job fails loudly and can be retried by the scheduler at the next interval.

## Idempotency

Retention enforcement is idempotent; re-running a category after successful deletion will delete zero additional records once the dataset is compliant.
