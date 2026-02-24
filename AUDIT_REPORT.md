# Observability, Logging & APM Audit Report

## 1. Executive Summary

This audit reviewed the codebase for observability gaps, focusing on distributed tracing, structured logging, and metrics instrumentation. The system generally follows good practices (structured logging, OTel middleware), but critical gaps exist in background job tracing and external context propagation.

## 2. Findings

### [P0] Missing Distributed Tracing in Background Jobs
- **Severity**: Critical
- **File**: `backend/app/jobs/run.py`
- **Impact**: All database queries, external API calls, and logic within background jobs (email sending, data export, retention) run without an active OpenTelemetry Span. Logs lack a consistent `trace_id`. Failures cannot be traced end-to-end.
- **Fix**: Initialize a tracer span in `_run_job` and set `job.name` attribute.

### [P1] Missing Trace Context Propagation in Outbox Webhooks
- **Severity**: High
- **File**: `backend/app/domain/outbox/service.py`
- **Impact**: Outgoing webhooks sent via `httpx` do not include W3C Trace Context headers. Downstream consumers cannot correlate the webhook with the source event.
- **Fix**: Use `opentelemetry.propagate.inject` to add headers to the webhook request.

### [P2] Database Connection Pool Metrics Absent
- **Severity**: Medium
- **File**: `backend/app/infra/db.py`
- **Impact**: No visibility into connection pool saturation (active/idle connections, wait times). Blind spot for database capacity planning.
- **Fix**: Expose SQLAlchemy pool statistics via Prometheus Gauges.

### [P2] External Client Trace Correlation Gaps
- **Severity**: Medium
- **Files**: `backend/app/infra/stripe_client.py`, `backend/app/infra/email.py`
- **Impact**: Requests to Stripe, SendGrid, and Twilio do not include the internal `trace_id` (e.g., in metadata or headers). This makes it difficult to link provider webhooks/logs back to the specific internal request.
- **Fix**: Inject `trace_id` into request metadata/headers where supported.

### [P2] Transient Log Context in Jobs
- **Severity**: Medium
- **File**: `backend/app/jobs/run.py`
- **Impact**: Log context is cleared after each job run but not re-initialized with a consistent Job/Trace ID until specific points. Interleaved logs are hard to filter.
- **Fix**: Set `job_id` or `trace_id` in `update_log_context` at the start of `_run_job`.

## 3. Recommendations

1.  **Immediate**: Wrap `_run_job` in a tracer span to enable visibility into background processes.
2.  **Immediate**: Update `OutboxAdapters` to inject trace headers for webhooks.
3.  **Short-term**: Implement a metrics collector for SQLAlchemy pool stats.
4.  **Long-term**: Standardize external client instrumentation to include `trace_id` in metadata for all providers.
