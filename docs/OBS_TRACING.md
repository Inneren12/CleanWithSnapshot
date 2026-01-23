# OpenTelemetry tracing (API + jobs)

## Overview
- Traces are exported via OTLP/gRPC to Tempo.
- Spans cover inbound HTTP (FastAPI), database queries (SQLAlchemy), and outbound HTTP (httpx).
- Query strings and SQL statements are intentionally excluded from span attributes to reduce PII exposure.

## Configuration
The following environment variables are required (see `docker-compose.yml` / `backend/docker-compose.yml`):
- `OTEL_EXPORTER_OTLP_ENDPOINT` (e.g. `http://tempo:4317`)
- `OTEL_SERVICE_NAME` (`api` or `jobs`)
- `DEPLOYMENT_ENV` (`local` / `prod`)

Optional:
- `GIT_SHA` (used for `service.version`), otherwise a git SHA is resolved when available.

## Validation steps
1. Start the stack (including Tempo/Grafana if using observability compose):
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
   ```
2. Generate a request:
   ```bash
   curl -fsS http://localhost:8000/healthz
   ```
3. Open Grafana → **Explore** → **Tempo** and search for traces:
   - Query by service name (`api` or `jobs`).
   - Confirm at least one HTTP span exists.
4. Trigger a request or job that performs a DB query:
   - Confirm DB spans appear (SQL statements are not recorded).

## Notes on PII
Span attributes exclude SQL statements and query strings by design. Avoid adding request/response bodies, headers, or user identifiers to span attributes to keep traces free of secrets and PII.
