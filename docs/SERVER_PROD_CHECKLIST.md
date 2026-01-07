# Server Production Checklist (VPS)

This checklist is a one-stop, actionable reference for bringing up and operating the production stack on a fresh VPS **without exposing secrets**. It is tailored to the current repo layout, Docker Compose configuration, and the backend’s runtime checks.

> **Do not paste secrets into tickets or logs.** Use only key names and status (set/missing/placeholder).

---

## One-time setup (fresh VPS)

### 1) OS packages and services
- **Required packages**
  - Docker Engine + Docker Compose plugin
  - `ufw` (or firewall equivalent)
  - `curl`, `jq`, `git`, `cron`/systemd timers
  - `logrotate`
- **Services**
  - Docker daemon enabled on boot
  - Cron/systemd timers enabled for backups and monitoring probes

### 2) Directory layout & permissions
Create directories and ensure Docker can read/write:
- Repo clone: `/opt/cleaning`
- Env file: `/etc/cleaning/cleaning.env` (0600 root:root)
- Caddy logs: `/opt/cleaning/logs/` (owned by root, writable by Docker)
- Uploads (local storage): `/opt/cleaning/var/uploads/` (owned by root, writable by Docker)
- DB backup target: `/opt/backups/postgres/` (owned by root, writable by backup job, **readable** by Docker)

> The API container reads `/opt/backups/postgres/LAST_SUCCESS.txt` via a read-only bind mount for `/healthz/backup`.

### 3) Firewall rules / ports
- **Public**: 80/tcp, 443/tcp
- **SSH**: 22/tcp (or your custom port)
- **Internal only**: Postgres 5432, API 8000, Jobs 8001, Web 3000 (no public exposure)

### 4) DNS and TLS
- Cloudflare DNS entries for API and web:
  - `A/AAAA` for `api.<domain>` → VPS IP
  - `A/AAAA` for `<domain>` and `www.<domain>` → VPS IP
- Caddy handles TLS automatically; ensure Cloudflare is in “Full (strict)” mode.

---

## Compose/runtime audit (current stack)

### Services and their expectations
- **db**: Postgres 16 (persistent `pg_data` volume)
- **api**: Uvicorn/FastAPI (relies on `/etc/cleaning/cleaning.env` or `.env` via `ENV_FILE`)
- **jobs**: Background runner (requires same env and DB connectivity)
- **web**: Next.js (only public port via Caddy)
- **caddy**: reverse proxy + TLS + access logs

### Required bind mounts & volumes
- `./logs` → `/var/log/caddy` (for Caddy access + error logs)
- `./var/uploads` → `/app/var/uploads` (local photo storage persistence)
- `/opt/backups/postgres` → `/opt/backups/postgres` (read-only for backup health checks)
- `pg_data`, `caddy_data`, `caddy_config` named volumes for persistence

### Env file handling
- Containers read env via `env_file: ${ENV_FILE:-.env}`
- **Production recommendation:**
  - Option A (recommended):
    ```bash
    export ENV_FILE=/etc/cleaning/cleaning.env
    docker compose --env-file /etc/cleaning/cleaning.env up -d --force-recreate
    ```
  - Option B: symlink `/opt/cleaning/.env` → `/etc/cleaning/cleaning.env`

### Common footguns
- Values containing spaces or JSON arrays **must be quoted** (ex: `CORS_ORIGINS` JSON)
- `STRICT_CORS=true` requires **explicit** `CORS_ORIGINS` (no wildcards)
- Ensure **uploads** are on a persistent host path if using local storage
- Ensure `/opt/backups/postgres/LAST_SUCCESS.txt` exists for `/healthz/backup`

---

## External dependencies & credentials

### Email (SMTP or SendGrid)
- **Required env keys**
  - SMTP: `EMAIL_MODE=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM`
  - SendGrid: `EMAIL_MODE=sendgrid`, `SENDGRID_API_KEY`, `EMAIL_FROM`
- **DNS records**
  - SPF and DKIM records for the sender domain
  - DMARC policy (monitoring or quarantine/reject)
- **Verification**
  - Trigger a test email from admin API and check delivery
  - Check email-related logs for send failures

### Stripe payments + webhooks (if enabled)
- **Required env keys**
  - `DEPOSITS_ENABLED=true`
  - `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`
  - `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL`, invoice/billing URLs
- **Webhook URL**
  - `/v1/payments/stripe/webhook` (legacy `/stripe/webhook` also exists)
- **Verification**
  - Use Stripe CLI to send a test event
  - Confirm webhook returns 200 and logs show processed/ignored

### Captcha (Cloudflare Turnstile)
- **Required env keys**
  - `CAPTCHA_MODE=turnstile`, `TURNSTILE_SECRET_KEY`
- **Verification**
  - Verify signup/booking flows that require captcha

### Redis (rate limiting, photo token cache)
- **Required env key**
  - `REDIS_URL`
- **Verification**
  - Observe rate limiting and photo token issuance
  - Check logs for “redis rate limiter unavailable” warnings

### Monitoring / metrics
- **Required env keys**
  - `METRICS_ENABLED=true`
  - `METRICS_TOKEN`
- **Metrics endpoint**
  - `GET /metrics` with `Authorization: Bearer <METRICS_TOKEN>`
- **Monitoring checks**
  - Better Stack / HTTP monitors for `/healthz`, `/readyz`, `/healthz/backup`
- **Optional heartbeat**
  - `BETTER_STACK_HEARTBEAT_URL` for jobs runner ping

---

## Full env key classification (prod-complete)

> **Goal:** No missing MUST keys, no placeholders, and all SHOULD keys set for “full functionality.”

### MUST (production safety)
- `APP_ENV=prod`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `DATABASE_URL`
- `AUTH_SECRET_KEY`
- `CLIENT_PORTAL_SECRET`
- `WORKER_PORTAL_SECRET`
- `TRUST_PROXY_HEADERS=true`
- `STRICT_CORS=true`
- `CORS_ORIGINS` (required if `STRICT_CORS=true`)

### MUST when enabled
- `METRICS_TOKEN` (when `METRICS_ENABLED=true`)
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` (when `DEPOSITS_ENABLED=true`)
- `TURNSTILE_SECRET_KEY` (when `CAPTCHA_MODE=turnstile`)
- `SENDGRID_API_KEY` (when `EMAIL_MODE=sendgrid`)
- `SMTP_PASSWORD` (when `EMAIL_MODE=smtp`)
- `S3_*` or `R2_*` (when `ORDER_STORAGE_BACKEND` is `s3`/`r2`/`cloudflare_r2`)

### SHOULD (production correctness)
- `PUBLIC_BASE_URL`
- `CLIENT_PORTAL_BASE_URL`
- `EMAIL_MODE`, `EMAIL_FROM`, `EMAIL_FROM_NAME`
- `REDIS_URL`
- `ORDER_STORAGE_BACKEND`, `ORDER_UPLOAD_ROOT`
- `JOBS_ENABLED=true`, `JOB_HEARTBEAT_REQUIRED=true`, `JOB_RUNNER_ID`
- `METRICS_ENABLED=true`

### OPTIONAL (tuning / advanced)
- `RATE_LIMIT_*`
- `DATABASE_POOL_*`
- `EMAIL_*` retry/circuit params
- `STRIPE_CIRCUIT_*`
- `ORDER_PHOTO_*` limits
- `EXPORT_*`
- `RETENTION_*`
- `ADMIN_IP_ALLOWLIST_CIDRS`
- `ADMIN_MFA_REQUIRED` + `ADMIN_MFA_REQUIRED_ROLES`

### Matching env_audit behavior
- Use `python3 ops/env_audit.py --env /etc/cleaning/cleaning.env --check-unused` as a preflight check.
- Ensure `METRICS_TOKEN` is treated as conditional for `METRICS_ENABLED=true`.

---

## Per-deploy runbook

1) **Pull & build**
```bash
cd /opt/cleaning
./ops/deploy.sh
```

2) **Migrations**
- Migrations run automatically in `ops/deploy.sh` via `alembic upgrade head`.
- Verify migrations are in sync with:
  ```bash
  curl -fsS https://api.<domain>/readyz | jq .
  ```

3) **Smoke**
```bash
./ops/smoke.sh
```

---

## Verification steps (post-deploy)

### Core health
```bash
curl -fsS https://api.<domain>/healthz
curl -fsS https://api.<domain>/readyz | jq .
```

### Backup freshness
```bash
curl -fsS https://api.<domain>/healthz/backup | jq .
```

### Admin auth (whoami)
```bash
curl -u "<ADMIN_BASIC_USERNAME>:<ADMIN_BASIC_PASSWORD>" \
  https://api.<domain>/v1/admin/whoami
```

### Jobs heartbeat
```bash
curl -fsS https://api.<domain>/readyz | jq '.checks[] | select(.name=="jobs")'
```

### Metrics (if enabled)
```bash
curl -fsS -H "Authorization: Bearer <METRICS_TOKEN>" https://api.<domain>/metrics
```

### Email send (real test)
- Trigger a booking/invoice email through the admin API and confirm delivery.

### Uploads (local storage)
- Upload a photo and confirm the file appears under `/opt/cleaning/var/uploads/`.

---

## Feature → prerequisites → env keys → verification

### Auth/Admin access
- **Prereqs:** Admin user seeded, `AUTH_SECRET_KEY` + portal secrets set
- **Env keys:** `AUTH_SECRET_KEY`, `CLIENT_PORTAL_SECRET`, `WORKER_PORTAL_SECRET`, optional basic auth credentials
- **Verify:** `GET /v1/admin/whoami` returns 200 with valid auth

### Jobs/heartbeat
- **Prereqs:** `jobs` container running, DB available
- **Env keys:** `JOBS_ENABLED=true`, `JOB_HEARTBEAT_REQUIRED=true`, `JOB_RUNNER_ID`
- **Verify:** `/readyz` shows `jobs.ok=true` and recent heartbeat

### Email sending
- **Prereqs:** SMTP or SendGrid configured
- **Env keys:** `EMAIL_MODE`, `EMAIL_FROM`, SMTP or SendGrid keys
- **Verify:** Send a test invoice/notification and confirm delivery

### Photo uploads (local storage)
- **Prereqs:** `/opt/cleaning/var/uploads/` directory exists, mounted into containers
- **Env keys:** `ORDER_STORAGE_BACKEND=local`, `ORDER_UPLOAD_ROOT=var/uploads/orders`, `ORDER_PHOTO_SIGNING_SECRET`
- **Verify:** Upload a photo, confirm file exists on VPS

### Rate limiting / Redis
- **Prereqs:** Redis reachable
- **Env keys:** `REDIS_URL`
- **Verify:** Check logs for Redis availability and rate-limit behavior

### Stripe webhooks/payments
- **Prereqs:** Stripe account + webhook endpoint configured
- **Env keys:** `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, success/cancel URLs
- **Verify:** Stripe CLI test event returns 200

### Metrics/monitoring
- **Prereqs:** Metrics enabled, token set
- **Env keys:** `METRICS_ENABLED=true`, `METRICS_TOKEN`
- **Verify:** `/metrics` returns 200 with Bearer token

### Backups/restore
- **Prereqs:** Backup job writes `/opt/backups/postgres/LAST_SUCCESS.txt`
- **Env keys:** None (filesystem-based)
- **Verify:** `/healthz/backup` returns 200

---

## Backups & restore procedure

### What to back up
- Postgres data (pg_dump or physical backup)
- `/opt/cleaning/var/uploads/`
- Optional: `/opt/cleaning/logs/` (for incident investigations)

### Example backup job (daily)
- Run a host-level backup that writes a timestamp to `/opt/backups/postgres/LAST_SUCCESS.txt`.
- Store backups offsite (object storage or remote server).

### Restore (safe procedure)
1) Stop services: `docker compose down`
2) Restore Postgres from backup
3) Restore uploads to `/opt/cleaning/var/uploads/`
4) Start services: `docker compose up -d`
5) Validate `/readyz` + `/healthz/backup`

---

## Logging / rotation

- Caddy logs are already rotated by Caddy under `/opt/cleaning/logs/`.
- For container logs, use `docker compose logs` and consider `logrotate` for `/var/lib/docker/containers/*/*.log` on the host.

---

## Security hardening checklist

- **SSH**: disable password auth, use keys, non-root user, optional port change
- **Firewall**: allow only 22/80/443, block all else
- **Cloudflare**:
  - WAF rules for admin paths
  - Allow Stripe webhook IPs or bypass rules for `/v1/payments/stripe/webhook`
  - Rate-limit rules for public endpoints
- **Secrets**: `/etc/cleaning/cleaning.env` permissions `0600`, never commit
- **Caddy**: ensure `Authorization` header is passed upstream (required for admin auth)

---

## When something breaks (triage)

1) **Check container status**
```bash
docker compose ps
```

2) **Inspect logs**
```bash
docker compose logs --tail=200 api
```

3) **Check readiness**
```bash
curl -fsS https://api.<domain>/readyz | jq .
```

4) **Common failure hints**
- `/readyz` DB fail → Postgres unavailable or creds incorrect
- `/readyz` migrations fail → migration not run or version mismatch
- `/readyz` jobs fail → jobs runner not running or heartbeat stale
- `/healthz/backup` fail → backup marker missing or stale

