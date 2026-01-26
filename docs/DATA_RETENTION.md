# Data Retention Enforcement

This document defines the centralized data retention framework that enforces retention policies via scheduled jobs. The framework is deterministic, auditable, and idempotent.

## Categories & Defaults

| Category | Description | Default retention | Config key | Enforcement notes |
| --- | --- | --- | --- | --- |
| application logs | Request, error, and operational logs stored in the database (reason logs). **Excludes audit logs and security logs with extended retention.** | 30 days | `retention_application_log_days` | Purged daily via log retention job. |
| analytics events | Raw, user-level analytics event logs (timestamped). | 90 days | `retention_analytics_event_days` | Purged daily via analytics retention job. Aggregated metrics are retained. |
| soft-deleted entities | Records marked as deleted (soft delete). | 30 days | `retention_soft_deleted_days` | Purged weekly via data retention job. |
| audit logs | Administrative/configuration audit logs. | 7 years (2555 days) | `retention_audit_log_days` | **Reference-only in this framework.** Purge enforcement remains in the dedicated audit retention job/policy. |

Retention policies are centrally defined in code (`app.settings`) and used by the retention engine.

## Scheduled Jobs

| Job | Schedule | Categories |
| --- | --- | --- |
| `log-retention-daily` | Daily | application logs |
| `data-retention-daily` | Daily | analytics events (raw only, legacy alias) |
| `analytics-retention-daily` | Daily | analytics events (raw only) |
| `data-retention-weekly` | Weekly | soft-deleted entities, audit logs (reference-only) |

Schedulers should run these jobs daily/weekly. The jobs call the centralized retention service and do not delete data directly.

## Auditability & Metrics

Each retention run emits:
- A system audit log entry with category, retention days, cutoff, and deleted counts.
- A Prometheus counter: `retention_records_deleted_total{category}`.

Log retention runs additionally emit:
- A system audit entry with `category=logs` and `count`.
- A Prometheus counter: `logs_purged_total`.

Analytics retention runs additionally emit:
- A system audit entry with `category=analytics` and the data classification.
- A Prometheus counter: `analytics_events_purged_total`.

## Failure & Retry Behavior

Log retention deletes in small batches to avoid long-running locks. Each batch is committed independently and retried up to `log_retention_batch_retries` with exponential backoff (starting at `log_retention_batch_retry_delay_seconds`). If a batch still fails, the job aborts and can be retried safely by the scheduler at the next interval.

Data retention runs are transactional per category. If a category fails, the transaction is rolled back so no partial deletion is committed. The job fails loudly and can be retried by the scheduler at the next interval.

## Idempotency

Retention enforcement is idempotent; re-running a category after successful deletion will delete zero additional records once the dataset is compliant.

## Analytics Classification & Privacy Guarantees

Analytics data is classified into:
- **Raw events**: User-level, timestamped logs stored in `event_logs` (may include UTM fields, lead/booking references).
- **Aggregated metrics**: De-identified rollups (counts, histograms, conversion rates) computed for dashboards such as
  conversion funnels, geo heatmaps, marketing lead-source analytics, NPS distributions, and competitor benchmarks.

Raw analytics events are purged after `retention_analytics_event_days`. Aggregated metrics are retained because they do not
contain user-identifiable details. This ensures no PII remains in analytics event logs beyond retention while preserving
privacy-safe reporting.
