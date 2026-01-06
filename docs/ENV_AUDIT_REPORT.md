# Production Environment Audit Report

**Date**: 2026-01-06
**Target**: `/etc/cleaning/cleaning.env`
**Deployment**: Docker Compose with `--env-file /etc/cleaning/cleaning.env`

## Executive Summary

This audit analyzed the codebase to determine which environment variables are **truly required** for safe production operation versus those that are optional tuning parameters. The analysis is based on:

1. Pydantic Settings class (`backend/app/settings.py`)
2. Production validation logic (lines 232-319)
3. Runtime usage across services (api, jobs, web, db, caddy)
4. Current live environment keys

### Current Live Environment Status

**Live keys detected** (names only):
- APP_ENV
- POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
- DATABASE_URL
- AUTH_SECRET_KEY
- CLIENT_PORTAL_SECRET
- WORKER_PORTAL_SECRET
- METRICS_TOKEN
- ADMIN_BASIC_USERNAME
- ⚠️ ADMIN_BASIC_PASSWORD (detected as placeholder - requires fix)

### Critical Findings

1. ⚠️ **ADMIN_BASIC_PASSWORD** appears to be a placeholder value
2. ⚠️ Missing recommended security keys: **STRICT_CORS**, **TRUST_PROXY_HEADERS**
3. ⚠️ Missing base URLs for proper link generation: **PUBLIC_BASE_URL**, **CLIENT_PORTAL_BASE_URL**
4. Missing storage configuration (ORDER_STORAGE_BACKEND and related credentials)
5. Missing CORS_ORIGINS (required if STRICT_CORS=true)

---

## Environment Variable Registry

### Tier Classification

- **MUST**: Required for safe production operation (security, auth, DB connectivity)
- **SHOULD**: Highly recommended for production (proper links, CORS, rate limiting infrastructure)
- **OPTIONAL**: Feature flags, tuning parameters, advanced settings

---

## MUST Variables (Required for Safe Production)

| Key | Default | Component | Secret? | Purpose | Failure Impact |
|-----|---------|-----------|---------|---------|----------------|
| **APP_ENV** | `prod` | all | N | Environment mode | Disables prod validation; allows test mode |
| **POSTGRES_DB** | - | db | N | Database name | Container fails to start |
| **POSTGRES_USER** | - | db | N | Database user | Container fails to start |
| **POSTGRES_PASSWORD** | - | db | Y | Database password | Container fails to start |
| **DATABASE_URL** | `postgresql+psycopg://postgres:postgres@postgres:5432/cleaning` | api, jobs | Y | SQLAlchemy connection string | App crashes on startup |
| **AUTH_SECRET_KEY** | `dev-auth-secret` | api, jobs | Y | JWT signing, session tokens | **ENFORCED**: Cannot be default in prod (settings.py:288) |
| **CLIENT_PORTAL_SECRET** | `dev-client-portal-secret` | api, jobs | Y | Client portal magic link signing | **ENFORCED**: Cannot be default in prod (settings.py:289-291) |
| **WORKER_PORTAL_SECRET** | `None` | api, jobs | Y | Worker portal magic link signing | **ENFORCED**: Required in prod (settings.py:293-296) |
| **METRICS_TOKEN** | `None` | api, jobs | Y | Metrics endpoint bearer token | **ENFORCED** if METRICS_ENABLED=true (settings.py:306-307) |
| **TRUST_PROXY_HEADERS** | `false` | api | N | Trust X-Forwarded-For/Proto headers | Client IPs wrong; HTTPS detection fails |
| **STRICT_CORS** | `false` | api | N | Enable strict CORS validation | Wide-open CORS = CSRF risk |
| **CORS_ORIGINS** | `[]` | api | N | Allowed CORS origins | **ENFORCED** if STRICT_CORS=true (settings.py:298-304) |

**Where used:**
- `AUTH_SECRET_KEY`: settings.py:61, settings.py:288, used throughout auth (app/auth/*, app/api/auth.py)
- `CLIENT_PORTAL_SECRET`: settings.py:107, api/routes_client.py (magic link generation)
- `WORKER_PORTAL_SECRET`: settings.py:108, app/auth/worker_auth.py
- `METRICS_TOKEN`: settings.py:161, api/routes_metrics.py (bearer auth check)
- `TRUST_PROXY_HEADERS`: settings.py:27, middleware setup for proper client IP extraction
- `STRICT_CORS`: settings.py:14, CORS middleware configuration
- `POSTGRES_*`: docker-compose.yml:6-8, db container environment

**Notes:**
- DATABASE_URL can use `${POSTGRES_PASSWORD}` interpolation (see .env.production.example:23)
- METRICS_ENABLED defaults to `true` (settings.py:160), so METRICS_TOKEN is effectively required
- Behind Caddy reverse proxy, TRUST_PROXY_HEADERS=true is critical for logging and rate limiting
- STRICT_CORS + CORS_ORIGINS protect against cross-origin attacks

---

## SHOULD Variables (Highly Recommended)

| Key | Default | Component | Secret? | Purpose | Degraded Behavior |
|-----|---------|-----------|---------|---------|-------------------|
| **PUBLIC_BASE_URL** | `None` | api, jobs | N | Base URL for public links | Links use fallback or broken (jobs/email_jobs.py:30-31) |
| **CLIENT_PORTAL_BASE_URL** | `None` | api, jobs | N | Client portal base URL | Falls back to PUBLIC_BASE_URL (api/routes_client.py:112) |
| **REDIS_URL** | `None` | api, jobs | N | Redis for rate limiting, jobs | Rate limiting fails open (settings.py:24); jobs disabled |
| **TRUSTED_PROXY_IPS** | `[]` | api | N | Trusted proxy IP list | Less secure proxy validation |
| **TRUSTED_PROXY_CIDRS** | `[]` | api | N | Trusted proxy CIDR ranges | Less secure proxy validation |
| **EMAIL_MODE** | `off` | api, jobs | N | Email provider (smtp/sendgrid) | No emails sent (infra/email.py:48) |
| **EMAIL_FROM** | `None` | api, jobs | N | From email address | Email sending fails if enabled |
| **SMTP_PASSWORD** or **SENDGRID_API_KEY** | `None` | api, jobs | Y | Email provider credentials | Email fails if EMAIL_MODE enabled |
| **ORDER_STORAGE_BACKEND** | `local` | api | N | Photo storage backend | Uses local filesystem (infra/storage/__init__.py:18) |
| **S3_ACCESS_KEY**, **S3_SECRET_KEY**, **S3_BUCKET** | `None` | api | Y | S3 storage credentials | **ENFORCED** if backend=s3 (infra/storage/__init__.py:22-25) |
| **R2_ACCESS_KEY**, **R2_SECRET_KEY**, **R2_BUCKET** | `None` | api | Y | Cloudflare R2 credentials | **ENFORCED** if backend=r2 (infra/storage/__init__.py:38-41) |
| **STRIPE_SECRET_KEY** | `None` | api | Y | Stripe payments | Payment endpoints return 503 (api/routes_payments.py:518) |
| **STRIPE_WEBHOOK_SECRET** | `None` | api | Y | Stripe webhook verification | Webhook endpoint fails (api/routes_payments.py:668) |
| **CAPTCHA_MODE** | `off` | api | N | Captcha provider | No bot protection |
| **TURNSTILE_SECRET_KEY** | `None` | api | Y | Cloudflare Turnstile secret | **ENFORCED** if CAPTCHA_MODE=turnstile (infra/captcha.py:29) |
| **INVOICE_PUBLIC_TOKEN_SECRET** | `None` | api | Y | Invoice link token signing | Falls back to insecure mode (domain/invoices/service.py:603) |
| **EMAIL_UNSUBSCRIBE_SECRET** | `None` | api, jobs | Y | Unsubscribe link signing | Unsubscribe links fail to validate |
| **ORDER_PHOTO_SIGNING_SECRET** | `None` | api | Y | Photo URL signing | Falls back to AUTH_SECRET_KEY (infra/storage/__init__.py:19) |

**Where used:**
- `PUBLIC_BASE_URL`: jobs/email_jobs.py:52, domain/notifications/email_service.py:208, api/routes_admin.py:3064
- `REDIS_URL`: Rate limiting (app/infra/rate_limit.py), job queue infrastructure
- `EMAIL_MODE`: infra/email.py:48, domain/notifications/email_service.py:398
- `ORDER_STORAGE_BACKEND`: infra/storage/__init__.py:15 (factory decision point)
- `STRIPE_SECRET_KEY`: services.py:31, api/routes_payments.py, infra/stripe_client.py:147

**Notes:**
- Without PUBLIC_BASE_URL or CLIENT_PORTAL_BASE_URL, email links may be broken or use wrong domain
- Storage backend defaults to "local" but production should use s3/r2/cloudflare_images
- If using legacy basic auth (LEGACY_BASIC_AUTH_ENABLED=true), at least one role's username/password required (settings.py:254-258)
- Payment features gracefully degrade without Stripe keys (503 responses)

---

## OPTIONAL Variables (Tuning & Advanced Features)

| Category | Keys | Purpose |
|----------|------|---------|
| **Database tuning** | DATABASE_POOL_SIZE, DATABASE_MAX_OVERFLOW, DATABASE_POOL_TIMEOUT_SECONDS, DATABASE_STATEMENT_TIMEOUT_MS | Connection pool sizing |
| **Rate limiting** | RATE_LIMIT_PER_MINUTE, ADMIN_ACTION_RATE_LIMIT_PER_MINUTE, RATE_LIMIT_CLEANUP_MINUTES, RATE_LIMIT_FAIL_OPEN_SECONDS | Rate limit thresholds |
| **Auth tuning** | AUTH_TOKEN_TTL_MINUTES, AUTH_ACCESS_TOKEN_TTL_MINUTES, AUTH_REFRESH_TOKEN_TTL_MINUTES, SESSION_TTL_MINUTES_WORKER, SESSION_TTL_MINUTES_CLIENT, SESSION_ROTATION_GRACE_MINUTES | Token/session lifetimes |
| **Password hashing** | PASSWORD_HASH_SCHEME, PASSWORD_HASH_ARGON2_TIME_COST, PASSWORD_HASH_ARGON2_MEMORY_COST, PASSWORD_HASH_BCRYPT_COST | Argon2/bcrypt parameters |
| **Email retries** | EMAIL_MAX_RETRIES, EMAIL_RETRY_BACKOFF_SECONDS, EMAIL_HTTP_MAX_ATTEMPTS, EMAIL_TIMEOUT_SECONDS, SMTP_TIMEOUT_SECONDS | Email delivery resilience |
| **Circuit breakers** | STRIPE_CIRCUIT_FAILURE_THRESHOLD, STRIPE_CIRCUIT_RECOVERY_SECONDS, EMAIL_CIRCUIT_FAILURE_THRESHOLD, S3_CIRCUIT_FAILURE_THRESHOLD | External service protection |
| **Storage tuning** | S3_CONNECT_TIMEOUT_SECONDS, S3_READ_TIMEOUT_SECONDS, S3_MAX_ATTEMPTS, STORAGE_DELETE_RETRY_INTERVAL_SECONDS, STORAGE_DELETE_MAX_ATTEMPTS | Storage resilience |
| **Jobs** | JOBS_ENABLED, JOB_HEARTBEAT_REQUIRED, JOB_HEARTBEAT_TTL_SECONDS, JOB_RUNNER_ID | Background job control |
| **Retention** | RETENTION_CHAT_DAYS, RETENTION_LEAD_DAYS, RETENTION_ENABLE_LEADS | Data cleanup policies |
| **Pricing** | PRICING_CONFIG_PATH, DEPOSIT_PERCENT, DEPOSIT_CURRENCY, DEFAULT_WORKER_HOURLY_RATE_CENTS, DEPOSITS_ENABLED | Business logic config |
| **Export/webhooks** | EXPORT_MODE, EXPORT_WEBHOOK_URL, EXPORT_WEBHOOK_TIMEOUT_SECONDS, EXPORT_WEBHOOK_MAX_RETRIES, EXPORT_WEBHOOK_ALLOWED_HOSTS | External integrations |
| **Stripe URLs** | STRIPE_SUCCESS_URL, STRIPE_CANCEL_URL, STRIPE_INVOICE_SUCCESS_URL, STRIPE_BILLING_SUCCESS_URL, etc. | Payment flow redirects |
| **Observability** | ADMIN_NOTIFICATION_EMAIL, BETTER_STACK_HEARTBEAT_URL | Monitoring/alerting |
| **Photo settings** | ORDER_PHOTO_MAX_BYTES, ORDER_PHOTO_ALLOWED_MIMES_RAW, ORDER_PHOTO_SIGNED_URL_TTL_SECONDS, PHOTO_URL_TTL_SECONDS | Upload constraints |
| **Security extras** | ADMIN_IP_ALLOWLIST_CIDRS, ADMIN_MFA_REQUIRED, ADMIN_MFA_REQUIRED_ROLES, STRICT_POLICY_MODE, ADMIN_READ_ONLY | Advanced access controls |
| **DLQ/Outbox** | DLQ_AUTO_REPLAY_ENABLED, OUTBOX_MAX_ATTEMPTS, OUTBOX_BASE_BACKOFF_SECONDS | Message retry policies |

**Defaults:**
- Most tuning parameters have sensible defaults in settings.py
- Jobs default to JOBS_ENABLED=false, but production may want true
- METRICS_ENABLED defaults to true
- DEPOSITS_ENABLED defaults to true

---

## Keys in .env.production.example but NOT Used in Code

**Analysis**: Comparing backend/.env.production.example against actual code usage:

✅ **All keys in .env.production.example are referenced in the codebase.**

Notable observations:
- Some keys like `LEGACY_BASIC_AUTH_ENABLED` are commented out in example (line 50) - correct approach
- Some storage backends (Cloudflare Images) require keys not shown in example: `CF_IMAGES_ACCOUNT_ID`, `CF_IMAGES_API_TOKEN`, `CF_IMAGES_ACCOUNT_HASH`
- Worker basic auth keys are in example but typically unused unless LEGACY_BASIC_AUTH_ENABLED=true

---

## Keys Used in Code but MISSING from .env.production.example

The following keys are used in code but not documented in backend/.env.production.example:

1. `CF_IMAGES_ACCOUNT_ID` - Cloudflare Images account (settings.py:143)
2. `CF_IMAGES_API_TOKEN` - Cloudflare Images API token (settings.py:144)
3. `CF_IMAGES_ACCOUNT_HASH` - Cloudflare Images account hash (settings.py:145)
4. `CF_IMAGES_DEFAULT_VARIANT` - Default image variant (settings.py:146, default: "public")
5. `CF_IMAGES_THUMBNAIL_VARIANT` - Thumbnail variant (settings.py:147)
6. `CF_IMAGES_SIGNING_KEY` - CF Images signed URL key (settings.py:148)
7. `PHOTO_TOKEN_SECRET` - Photo token signing (settings.py:129)
8. `PHOTO_TOKEN_BIND_UA` - Bind tokens to user agent (settings.py:130, default: true)
9. `PHOTO_TOKEN_ONE_TIME` - One-time photo tokens (settings.py:131, default: false)
10. `BETTER_STACK_HEARTBEAT_URL` - Uptime monitoring (settings.py:167)
11. `ADMIN_MFA_REQUIRED` - Force MFA for admin (settings.py:59, default: false)
12. `ADMIN_MFA_REQUIRED_ROLES` - Roles requiring MFA (settings.py:60)
13. `ADMIN_IP_ALLOWLIST_CIDRS` - Admin IP restrictions (settings.py:17-18)
14. `STRICT_POLICY_MODE` - Policy enforcement mode (settings.py:15, default: false)
15. `ADMIN_READ_ONLY` - Read-only admin mode (settings.py:16, default: false)
16. Various outbox/DLQ tuning parameters (settings.py:180-195)

**Recommendation**: These are advanced/optional features and don't need to be in the basic example template.

---

## Minimal Safe Production Environment Template

```bash
##### CRITICAL: Required for safe production #####

# Environment (triggers prod validation)
APP_ENV=prod

# Database (used by db container and DATABASE_URL interpolation)
POSTGRES_DB=cleaning
POSTGRES_USER=clean_prod
POSTGRES_PASSWORD=__GENERATE_STRONG_PASSWORD_32_CHARS__

# Database connection string (can use ${POSTGRES_PASSWORD} interpolation)
DATABASE_URL=postgresql+psycopg://clean_prod:${POSTGRES_PASSWORD}@db:5432/cleaning

# Authentication secrets (ENFORCED in prod - cannot be defaults)
AUTH_SECRET_KEY=__GENERATE_STRONG_SECRET_64_CHARS__
CLIENT_PORTAL_SECRET=__GENERATE_STRONG_SECRET_64_CHARS__
WORKER_PORTAL_SECRET=__GENERATE_STRONG_SECRET_64_CHARS__

# Metrics (required if METRICS_ENABLED=true, which is the default)
METRICS_TOKEN=__GENERATE_BEARER_TOKEN_32_CHARS__

# Reverse proxy configuration (CRITICAL behind Caddy)
TRUST_PROXY_HEADERS=true
TRUSTED_PROXY_IPS=["172.16.0.0/12"]
TRUSTED_PROXY_CIDRS=[]

# CORS protection (REQUIRED for web client)
STRICT_CORS=true
CORS_ORIGINS=["https://panidobro.com","https://api.panidobro.com"]

##### HIGHLY RECOMMENDED: Links, features #####

# Base URLs for proper link generation in emails
PUBLIC_BASE_URL=https://panidobro.com
CLIENT_PORTAL_BASE_URL=https://panidobro.com

# Redis for rate limiting and job queue
REDIS_URL=redis://redis:6379/0

# Storage (choose one: local, s3, r2, cloudflare_images)
ORDER_STORAGE_BACKEND=s3
S3_BUCKET=cleaning-uploads-prod
S3_ACCESS_KEY=__S3_ACCESS_KEY__
S3_SECRET_KEY=__S3_SECRET_KEY__
S3_REGION=us-west-2
S3_ENDPOINT=https://s3.us-west-2.amazonaws.com

# Email (choose: off, smtp, sendgrid)
EMAIL_MODE=smtp
EMAIL_FROM=no-reply@panidobro.com
EMAIL_FROM_NAME=Cleaning Operations
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USERNAME=apikey
SMTP_PASSWORD=__SENDGRID_API_KEY_OR_SMTP_PASSWORD__
SMTP_USE_TLS=true

# Stripe payments
STRIPE_SECRET_KEY=__STRIPE_SECRET_KEY__
STRIPE_WEBHOOK_SECRET=__STRIPE_WEBHOOK_SECRET__
STRIPE_SUCCESS_URL=https://panidobro.com/deposit-success?session_id={CHECKOUT_SESSION_ID}
STRIPE_CANCEL_URL=https://panidobro.com/deposit-cancelled
STRIPE_INVOICE_SUCCESS_URL=https://panidobro.com/invoice-success?session_id={CHECKOUT_SESSION_ID}
STRIPE_INVOICE_CANCEL_URL=https://panidobro.com/invoice-cancelled
STRIPE_BILLING_SUCCESS_URL=https://panidobro.com/billing/success?session_id={CHECKOUT_SESSION_ID}
STRIPE_BILLING_CANCEL_URL=https://panidobro.com/billing/cancelled
STRIPE_BILLING_PORTAL_RETURN_URL=https://panidobro.com/billing

# Captcha (recommended for public forms)
CAPTCHA_MODE=turnstile
TURNSTILE_SECRET_KEY=__TURNSTILE_SECRET_KEY__

# Invoice public links
INVOICE_PUBLIC_TOKEN_SECRET=__GENERATE_STRONG_SECRET_32_CHARS__

# Email unsubscribe links
EMAIL_UNSUBSCRIBE_SECRET=__GENERATE_STRONG_SECRET_32_CHARS__

# Jobs (if running jobs container)
JOBS_ENABLED=true
JOB_HEARTBEAT_REQUIRED=true
JOB_HEARTBEAT_TTL_SECONDS=180
JOB_RUNNER_ID=jobs-01

##### OPTIONAL: Tuning (defaults are usually fine) #####

# Rate limiting
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_CLEANUP_MINUTES=15

# Database pool
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=5
DATABASE_POOL_TIMEOUT_SECONDS=30.0
DATABASE_STATEMENT_TIMEOUT_MS=5000

# Pricing
PRICING_CONFIG_PATH=pricing/economy_v1.json
DEPOSIT_PERCENT=0.25
DEPOSIT_CURRENCY=cad
DEFAULT_WORKER_HOURLY_RATE_CENTS=2500
DEPOSITS_ENABLED=true

# Retention
RETENTION_CHAT_DAYS=30
RETENTION_LEAD_DAYS=365
RETENTION_ENABLE_LEADS=true

# Notifications
ADMIN_NOTIFICATION_EMAIL=ops@panidobro.com

# LEGACY: Only enable if you need role-based basic auth (not recommended)
# LEGACY_BASIC_AUTH_ENABLED=false
# ADMIN_BASIC_USERNAME=
# ADMIN_BASIC_PASSWORD=

# Testing (MUST be false in prod)
TESTING=false
```

---

## Specific Production Recommendations

### 1. Security Headers & CORS

**Current issue**: Live env may not have STRICT_CORS or CORS_ORIGINS configured.

**Fix**:
```bash
STRICT_CORS=true
CORS_ORIGINS=["https://panidobro.com","https://api.panidobro.com"]
TRUST_PROXY_HEADERS=true
TRUSTED_PROXY_IPS=["172.16.0.0/12"]  # Docker network
```

This prevents CSRF attacks and ensures correct client IP logging.

### 2. Base URLs for Links

**Current issue**: Missing PUBLIC_BASE_URL and CLIENT_PORTAL_BASE_URL.

**Impact**: Email links may use incorrect domain or be broken (jobs/email_jobs.py:54, :141).

**Fix**:
```bash
PUBLIC_BASE_URL=https://panidobro.com
CLIENT_PORTAL_BASE_URL=https://panidobro.com
```

### 3. Admin Basic Auth

**Current issue**: ADMIN_BASIC_PASSWORD detected as placeholder.

**Options**:
1. **Recommended**: Disable legacy basic auth entirely (modern auth via CLIENT_PORTAL_SECRET)
   ```bash
   LEGACY_BASIC_AUTH_ENABLED=false
   # Remove ADMIN_BASIC_USERNAME and ADMIN_BASIC_PASSWORD
   ```

2. **If needed**: Generate strong password (16+ chars, validated by settings.py:261-277)
   ```bash
   LEGACY_BASIC_AUTH_ENABLED=true
   ADMIN_BASIC_USERNAME=admin
   ADMIN_BASIC_PASSWORD=__GENERATE_STRONG_PASSWORD_MIN_12_CHARS__
   ```

### 4. Metrics Token

**Current**: METRICS_TOKEN is set ✅

**Verify**: Token should be a strong bearer token (32+ random chars).

### 5. Storage Backend

**Default**: `local` filesystem (not suitable for production scaling)

**Recommendation**: Use S3 or Cloudflare R2
```bash
ORDER_STORAGE_BACKEND=s3
S3_BUCKET=cleaning-uploads-prod
S3_ACCESS_KEY=__AWS_ACCESS_KEY__
S3_SECRET_KEY=__AWS_SECRET_KEY__
S3_REGION=us-west-2
```

Or Cloudflare R2:
```bash
ORDER_STORAGE_BACKEND=r2
R2_BUCKET=cleaning-uploads
R2_ACCESS_KEY=__R2_ACCESS_KEY__
R2_SECRET_KEY=__R2_SECRET_KEY__
R2_ENDPOINT=https://__ACCOUNT_ID__.r2.cloudflarestorage.com
R2_PUBLIC_BASE_URL=https://cdn.panidobro.com
```

### 6. Email Configuration

If email notifications are needed:
```bash
EMAIL_MODE=smtp  # or sendgrid
EMAIL_FROM=no-reply@panidobro.com
EMAIL_FROM_NAME=Cleaning Ops
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USERNAME=apikey
SMTP_PASSWORD=__SENDGRID_API_KEY__
```

---

## Deployment Validation Checklist

Use `ops/env_audit.py` to validate your environment:

```bash
# On production VPS
python3 ops/env_audit.py --env /etc/cleaning/cleaning.env

# Expected output:
# [OK] All MUST keys present
# [OK] No placeholder values detected
# [WARN] Optional keys: EMAIL_MODE=off (emails disabled)
```

**Before deploy checklist**:

- [ ] Run: `python3 ops/env_audit.py --env /etc/cleaning/cleaning.env`
- [ ] Verify all MUST keys present (exit code 0 or warnings only)
- [ ] No CHANGE_ME, PutStrongAdminPasswordHere, or weak passwords
- [ ] STRICT_CORS=true with explicit CORS_ORIGINS
- [ ] TRUST_PROXY_HEADERS=true (behind Caddy)
- [ ] PUBLIC_BASE_URL and CLIENT_PORTAL_BASE_URL match production domain
- [ ] METRICS_TOKEN is strong random value
- [ ] Storage backend configured (s3/r2, not local)
- [ ] Email credentials valid if EMAIL_MODE != off
- [ ] Stripe keys valid if payments enabled
- [ ] Database credentials strong (16+ chars)
- [ ] All secrets are unique (not reused across environments)

**Compose deployment**:
```bash
cd /opt/cleaning
docker compose --env-file /etc/cleaning/cleaning.env up -d --force-recreate
```

---

## Appendix: Environment Loading Behavior

### Where Settings Are Loaded

1. **Pydantic BaseSettings** (`backend/app/settings.py:427`)
   - Auto-loads from `.env` file in working directory (model_config line 197)
   - Overridden by actual environment variables
   - All keys are case-insensitive

2. **Docker Compose** (`docker-compose.yml`)
   - `db` service: Reads POSTGRES_* from compose environment
   - `api` and `jobs` services: `env_file: .env` (line 28, 47)
   - Production deployment uses: `docker compose --env-file /etc/cleaning/cleaning.env`

3. **Direct os.environ usage** (rare):
   - `backend/app/main.py:233` - pytest detection only
   - `backend/tests/conftest.py` - test setup only

### Single Source of Truth Approach

**Recommended**: `/etc/cleaning/cleaning.env` with `--env-file` flag

```bash
# Deploy command
docker compose --env-file /etc/cleaning/cleaning.env up -d --force-recreate

# Compose file (docker-compose.yml)
services:
  api:
    env_file: .env  # This reads from --env-file path when specified
  jobs:
    env_file: .env
  db:
    environment:
      POSTGRES_DB: ${POSTGRES_DB}      # Interpolated from env file
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
```

**Why this works**:
- `--env-file` makes variables available for ${VAR} interpolation in compose.yml
- `env_file: .env` in services passes variables into container environment
- Single file to manage, no duplication

---

## Tools

### Environment Audit Script

Run `ops/env_audit.py` to detect:
- Missing MUST keys
- Placeholder values (CHANGE_ME, example, etc.)
- Unused keys in environment
- Configuration mismatches

**Usage**:
```bash
python3 ops/env_audit.py --env /etc/cleaning/cleaning.env
python3 ops/env_audit.py --env /etc/cleaning/cleaning.env --verbose
python3 ops/env_audit.py --env /etc/cleaning/cleaning.env --check-unused
```

**Exit codes**:
- `0` = OK (all MUST keys present, no placeholders)
- `1` = Warnings only (optional missing, unused keys)
- `2` = Errors (missing MUST keys or placeholder detected)

---

## References

- Settings source: `backend/app/settings.py` (Pydantic BaseSettings)
- Production validation: `backend/app/settings.py:232-319` (validate_prod_settings)
- Docker compose: `docker-compose.yml`
- Example env: `backend/.env.production.example`
- Tests: `backend/tests/test_prod_config_validation.py`
- Storage factory: `backend/app/infra/storage/__init__.py`
- Email factory: `backend/app/infra/email.py`
- Captcha: `backend/app/infra/captcha.py`
