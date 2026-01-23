# Jobs & Outbox Metrics

This service exposes Prometheus metrics at `/metrics` when `METRICS_ENABLED=true`. The following
series focus on job execution and outbox delivery health while keeping labels low-cardinality.

## Jobs runner metrics

| Metric | Type | Labels | Description |
| --- | --- | --- | --- |
| `jobs_last_success_timestamp` | Gauge | `job` | Unix timestamp of the most recent successful run for a job. |
| `jobs_run_total` | Counter | `job`, `result` | Job run outcomes (`success` or `error`). |
| `jobs_duration_seconds` | Histogram | `job` | Job run duration in seconds. |

## Outbox pipeline metrics

| Metric | Type | Labels | Description |
| --- | --- | --- | --- |
| `outbox_pending_total` | Gauge | `type` | Pending outbox messages by type (e.g., `email`, `webhook`, `export`). |
| `outbox_deliver_total` | Counter | `type`, `result` | Outbox delivery attempts by type and result (`success` or `error`). |
| `outbox_lag_seconds` | Gauge | `type` | Age in seconds of the oldest pending outbox event by type. |

## Notes

- Labels intentionally exclude org/user identifiers to keep cardinality low.
- `outbox_lag_seconds` is `0` when no pending events exist for a given type.
