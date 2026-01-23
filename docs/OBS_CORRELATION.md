# Observability: Log ↔ Trace Correlation

This repo correlates structured JSON logs with distributed traces by injecting `trace_id`/`span_id` into every log event and by adding a Grafana Loki derived field that links directly to Tempo traces.

## How it works

- The logging formatter reads the current OpenTelemetry span context and injects `trace_id` and `span_id` into JSON logs.
- The request middleware attaches `request_id` to the active span for easier trace search.
- Grafana Loki is provisioned with a derived field that extracts `trace_id` and links to the Tempo datasource.

## Example log payload

```json
{
  "timestamp": "2024-01-01T12:34:56.789Z",
  "level": "INFO",
  "message": "request",
  "logger": "app.request",
  "trace_id": "4e0f4c2bd2b6b47c8a54d61dc1a0a5d5",
  "span_id": "b1f5c2d3e4a5b678",
  "request_id": "7b4dc0a4-32ef-4d2f-a3d0-0d2c1e5fbad7",
  "method": "GET",
  "path": "/api/health",
  "status_code": 200,
  "latency_ms": 12
}
```

## Workflow: logs → traces in Grafana

1. Open **Explore** → **Loki**.
2. Run a query such as:
   ```
   {app="api"} |= "trace_id"
   ```
3. Click the **trace_id** derived field in a log line to open the corresponding trace in **Tempo**.

## Workflow: traces → logs

1. Open a trace in **Tempo**.
2. Use the `request_id` attribute (now attached to spans) to search logs:
   ```
   {app="api"} |= "request_id=\"<request-id>\""
   ```

## Verification

- Confirm log entries include `trace_id` and `span_id`.
- Validate that clicking `trace_id` in the Loki log details opens the Tempo trace.
