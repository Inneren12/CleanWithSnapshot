# Operations Guide

Comprehensive guide for deploying, monitoring, and troubleshooting CleanWithSnapshot in production.

---

## Table of Contents

1. [Deployment](#deployment)
2. [Security Scanning](#security-scanning)
3. [Environment Configuration](#environment-configuration)
4. [Health Monitoring](#health-monitoring)
5. [Logs & Debugging](#logs--debugging)
6. [Backup & Restore](#backup--restore)
7. [Troubleshooting](#troubleshooting)
8. [Performance Tuning](#performance-tuning)

---

## Deployment

### Production Stack

**Infrastructure:** Docker Compose with 5 services

```
┌─────────────────────────────────────────┐
│            Caddy (Reverse Proxy)         │
│         :80 → :443 (auto-HTTPS)          │
└──────────┬────────────────────┬──────────┘
           │                    │
           ▼                    ▼
    ┌──────────┐         ┌──────────┐
    │ API      │         │ Web      │
    │ :8000    │         │ :3000    │
    └─────┬────┘         └──────────┘
          │
          ▼
    ┌──────────┐         ┌──────────┐
    │ Postgres │         │ Redis    │
    │ :5432    │         │ :6379    │
    └──────────┘         └──────────┘
```

**Services:**

| Service | Image | Port | Data Volume |
|---------|-------|------|-------------|
| `caddy` | caddy:2 | 80, 443 | `caddy_data`, `caddy_config` |
| `api` | ./backend (Dockerfile) | 8000 | `./var/uploads` |
| `web` | ./web (Dockerfile) | 3000 | None |
| `db` | postgres:16 | 5432 | `pg_data` |
| `redis` | redis:7-alpine | 6379 | `redis_data` |

---

### One-Button Deploy

**Location:** `/opt/cleaning` (production server)

**Command:**

```bash
cd /opt/cleaning
./ops/deploy.sh
```

**What it does:**

1. **Prints git SHAs** - Current and updated commit hashes
2. **Fetches latest code** - `git fetch origin && git reset --hard origin/main`
   - Preserves: `.env`, `logs/`, `pg_data/`, `var/`, `tmp/`
3. **Builds Docker images** - `docker compose build`
4. **Starts stack** - `docker compose up -d --remove-orphans`
5. **Waits for Postgres** - Health check loop
6. **Runs migrations** - `alembic upgrade head` inside API container
7. **Smoke tests** - `ops/smoke.sh` (API + web health checks)
8. **Fails if unhealthy** - Non-zero exit if smoke tests fail

**Script:** `ops/deploy.sh`

---

### Manual Deployment Steps

If you need to deploy manually:

```bash
cd /opt/cleaning

# 1. Pull latest code
git fetch origin
git reset --hard origin/main

# 2. Build images
docker compose build

# 3. Start services
docker compose up -d --remove-orphans

# 4. Wait for Postgres
until docker compose exec -T db pg_isready; do sleep 1; done

# 5. Run migrations
docker compose exec api alembic upgrade head

# 6. Verify health
curl -fsS https://api.panidobro.com/healthz
curl -fsS https://panidobro.com/
```

---

### CI Smoke Tests (Docker Compose)

The CI pipeline validates deploy readiness by spinning up Docker Compose and running the same
`ops/smoke.sh` health checks used in production.

**CI flow:**

```bash
# Start the minimal stack with CI-specific overrides
docker compose -f docker-compose.yml -f docker-compose.ci.yml up -d --wait db redis api web

# Run smoke tests against the locally exposed services
API_BASE_URL=http://localhost:8000 \
WEB_BASE_URL=http://localhost:3000 \
./ops/smoke.sh

# Always clean up
docker compose -f docker-compose.yml -f docker-compose.ci.yml down -v
```

**Failure artifacts:** If the smoke tests fail, CI uploads Docker Compose logs and service status
to help debug startup issues.

---

### Rollback

**Rollback to previous commit:**

```bash
cd /opt/cleaning

# 1. Find previous good commit
git log --oneline -10

# 2. Reset to that commit
git reset --hard <sha>

# 3. Re-deploy
./ops/deploy.sh
```

**Important:** Migrations are forward-only. Rollback code, NOT migrations.

---

## Security Scanning

### Container vulnerability policy (Trivy)

**CI behavior:** The pipeline builds the `api` and `web` images with `docker compose build api web` and scans
those images with Trivy. The job **fails on CRITICAL vulnerabilities** so releases are blocked until critical
issues are addressed. Trivy JSON reports are uploaded as CI artifacts for review.

**Remediation workflow:**

1. **Identify the affected component** in the Trivy report (base image, OS package, or application dependency).
2. **Upgrade the base image** (e.g., `python:3.11-slim`, `node:20-alpine`) or update the dependency that pulls
   in the vulnerable package.
3. **Rebuild the image locally** and re-run Trivy to verify the fix:
   ```bash
   docker compose build api web
   trivy image cleanwithsnapshot-api
   trivy image cleanwithsnapshot-web
   ```
4. **Re-run CI** (or push a follow-up commit) once the critical findings are resolved.

---

### RLS coverage audit

We run a Row-Level Security (RLS) coverage audit to ensure every org-scoped table is protected.
The audit script inspects tables with an `org_id` column and verifies that RLS is enabled and
at least one policy exists.

**Core table gate:** The CI job fails if any of the following core tables lack RLS coverage:
`bookings`, `invoices`, `leads`, `clients` (maps to `client_users`), `workers`. Non-core tables
are reported as warnings only (the warning list is included in the report output).

**Run locally (database mode):**

```bash
cd backend
python scripts/audit_rls_coverage.py --fail-on-core-missing --output rls-audit.md
```

**Run locally without a database (metadata mode):**

```bash
cd backend
python scripts/audit_rls_coverage.py --source metadata --output rls-audit.md
```

**CI behavior:** The `Security - RLS Coverage Audit` job provisions a temporary Postgres service,
applies migrations, and runs the audit. The markdown report is uploaded as a CI artifact.

---

## Scheduled Jobs

The API container runs the job runner to process background tasks (email reminders, outbox delivery, storage cleanup).
Digest jobs are executed by the same runner and can be triggered on-demand.

**Run locally (one-shot):**

```bash
cd backend
python -m app.jobs.run --job notifications-digest-daily --once
python -m app.jobs.run --job notifications-digest-weekly --once
python -m app.jobs.run --job notifications-digest-monthly --once
```

**Digest configuration:**
- Settings are stored in `notifications_digest_settings` (`digest_key`, `enabled`, `schedule`, `recipients`).
- Only enabled digests matching the job schedule are sent.
- Digest delivery is gated by `module.notifications_center` feature toggle.
- Delivery is rate-limited per org/period using `notifications_digest_state` so looping runners do not resend
  the same daily/weekly/monthly digest within the same period.
- Safe to run every loop: each org/digest is gated by a period key computed in the org timezone.

### Google Calendar sync job (gcal-sync)

**Run locally (one-shot):**

```bash
cd backend
python -m app.jobs.run --job gcal-sync --once
```

**Environment variables:**
- `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` (OAuth setup)
- `GCAL_SYNC_INTERVAL_SECONDS` (minimum seconds between sync runs per org/calendar)
- `GCAL_SYNC_INITIAL_DAYS` (initial lookback window when no cursor exists)
- `GCAL_SYNC_FUTURE_DAYS` (future horizon to sync)
- `GCAL_SYNC_BACKFILL_MINUTES` (overlap window to avoid missing near-edge changes)

**Safe cadence:**
- The runner can loop every minute, but `gcal-sync` only executes when
  `now - last_sync_at >= GCAL_SYNC_INTERVAL_SECONDS`.
- Sync is skipped entirely if the integration is disabled for the org.

---

### QuickBooks sync job (qbo-sync)

Runs the QuickBooks Online sync loop (invoice push + payment status pull).

**Run locally (one-shot):**

```bash
cd backend
python -m app.jobs.run --job qbo-sync --once
```

**Environment variables:**
- `QUICKBOOKS_OAUTH_CLIENT_ID`, `QUICKBOOKS_OAUTH_CLIENT_SECRET`, `QUICKBOOKS_OAUTH_REDIRECT_URI` (OAuth setup)
- `QBO_SYNC_INTERVAL_SECONDS` (minimum seconds between sync runs per org)
- `QBO_SYNC_INITIAL_DAYS` (lookback window when no cursor exists)
- `QBO_SYNC_BACKFILL_DAYS` (overlap window to avoid missing late updates)

**Safe cadence:**
- The runner can loop every minute, but `qbo-sync` only executes when
  `now - last_sync_at >= QBO_SYNC_INTERVAL_SECONDS`.
- Sync is skipped entirely if the integration is disabled for the org or OAuth is not configured.

---

### Lead nurture runner (leads-nurture-runner)

Processes due nurture step logs (planned/scheduled lead follow-ups) with strict gating.

**Run locally (one-shot):**

```bash
cd backend
python -m app.jobs.run --job leads-nurture-runner --once
```

**Environment variables:**
- `LEADS_NURTURE_RUNNER_BATCH_SIZE` (max due logs per run, default 50)
- `LEADS_NURTURE_RUNNER_LOOKBACK_HOURS` (planned_at lookback window, default 168)

**Feature gating:**
- Requires org feature overrides: `module.leads` + `leads.nurture` (both disabled by default).

**Quiet hours:**
- Uses org settings timezone + `business_hours` windows.
- Steps are deferred to the next business-hour start when quiet hours are active.

**Provider safety:**
- If email/SMS providers are disabled or unconfigured, the runner logs the step as `skipped`
  instead of crashing.

**Safe cadence:**
- Can run every minute; selection is windowed on `planned_at <= now` and the lookback window.

---

## Finance tax exports

Finance tax exports are generated on-demand as ZIP bundles of CSV files for GST reporting (summary, payments,
expenses, instalments). These endpoints are admin-authenticated and require `finance.view`.

**Example (GST export):**

```bash
curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \\
  "https://api.panidobro.com/v1/admin/finance/taxes/export?from=2026-01-01&to=2026-03-31" \\
  -o gst_export_2026_Q1.zip
```

---

## NPS Survey Sends

**Endpoint:** `POST /v1/admin/nps/send?booking_id=<booking_id>`

**Behavior:**
- Enqueues an outbox event for the booking; the `nps-send-runner` job delivers the send.
- Gate sends per booking (once) and per client within the configured period to prevent spam.
- Honors the `quality.nps` feature flag and NPS unsubscribe list.
- If email or SMS delivery is disabled, the job logs and marks the outbox event as sent.

**Required configuration:**
- `PUBLIC_BASE_URL` or `CLIENT_PORTAL_BASE_URL` must be set so survey links are generated.
- The `outbox-delivery` job must be running to deliver queued emails.

**Example:**

```bash
curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \\
  -X POST "https://api.panidobro.com/v1/admin/nps/send?booking_id=BOOKING_ID"
```

---

## Environment Configuration

### Critical Environment Variables

**Location:** `/opt/cleaning/.env` (NEVER commit this file)

**Required variables:**

```bash
# Database
DATABASE_URL="postgresql+psycopg://user:pass@db:5432/cleaning"
POSTGRES_DB="cleaning"
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="<strong-password>"

# Secrets (32+ chars in production)
AUTH_SECRET_KEY="<random-string-32-chars>"
CLIENT_PORTAL_SECRET="<random-string-32-chars>"
WORKER_PORTAL_SECRET="<random-string-32-chars>"

# Admin credentials (at least one required)
ADMIN_BASIC_USERNAME="admin"
ADMIN_BASIC_PASSWORD="<strong-password>"

# Environment
APP_ENV="prod"
STRICT_CORS="true"
TRUST_PROXY_HEADERS="true"
```

### Google Calendar OAuth (Integrations)

Set these to enable Google Calendar OAuth connect/disconnect:

```bash
GOOGLE_OAUTH_CLIENT_ID="<google-oauth-client-id>"
GOOGLE_OAUTH_CLIENT_SECRET="<google-oauth-client-secret>"
GOOGLE_OAUTH_REDIRECT_URI="https://panidobro.com/admin/settings/integrations"
```

The redirect URI should match the OAuth consent screen configuration and point to the
admin integrations page where the callback is handled.

### QuickBooks OAuth (Integrations)

Set these to enable QuickBooks OAuth connect/disconnect:

```bash
QUICKBOOKS_OAUTH_CLIENT_ID="<quickbooks-client-id>"
QUICKBOOKS_OAUTH_CLIENT_SECRET="<quickbooks-client-secret>"
QUICKBOOKS_OAUTH_REDIRECT_URI="https://panidobro.com/admin/settings/integrations"
```

The redirect URI should match the QuickBooks app configuration and point to the
admin integrations page where the callback is handled.

### Maps (Google Maps Distance Matrix)

Set these to enable Maps distance matrix requests and quota tracking:

```bash
GOOGLE_MAPS_API_KEY="<google-maps-api-key>"
```

**Optional quota controls:**

```bash
MAPS_MONTHLY_QUOTA_LIMIT="10000"  # billable elements per month, set to 0 for unlimited
MAPS_REQUESTS_PER_MINUTE="30"     # per-org rate limit
```

**Runbook:**
- If the key is missing or quota is exceeded, the API returns heuristic estimates instead of failing.
- Track usage via `GET /v1/admin/maps/quota` (owner/admin), and validate the key via
  `POST /v1/admin/maps/test_key` (owner only).

### Weather + Traffic Widget (Open-Meteo)

Controls the ops dashboard weather/traffic widget provider:

```bash
WEATHER_TRAFFIC_MODE="off"  # off | open_meteo
```

**Runbook:**
- When set to `off`, `/v1/admin/context/weather_traffic` returns empty payloads with a warning flag.
- When set to `open_meteo`, weather data is fetched from Open-Meteo and cached in memory for 15 minutes.

**Optional variables:**

```bash
# Email (SendGrid)
EMAIL_MODE="sendgrid"
SENDGRID_API_KEY="SG.xxx"

# SMS/Calls (Twilio)
SMS_MODE="twilio"
TWILIO_ACCOUNT_SID="ACxxx"
TWILIO_AUTH_TOKEN="xxx"

# Stripe
STRIPE_SECRET_KEY="sk_live_xxx"
STRIPE_WEBHOOK_SECRET="whsec_xxx"

# Storage (Cloudflare R2)
ORDER_STORAGE_BACKEND="r2"
R2_BUCKET="bucket-name"
R2_ACCESS_KEY="xxx"
R2_SECRET_KEY="xxx"

### CI secrets scanning (Gitleaks)

CI runs a Gitleaks scan on every PR and main branch push. PRs scan only the diff range; main pushes scan full history. The allowlist lives in `.gitleaks.toml` and intentionally skips docs, tests, and example env files that contain known-safe placeholders. Update the allowlist with a short justification if a new documented fixture triggers a false positive.

**If the scan finds a real secret:**
1. **Rotate immediately** in the upstream system (vendor console, cloud provider, or auth service). Avoid pasting any secret into tickets or logs.
2. **Update the secret store** (Vault/SSM/Kubernetes Secret/CI secret) with the new value and re-deploy or restart affected services.
3. **Invalidate sessions/tokens** where applicable (JWT signing keys, portal secrets, Stripe webhook secrets, OAuth client secrets).
4. **Audit access**: check logs for unexpected usage and confirm the old secret no longer works.
5. **Purge the secret from Git history** if it was committed (rewrite history, rotate again after the cleanup).

# Metrics
METRICS_ENABLED="true"
METRICS_TOKEN="<token>"

# NPS sends
NPS_SEND_PERIOD_DAYS="30"
```

**Rules action adapters:**
- `create_notification_event` always writes to the notifications inbox when rules execute.
- `send_email` only runs when `EMAIL_MODE` is enabled; otherwise it logs a skipped action.
- `send_sms` only runs when `SMS_MODE=twilio`; otherwise it logs a skipped action.
- `escalate` uses the rule escalation policy (level1 email, level2 sms) and writes cooldown tracking to
  `rule_escalations`; it will skip if within the cooldown window.
- Phone-call escalation is not executed yet (rule configs can store call intent, but it will only log).

**Full list:** See [docs/ENV_AUDIT_REPORT.md](./docs/ENV_AUDIT_REPORT.md)

---

### Docker Compose Configuration

**File:** `docker-compose.yml`

**Data persistence:**

```yaml
volumes:
  pg_data:         # PostgreSQL data
  redis_data:      # Redis persistence
  caddy_data:      # Caddy HTTPS certificates
  caddy_config:    # Caddy configuration
```

**Mapped directories:**

```yaml
- ./var/uploads:/app/var/uploads    # File uploads (API)
- /opt/backups/postgres:/backups    # Database backups (DB)
```

**Health checks:**

| Service | Check | Interval |
|---------|-------|----------|
| db | `pg_isready` | 5s |
| redis | `redis-cli ping` | 10s |
| api | HTTP 200 on `/healthz` | 10s |
| web | HTTP 200 on `/` | 10s |

---

## Health Monitoring

### Health Endpoints

**API Health:**

```bash
curl -fsS https://api.panidobro.com/healthz
```

**Expected response:**

```json
{
  "status": "ready",
  "db_connected": true,
  "migrations_current": true,
  "current_revision": "0086",
  "expected_revision": "0086"
}
```

**If unhealthy:**

```json
{
  "status": "unhealthy",
  "db_connected": false,
  "migrations_current": false,
  "current_revision": "0085",
  "expected_revision": "0086",
  "error": "Database connection failed"
}
```

**Web Health:**

```bash
curl -fsS https://panidobro.com/healthz
```

### Dead Letter Queue Check

**Admin-only:** Check for failed background jobs

```bash
curl -fsS -u "$ADMIN_USERNAME:$ADMIN_PASSWORD" \
  "https://api.panidobro.com/v1/admin/queue/dlq?kind=all&limit=1"
```

**Expected:**

```json
{
  "outbox_dead_count": 0,
  "export_dead_count": 0
}
```

**If non-zero:** Investigate failed jobs before proceeding with deploy.

---

### Metrics

**Prometheus metrics:**

```bash
curl https://api.panidobro.com/metrics \
  -H "Authorization: Bearer <metrics-token>"
```

**Key metrics:**
- `http_requests_total` - Request count by method, path, status
- `http_request_duration_seconds` - Latency histogram
- `http_5xx_errors_total` - 5xx error count

**Grafana dashboards:** (If configured)

---

## Logs & Debugging

### Application Logs

**Structured JSON logs with context:**

```json
{
  "timestamp": "2026-01-15T12:00:00Z",
  "level": "INFO",
  "message": "request",
  "request_id": "abc-123",
  "org_id": "org-789",
  "user_id": "user-456",
  "role": "admin",
  "method": "POST",
  "path": "/v1/admin/ui/bookings/create",
  "status_code": 200,
  "latency_ms": 45
}
```

**View logs:**

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api
docker compose logs -f web
docker compose logs -f db

# Last 200 lines
docker compose logs --tail=200 api

# Search logs
docker compose logs api | grep "error"
docker compose logs api | grep "org_id=xyz"
```

### Admin Audit Logs

**Database table:** `admin_audit_logs`

**Query recent admin actions:**

```sql
SELECT
  created_at,
  admin_role,
  action,
  resource_type,
  resource_id,
  metadata
FROM admin_audit_logs
WHERE org_id = 'org-789'
ORDER BY created_at DESC
LIMIT 50;
```

**Example:**

```
2026-01-15 12:00:00 | admin | booking.create | booking | def-456 | {"client_id": "abc-123"}
2026-01-15 11:55:00 | admin | worker.password_reset | worker | 5 | {"phone": "+1234567890"}
```

---

### Debug Mode

**Enable verbose logging (dev only):**

```bash
export LOG_LEVEL="DEBUG"
docker compose restart api
```

**Production:** Keep `LOG_LEVEL="INFO"` or `"WARNING"`

---

## Backup & Restore

### Database Backup

**Automated backup (recommended):**

```bash
# Add to cron (daily at 2 AM)
0 2 * * * /opt/cleaning/ops/backup.sh
```

**Manual backup:**

```bash
# Create backup
docker compose exec db pg_dump -U postgres cleaning > backup_$(date +%Y%m%d_%H%M%S).sql

# Copy to backup directory
mv backup_*.sql /opt/backups/postgres/

# Compress
gzip /opt/backups/postgres/backup_*.sql
```

**Backup location:** `/opt/backups/postgres/`

---

### Database Restore

**From backup file:**

```bash
cd /opt/cleaning

# 1. Stop API (prevent writes)
docker compose stop api web

# 2. Drop and recreate database
docker compose exec db psql -U postgres -c "DROP DATABASE cleaning;"
docker compose exec db psql -U postgres -c "CREATE DATABASE cleaning;"

# 3. Restore from backup
gunzip -c /opt/backups/postgres/backup_20260115.sql.gz | \
  docker compose exec -T db psql -U postgres cleaning

# 4. Verify
docker compose exec db psql -U postgres cleaning -c "SELECT COUNT(*) FROM bookings;"

# 5. Restart services
docker compose up -d
```

---

### File Uploads Backup

**Backup uploads directory:**

```bash
# Sync to remote storage (e.g., S3)
aws s3 sync /opt/cleaning/var/uploads/ s3://bucket-name/uploads/ --delete

# Or tar + compress
tar -czf uploads_backup_$(date +%Y%m%d).tar.gz var/uploads/
```

---

## Troubleshooting

### API Won't Start

**Symptom:** `docker compose up -d api` fails

**Check:**

1. **View logs:**
   ```bash
   docker compose logs api
   ```

2. **Common issues:**
   - Missing environment variables
   - Database connection failed
   - Migrations out of sync
   - Port 8000 already in use

3. **Solutions:**
   - Check `.env` file exists and is valid
   - Verify database is running: `docker compose ps db`
   - Run migrations: `docker compose exec api alembic upgrade head`
   - Kill process using port 8000: `sudo lsof -ti:8000 | xargs kill -9`

---

### Database Connection Issues

**Symptom:** `FATAL: password authentication failed`

**Check:**

1. **Database credentials:**
   ```bash
   grep POSTGRES .env
   ```

2. **Database running:**
   ```bash
   docker compose ps db
   docker compose logs db
   ```

3. **Solution:**
   - Ensure `POSTGRES_PASSWORD` in `.env` matches `DATABASE_URL`
   - Restart database: `docker compose restart db`

---

### Migrations Out of Sync

**Symptom:** `/healthz` returns `migrations_current: false`

**Solution:**

```bash
# Run migrations
docker compose exec api alembic upgrade head

# Verify
curl https://api.panidobro.com/healthz
```

---

### Multiple Migration Heads

**Symptom:** `alembic heads` shows multiple heads or the staging/prod pipeline fails the Alembic head check.

**What to do in staging/prod pipelines:**

1. **Stop the deployment** (do not run migrations with multiple heads).
2. **Identify all heads** in the repo:
   ```bash
   cd backend
   alembic heads
   ```
3. **Create a merge migration** that includes every head:
   ```bash
   alembic merge -m "merge migration heads" <head1> <head2> ... <headN>
   ```
4. **Commit the merge** and re-run the pipeline:
   ```bash
   git add alembic/versions/merge_*.py
   git commit -m "chore(db): merge migration heads"
   git push
   ```
5. **Re-deploy** once CI is green:
   ```bash
   ./ops/deploy.sh
   ```

**Important:** do not apply migrations in staging/prod until the merge migration lands and `alembic heads`
returns a single revision.

See [DB_MIGRATIONS.md](./DB_MIGRATIONS.md#merging-heads) for the detailed merge procedure.

---

### High CPU/Memory Usage

**Check resource usage:**

```bash
docker stats

# Output:
# CONTAINER   CPU %   MEM USAGE / LIMIT   MEM %
# api         25%     512MB / 2GB         25%
# db          15%     1GB / 4GB           25%
```

**Solutions:**

1. **Increase container resources** (in `docker-compose.yml`):
   ```yaml
   api:
     deploy:
       resources:
         limits:
           memory: 2G
           cpus: '1.0'
   ```

2. **Database connection pooling** (check settings.py):
   - `pool_size` - Number of connections
   - `max_overflow` - Additional connections
   - `pool_timeout_seconds` - Connection wait timeout

3. **Check for slow queries:**
   ```sql
   SELECT * FROM pg_stat_activity WHERE state = 'active';
   ```

---

### Rate Limit Errors

**Symptom:** 429 Too Many Requests

**Check:**

```bash
# View rate limiter config
grep RATE_LIMIT .env
```

**Adjust rate limits:**

```bash
# In .env
RATE_LIMIT_PER_MINUTE=60  # Increase from 30
ADMIN_ACTION_RATE_LIMIT_PER_MINUTE=10  # Increase from 5

# Restart
docker compose restart api
```

---

## Performance Tuning

### Database Optimization

**Check slow queries:**

```sql
-- Enable query logging
ALTER SYSTEM SET log_min_duration_statement = 1000;  -- Log queries > 1s
SELECT pg_reload_conf();

-- View slow queries (from logs)
docker compose logs db | grep "duration:"
```

**Add indexes:**

```bash
# Create migration for missing indexes
cd backend
alembic revision -m "add booking status index"

# Edit migration
# op.create_index('ix_bookings_status', 'bookings', ['status'])

# Deploy
alembic upgrade head
```

**Vacuum database:**

```bash
docker compose exec db vacuumdb -U postgres -d cleaning --analyze
```

---

### Connection Pooling

**Tune pool settings** (`backend/app/settings.py`):

```python
class Settings(BaseSettings):
    pool_size: int = 20  # Increase if needed
    max_overflow: int = 10
    pool_timeout_seconds: int = 30
    statement_timeout_ms: int = 5000  # Query timeout
```

---

### Caching (Redis)

**Enable Redis caching** (if not already):

```bash
# In .env
REDIS_URL="redis://redis:6379/0"

# Restart
docker compose restart api
```

**Monitor Redis:**

```bash
docker compose exec redis redis-cli INFO stats
```

---

### CDN for Static Assets

**Use Cloudflare or similar for:**
- Next.js static assets
- Uploaded images (if using R2/Cloudflare Images)

**Configure in `web/next.config.js`:**

```javascript
module.exports = {
  assetPrefix: process.env.CDN_URL || '',
}
```

---

## Quick Reference

### Common Commands

```bash
# Deploy
cd /opt/cleaning && ./ops/deploy.sh

# Health check
curl -fsS https://api.panidobro.com/healthz

# View logs
docker compose logs -f api

# Restart service
docker compose restart api

# Run migrations
docker compose exec api alembic upgrade head

# Database backup
docker compose exec db pg_dump -U postgres cleaning > backup.sql

# Database restore
cat backup.sql | docker compose exec -T db psql -U postgres cleaning

# Check disk space
df -h

# Check memory
free -m

# Check container stats
docker stats
```

---

## Monitoring Checklist

**Daily:**
- [ ] Check `/healthz` endpoint
- [ ] Review error logs: `docker compose logs api | grep ERROR`
- [ ] Check disk space: `df -h`

**Weekly:**
- [ ] Review admin audit logs for anomalies
- [ ] Check database backup integrity
- [ ] Review slow query logs

**Monthly:**
- [ ] Update dependencies (security patches)
- [ ] Review performance metrics
- [ ] Clean up old logs/backups

---

## Related Documentation

- [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) - High-level architecture
- [DB_MIGRATIONS.md](./DB_MIGRATIONS.md) - Migration management
- [RUNBOOK.md](./RUNBOOK.md) - Quick operations guide
- [docs/DEPLOY_RUNBOOK.md](./docs/DEPLOY_RUNBOOK.md) - Deployment details
- [docs/DLQ_RUNBOOK.md](./docs/DLQ_RUNBOOK.md) - Dead letter queue management
- [docs/SMOKE.md](./docs/SMOKE.md) - Smoke testing guide
- [docs/ENV_AUDIT_REPORT.md](./docs/ENV_AUDIT_REPORT.md) - Environment variables
