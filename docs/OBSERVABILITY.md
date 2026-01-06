# Observability

The API exposes Prometheus-compatible metrics at `/metrics` when `METRICS_ENABLED=true`. In production the endpoint requires the shared bearer token configured via `METRICS_TOKEN` to avoid exposing data publicly.

## Key HTTP metrics
- `http_requests_total{method, path, status_class}`: request volume by route and coarse status.
- `http_request_latency_seconds{method, path, status_class}`: latency histogram for p50/p95 via bucket aggregation.
- `http_5xx_total{method, path}`: server error counts to watch error spikes.

Suggested alerts:
- 5xx error rate: alert when the ratio of `http_5xx_total` to `http_requests_total` for a route exceeds a small threshold over 5–10 minutes.
- Latency: alert when the p95 or p99 of `http_request_latency_seconds` for critical routes rises above the SLO.

## Jobs and queues
- `outbox_queue_messages{status}` and `dlq_depth_snapshot{kind,stage}` track queue depth and replay snapshots.
- `job_runner_up{job}`, `job_last_heartbeat_timestamp{job}`, and `job_last_success_timestamp{job}` verify runner liveness and freshness.
- `job_errors_total{job,reason}` indicates failure streaks.

Suggested alerts:
- Jobs: alert when `job_runner_up` is 0 or when `job_last_success_timestamp` is stale beyond the expected cadence.
- Queues: alert when `outbox_queue_messages{status="dead"}` grows or when DLQ depths increase unexpectedly.

## Safe labeling
Metrics use HTTP method, templated route path (no concrete IDs), and coarse status class labels to avoid sensitive data exposure.
