# DLQ Operations Runbook

This runbook walks operators through inspecting and safely replaying dead letter queue (DLQ) items for both outbox and export pipelines. All endpoints are admin-only and must be called with Basic Auth credentials and an org-scoped `Idempotency-Key` header for any replay action.

## 1) Check that the DLQ is empty
- Endpoint: `GET /v1/admin/queue/dlq?kind=all&limit=1`
- Expectation: `total`, `outbox_dead_count`, and `export_dead_count` should be `0`.
- Command:
  ```bash
  curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \
    "$API_BASE/v1/admin/queue/dlq?kind=all&limit=1"
  ```
- If counts are non-zero, proceed to listing to identify items. Treat any non-zero depth as an operational smell.

## 2) List DLQ items (with redaction)
- Endpoint: `GET /v1/admin/queue/dlq?kind=all&limit=50&offset=0`
- Response provides `payload_summary` fields with PII/token redaction for quick triage.
- Command:
  ```bash
  curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \
    "$API_BASE/v1/admin/queue/dlq?kind=all&limit=50&offset=0"
  ```
- Use `kind=outbox` or `kind=export` to focus on a single queue. Never log raw payloads; rely on the summaries.

## 3) Replay a single item (idempotent)
- Outbox item: `POST /v1/admin/outbox/{event_id}/replay`
- Export item: `POST /v1/admin/export-dead-letter/{event_id}/replay`
- Headers: include `Idempotency-Key` and optional `X-Correlation-ID` for traceability.
- Example:
  ```bash
  curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \
    -H "Idempotency-Key: dlq-replay-$EVENT_ID" \
    -H "X-Correlation-ID: dlq-$EVENT_ID" \
    -X POST "$API_BASE/v1/admin/outbox/$EVENT_ID/replay"
  ```
- Dry-run: not available; confirm downstream target health before replaying. Replays reset attempts and rely on existing dedupe/idempotency logic to avoid double-processing.

## 4) Replay a batch with a rate limit and explicit confirmation
- Endpoint: `POST /v1/admin/queue/dlq/replay?confirm=true&limit=10`
- Requirements:
  - `confirm=true` query flag is mandatory to avoid accidental bulk processing.
  - Action-level rate limiting applies per org; repeated calls may return HTTP 429.
  - Provide `Idempotency-Key` and optional `X-Correlation-ID` headers.
- Example:
  ```bash
  curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \
    -H "Idempotency-Key: dlq-batch-$(date +%s)" \
    -H "X-Correlation-ID: dlq-batch-$(date +%s)" \
    -X POST "$API_BASE/v1/admin/queue/dlq/replay?confirm=true&limit=10"
  ```
- Batch replay uses the same guarded replay logic as single-item endpoints (idempotency, org scoping, and audit logging) and stops once the limit is reached or failures hit configured streak limits.

## Operational safety notes
- Validate downstream services (email provider, webhook target, export destination) before replaying to avoid repeated DLQ growth.
- Use the smallest viable `limit` when batch replaying; prefer single replays when investigating incidents.
- Audit logs capture who initiated replays along with correlation IDs; keep these IDs in incident timelines.
