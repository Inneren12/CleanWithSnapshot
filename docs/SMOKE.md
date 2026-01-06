# Smoke Test Pack

This document provides a comprehensive set of smoke tests for the CleanWithSnapshot application. These tests verify that critical system components are operational after deployment.

## Environment Variables

Set these variables before running the smoke tests:

```bash
export API_BASE_URL="${API_BASE_URL:-https://api.panidobro.com}"
export WEB_BASE_URL="${WEB_BASE_URL:-https://panidobro.com}"
export ADMIN_USER="${ADMIN_USER:-admin}"
export ADMIN_PASS="${ADMIN_PASS:-secret}"
```

For local testing:
```bash
export API_BASE_URL="http://localhost:8000"
export WEB_BASE_URL="http://localhost:3000"
```

## 1. Health & Readiness Checks

### 1.1 API Liveness (GET)
Tests basic API availability.

```bash
curl -fsS "$API_BASE_URL/healthz"
```

**Expected:** `{"status":"ok"}` with HTTP 200

### 1.2 API Liveness (HEAD)
Tests liveness without response body.

```bash
curl -fsS -I "$API_BASE_URL/healthz" | head -1
```

**Expected:** `HTTP/2 200` or `HTTP/1.1 200`

### 1.3 API Readiness
Tests database connectivity, migration status, and job heartbeat.

```bash
curl -fsS "$API_BASE_URL/readyz" | jq .
```

**Expected:** HTTP 200 with structured checks when all systems are healthy:
```json
{
  "ok": true,
  "checks": [
    {
      "name": "db",
      "ok": true,
      "ms": 5.1,
      "detail": {"message": "database reachable"}
    },
    {
      "name": "migrations",
      "ok": true,
      "ms": 12.3,
      "detail": {
        "message": "migrations in sync",
        "migrations_current": true,
        "current_version": "abc123",
        "expected_head": "abc123",
        "migrations_check": "ok"
      }
    },
    {
      "name": "jobs",
      "ok": true,
      "ms": 8.5,
      "detail": {
        "enabled": true,
        "last_heartbeat": "2026-01-06T12:00:00Z",
        "runner_id": "jobs-runner",
        "age_seconds": 45.2,
        "threshold_seconds": 180
      }
    }
  ]
}
```

**Failure Scenarios:**

The endpoint returns **HTTP 503** when any check fails:

- **DB check fails** when:
  - Database is unreachable or connection times out (>2s)
  - Database session factory not configured
  - Example: `{"name": "db", "ok": false, "detail": {"message": "database check timed out", "timeout_seconds": 2.0}}`

- **Migrations check fails** when:
  - Current database revision doesn't match expected alembic head
  - Migration files not found (returns ok with skip_reason in packaged deployments)
  - Example: `{"name": "migrations", "ok": false, "detail": {"message": "migrations pending", "current_version": "abc123", "expected_head": "def456"}}`

- **Jobs check fails** when:
  - Jobs enabled but no heartbeat record exists
  - Heartbeat is stale (age > threshold, default 180s)
  - Jobs runner hasn't updated heartbeat recently
  - Example: `{"name": "jobs", "ok": false, "detail": {"enabled": true, "message": "job heartbeat stale", "age_seconds": 195.5, "threshold_seconds": 180}}`

**Notes:**
- Each check includes timing in milliseconds (`ms` field) for performance monitoring
- The `detail` object provides diagnostic information for each check
- Jobs check is only enforced when `JOBS_ENABLED=true` or `JOB_HEARTBEAT_REQUIRED=true`
- Migrations check gracefully skips when alembic files are unavailable (packaged deployments)

### 1.4 Backup Health Check
Tests backup freshness (last successful backup within 26 hours).

```bash
curl -fsS "$API_BASE_URL/healthz/backup" | jq .
```

**Expected:** HTTP 200 with:
```json
{
  "backup_ok": true,
  "last_backup_utc": "2026-01-06T12:00:00Z",
  "age_seconds": 3600
}
```

**Note:** Returns HTTP 503 if backup is too old or missing.

## 2. Web Application

### 2.1 Web Root
Tests Next.js web application availability.

```bash
curl -fsS "$WEB_BASE_URL/" -o /dev/null -w "%{http_code}\n"
```

**Expected:** HTTP 200

### 2.2 Web Assets
Tests static asset serving.

```bash
curl -fsS -I "$WEB_BASE_URL/_next/static" | head -1
```

**Expected:** HTTP 200 or HTTP 404 (acceptable if no specific asset)

## 3. API Core Endpoints

### 3.1 Estimate Pricing
Tests pricing calculation engine.

```bash
curl -fsS -X POST "$API_BASE_URL/v1/estimate" \
  -H "Content-Type: application/json" \
  -d '{
    "beds": 2,
    "baths": 1.5,
    "cleaning_type": "standard",
    "frequency": "weekly",
    "add_ons": {}
  }' | jq .
```

**Expected:** HTTP 200 with pricing data:
```json
{
  "pricing_config_id": "economy",
  "team_size": 2,
  "total_before_tax": 150.00
}
```

### 3.2 OpenAPI Docs
Tests API documentation availability.

```bash
curl -fsS "$API_BASE_URL/docs" -o /dev/null -w "%{http_code}\n"
```

**Expected:** HTTP 200

### 3.3 OpenAPI Schema
Tests OpenAPI schema generation.

```bash
curl -fsS "$API_BASE_URL/openapi.json" | jq '.info.title'
```

**Expected:** HTTP 200 with `"Cleaning Economy Bot"`

### 3.4 Analytics Funnel
Validates conversion counts and payment rollups.

```bash
curl -fsS \
  -u "$ADMIN_USER:$ADMIN_PASS" \
  -H "X-Test-Org: ${ORG_ID:-$DEFAULT_ORG_ID}" \
  "$API_BASE_URL/v1/admin/analytics/funnel?from=$(date -Idate)" | jq .counts
```

**Expected:** HTTP 200 with counts containing `leads`, `bookings`, `completed`, and `paid`.

## 4. Authentication & Authorization

### 4.1 Admin Auth (Basic)
Tests admin basic authentication.

```bash
curl -fsS -u "$ADMIN_USER:$ADMIN_PASS" \
  "$API_BASE_URL/v1/admin/profile" | jq .
```

**Expected:** HTTP 200 with admin profile or credentials

### 4.2 Unauthorized Access
Tests auth rejection.

```bash
curl -fsS -w "%{http_code}\n" -o /dev/null \
  "$API_BASE_URL/v1/admin/profile"
```

**Expected:** HTTP 401

## 5. Stripe Webhook Endpoint

### 5.1 Webhook Availability
Tests that webhook endpoint is reachable (will reject without valid signature).

```bash
curl -fsS -X POST "$API_BASE_URL/v1/payments/stripe/webhook" \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: t=invalid" \
  -d '{}' -w "%{http_code}\n" -o /dev/null
```

**Expected:** HTTP 400 or HTTP 503 (invalid signature or webhook disabled)

**Note:** HTTP 503 means `STRIPE_WEBHOOK_SECRET` is not configured.

### 5.2 Legacy Webhook Route
Tests legacy webhook endpoint.

```bash
curl -fsS -X POST "$API_BASE_URL/stripe/webhook" \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: t=invalid" \
  -d '{}' -w "%{http_code}\n" -o /dev/null
```

**Expected:** HTTP 400 or HTTP 503

## 6. Rate Limiting

### 6.1 Rate Limit Check
Tests that rate limiting is active (may need multiple requests).

```bash
for i in {1..100}; do
  curl -fsS "$API_BASE_URL/healthz" -o /dev/null -w "%{http_code}\n"
done | grep -c "429" || echo "No rate limits hit (expected in normal operation)"
```

**Expected:** Should complete without errors. HTTP 429 indicates rate limiting is working (but shouldn't happen in normal smoke testing).

## 7. Metrics Endpoint (if enabled)

### 7.1 Metrics Export
Tests metrics endpoint (requires METRICS_TOKEN).

```bash
# Only if METRICS_ENABLED=true
curl -fsS -H "Authorization: Bearer ${METRICS_TOKEN}" \
  "$API_BASE_URL/v1/metrics" | head -20
```

**Expected:** Prometheus-formatted metrics or HTTP 401/404

## 8. Database & Jobs

### 8.1 Job Heartbeat Status
Tests job runner heartbeat tracking.

```bash
curl -fsS -u "$ADMIN_USER:$ADMIN_PASS" \
  "$API_BASE_URL/v1/admin/jobs/status" | jq .
```

**Expected:** HTTP 200 with job status array:
```json
{
  "jobs": [
    {
      "name": "jobs-runner",
      "last_heartbeat": "2026-01-06T12:00:00Z",
      "last_success_at": "2026-01-06T12:00:00Z",
      "consecutive_failures": 0
    }
  ]
}
```

## 9. Reverse Proxy (Caddy)

### 9.1 HTTPS Redirect (Production Only)
Tests HTTP to HTTPS redirect.

```bash
# Production only - test HTTP redirect
curl -fsS -I "http://panidobro.com/" | grep -i "location: https"
```

**Expected:** `Location: https://panidobro.com/`

### 9.2 Security Headers
Tests security headers from Caddy and application.

```bash
curl -fsS -I "$API_BASE_URL/healthz" | grep -i "x-content-type-options"
```

**Expected:** `X-Content-Type-Options: nosniff`

```bash
curl -fsS -I "$API_BASE_URL/healthz" | grep -i "x-frame-options"
```

**Expected:** `X-Frame-Options: DENY`

## 10. Docker Services Health

### 10.1 All Services Running
Check that all Docker Compose services are up.

```bash
docker compose ps --format json | jq -r '.[] | "\(.Service): \(.State)"'
```

**Expected:**
```
api: running
web: running
db: running
caddy: running
```

### 10.2 Database Connectivity
Test PostgreSQL connectivity from host.

```bash
docker compose exec -T db pg_isready -U ${POSTGRES_USER:-postgres}
```

**Expected:** `<host>:<port> - accepting connections`

### 10.3 API Container Logs
Check for startup errors in API logs.

```bash
docker compose logs --tail=50 api | grep -i "error\|exception\|failed" || echo "No errors found"
```

**Expected:** No critical errors (some warnings acceptable)

## 11. Storage Backend

### 11.1 Storage Configuration
Verify storage backend is properly configured.

```bash
curl -fsS -u "$ADMIN_USER:$ADMIN_PASS" \
  "$API_BASE_URL/v1/admin/config" | jq '.storage'
```

**Expected:** Storage backend configuration (local/R2/Cloudflare Images)

## 12. Email System (if configured)

### 12.1 Email Configuration
Verify email adapter is configured.

```bash
curl -fsS -u "$ADMIN_USER:$ADMIN_PASS" \
  "$API_BASE_URL/v1/admin/config" | jq '.email'
```

**Expected:** Email mode (off/sendgrid/smtp)

## Quick Smoke Test Script

For a fast smoke test, run these essential checks:

```bash
#!/bin/bash
set -euo pipefail

echo "=== Quick Smoke Test ==="
echo ""

echo "[1/5] API Health..."
curl -fsS "$API_BASE_URL/healthz" -o /dev/null && echo "✓ OK" || echo "✗ FAIL"

echo "[2/5] API Readiness..."
curl -fsS "$API_BASE_URL/readyz" -o /dev/null && echo "✓ OK" || echo "✗ FAIL"

echo "[3/5] Web Root..."
curl -fsS "$WEB_BASE_URL/" -o /dev/null && echo "✓ OK" || echo "✗ FAIL"

echo "[4/5] Estimate Endpoint..."
curl -fsS -X POST "$API_BASE_URL/v1/estimate" \
  -H "Content-Type: application/json" \
  -d '{"beds":2,"baths":1,"cleaning_type":"standard"}' \
  -o /dev/null && echo "✓ OK" || echo "✗ FAIL"

echo "[5/5] Admin Auth..."
curl -fsS -u "$ADMIN_USER:$ADMIN_PASS" \
  "$API_BASE_URL/v1/admin/profile" -o /dev/null && echo "✓ OK" || echo "✗ FAIL"

echo ""
echo "=== Smoke Test Complete ==="
```

## 6. Finance Reconciliation (Admin-only)

Safely identify and repair invoice/payment mismatches without mutating production data:

1. **List mismatches (read-only):**

   ```bash
   export ORG_ID="$(uuidgen)" # set to the target org when running in multi-tenant environments

   curl -fsS -u "$ADMIN_USER:$ADMIN_PASS" \
     -H "X-Test-Org: $ORG_ID" \
     "$API_BASE_URL/v1/admin/finance/reconcile/invoices?status=mismatch&limit=10" | jq .
   ```

2. **Dry-run a reconcile (no writes):**

   ```bash
   INVOICE_ID="<invoice-id-from-step-1>"

   curl -fsS -u "$ADMIN_USER:$ADMIN_PASS" \
     -H "X-Test-Org: $ORG_ID" \
     "$API_BASE_URL/v1/admin/finance/invoices/$INVOICE_ID/reconcile?dry_run=1" | jq .
   ```

   **Expected:** `dry_run: true`, `before`/`after` snapshots, and `planned_operations` describing the status change. No audit logs or DB writes occur during a dry-run.

3. **Apply the reconcile (only after verifying the dry-run):**

   ```bash
   curl -fsS -u "$ADMIN_USER:$ADMIN_PASS" \
     -H "X-Test-Org: $ORG_ID" \
     -X POST "$API_BASE_URL/v1/admin/finance/invoices/$INVOICE_ID/reconcile" | jq .
   ```

## Troubleshooting

### Health Check Fails
- Check `docker compose ps` for service status
- Review logs: `docker compose logs api`
- Verify `.env` configuration

### Readiness Check Fails
- **View detailed check results:** `curl $API_BASE_URL/readyz | jq .`
- **DB check failure:**
  - Verify database is running: `docker compose ps db`
  - Check database logs: `docker compose logs db`
  - Test connection: `docker compose exec api python -c "from app.infra.db import get_session_factory; import asyncio; asyncio.run(get_session_factory().__anext__())"`
- **Migrations check failure:**
  - Check current revision: `docker compose exec api alembic current`
  - Check expected heads: `docker compose exec api alembic heads`
  - Apply pending migrations: `docker compose exec api alembic upgrade head`
- **Jobs check failure:**
  - Verify jobs are enabled: check `JOBS_ENABLED` in `.env`
  - Check job heartbeat freshness: `curl -u "$ADMIN_USER:$ADMIN_PASS" $API_BASE_URL/v1/admin/jobs/status | jq .`
  - Start job runner if not running: `docker compose up -d jobs` or run `python -m app.jobs.run`
  - Check job runner logs: `docker compose logs jobs`

### Backup Health Fails
- Ensure backup directory exists: `/opt/backups/postgres/`
- Check backup marker file: `/opt/backups/postgres/LAST_SUCCESS.txt`
- Run backup script if needed

### Stripe Webhook 503
- Verify `STRIPE_WEBHOOK_SECRET` is set in `.env`
- Check Stripe configuration in production settings

### Rate Limiting Not Working
- Check `REDIS_URL` configuration
- Verify rate limiter settings: `RATE_LIMIT_PER_MINUTE`
- Check logs for rate limiter initialization

## Next Steps

After smoke tests pass:
1. Review logs for warnings: `docker compose logs`
2. Check metrics endpoint (if enabled)
3. Run comprehensive test suite: `cd backend && pytest -m smoke`
4. Verify backup automation is scheduled
5. Test job runner is operational
6. Review GO_NO_GO.md checklist
