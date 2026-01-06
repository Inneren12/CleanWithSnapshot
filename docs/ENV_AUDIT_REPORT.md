# Environment Audit Report

## Source of truth and loading
- Backend settings are declared with Pydantic `BaseSettings` and default to reading an `.env` file in the backend build context; production should point that env file at `/etc/cleaning/cleaning.env` so all services share the same values.【F:backend/app/settings.py†L10-L197】
- Docker Compose currently injects `.env` into the `api` and `jobs` services; point that file to `/etc/cleaning/cleaning.env` for production and keep it consistent across `db`, `web`, and `caddy`.【F:docker-compose.yml†L1-L95】

## Env registry (key facts)
| KEY | Tier | Default | Component | Secret? | Where used | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| APP_ENV | MUST | `prod` | api/jobs | N | Validates prod-only settings on boot.【F:backend/app/settings.py†L13-L319】 | Must be `prod` in production to enforce secret checks and disable testing overrides. |
| DATABASE_URL | MUST | `postgresql+psycopg://postgres:postgres@postgres:5432/cleaning` | api/jobs | Y | DB session configuration.【F:backend/app/settings.py†L31-L35】 | Provide the live Postgres DSN; defaults point at the internal compose DB. |
| POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD | MUST | none | db | Y | Compose DB container config.【F:docker-compose.yml†L1-L15】 | Required for the Postgres service to start. |
| AUTH_SECRET_KEY | MUST | `dev-auth-secret` | api/jobs | Y | Required secret validation for prod.【F:backend/app/settings.py†L61-L289】 | Needs a long random value; prod boot fails if unset or default. |
| CLIENT_PORTAL_SECRET | MUST | `dev-client-portal-secret` | api/jobs | Y | Session signing for client portal.【F:backend/app/settings.py†L107-L295】 | Must be non-default; enforced in prod validation. |
| WORKER_PORTAL_SECRET | MUST | none | api/jobs | Y | Worker session signing.【F:backend/app/settings.py†L108-L295】 | Mandatory in prod; no default. |
| PUBLIC_BASE_URL | SHOULD | none | api/jobs | N | Base URL for links and emails.【F:backend/app/settings.py†L76-L78】 | Set to the canonical web origin to avoid broken links. |
| TRUST_PROXY_HEADERS | SHOULD | `False` | api/jobs | N | Client IP extraction for rate limiting.【F:backend/app/settings.py†L27-L337】 | Enable when running behind a reverse proxy; pair with trusted CIDRs/IPs. |
| STRICT_CORS / CORS_ORIGINS | SHOULD | `False` / empty | api/jobs | N | CORS enforcement.【F:backend/app/settings.py†L14-L305】 | In prod, STRICT_CORS requires explicit non-wildcard origins. |
| METRICS_ENABLED / METRICS_TOKEN | SHOULD (conditional MUST when enabled) | `True` / none | api/jobs | Y | Metrics endpoint auth.【F:backend/app/settings.py†L159-L307】【F:backend/app/main.py†L250-L261】 | If metrics are enabled, METRICS_TOKEN must be set to a strong value. |
| ADMIN_BASIC_USERNAME / ADMIN_BASIC_PASSWORD | SHOULD | none | api/jobs | Y | Break-glass admin auth path.【F:backend/app/settings.py†L45-L277】 | Optional unless `LEGACY_BASIC_AUTH_ENABLED=true`; avoid placeholder passwords. |
| CLIENT_PORTAL_BASE_URL | SHOULD | none | api/jobs | N | Portal link generation.【F:backend/app/settings.py†L109-L113】 | Set to the deployed worker/client portal domain. |
| EMAIL_MODE / SMTP_* / SENDGRID_API_KEY | OPTIONAL (conditional) | `off` | api/jobs | Y | Outbound email delivery configuration.【F:backend/app/settings.py†L36-L178】 | SMTP or Sendgrid fields become required if `EMAIL_MODE` selects them. |
| ORDER_STORAGE_BACKEND / S3_* / R2_* | OPTIONAL | `local` | api/jobs | Y | Upload storage backend configuration.【F:backend/app/settings.py†L116-L157】 | Required only if using S3/R2/Cloudflare storage. |
| JOBS_ENABLED / JOB_HEARTBEAT_REQUIRED / JOB_RUNNER_ID | OPTIONAL | `False` / `False` / none | jobs | N | Background job runner toggles.【F:backend/app/settings.py†L162-L167】 | Enable and configure heartbeat/token if running the jobs service. |
| METRICS_TOKEN (caddy/api exposure) | SHOULD | none | caddy/api | Y | Protects `/v1/metrics` endpoint.【F:backend/app/api/routes_metrics.py†L15-L18】 | Match the backend token to permit metrics scraping. |

## Template: minimal safe production env (/etc/cleaning/cleaning.env)
```
# Core runtime
APP_ENV=prod
DATABASE_URL=<postgresql+psycopg://user:pass@host:5432/db>
POSTGRES_DB=<db_name>
POSTGRES_USER=<db_user>
POSTGRES_PASSWORD=<db_password>

# Network & identity
PUBLIC_BASE_URL=https://app.example.com
TRUST_PROXY_HEADERS=true
STRICT_CORS=true
CORS_ORIGINS=["https://app.example.com","https://admin.example.com"]

# Auth secrets
AUTH_SECRET_KEY=<strong-random>
CLIENT_PORTAL_SECRET=<strong-random>
WORKER_PORTAL_SECRET=<strong-random>
CLIENT_PORTAL_BASE_URL=https://portal.example.com

# Metrics
METRICS_ENABLED=true
METRICS_TOKEN=<long-random>

# Break-glass basic auth (optional but secure if set)
ADMIN_BASIC_USERNAME=<admin_user>
ADMIN_BASIC_PASSWORD=<strong-password>
```

## Example alignment gaps
- Keys used in code but absent from `backend/.env.production.example` include admin safety toggles, rate-limit tuning, legacy basic auth controls, DLQ replay knobs, Cloudflare image settings, and proxy CIDR inputs.【650a1a†L1-L5】 Aligning the example with these keys avoids unused-key noise and ensures operators see all tunables.
- Keys present in the example but not parsed by code are the lower-cased list aliases (`CORS_ORIGINS`, `EXPORT_WEBHOOK_ALLOWED_HOSTS`, `TRUSTED_PROXY_CIDRS`, `TRUSTED_PROXY_IPS`).【650a1a†L3-L5】 Prefer the `*_RAW` variants already consumed by settings.

## Operational recommendations
- Keep `/etc/cleaning/cleaning.env` as the single source of truth and run compose with `--env-file /etc/cleaning/cleaning.env` so backend, jobs, and db share consistent secrets and URLs.【F:docker-compose.yml†L1-L52】
- Enable `TRUST_PROXY_HEADERS` and populate `TRUSTED_PROXY_IPS_RAW`/`TRUSTED_PROXY_CIDRS_RAW` when behind Caddy to ensure accurate client IPs for rate limiting and audit logs.【F:backend/app/settings.py†L27-L344】
- When `STRICT_CORS=true`, define explicit `CORS_ORIGINS` to prevent wildcard exposure.【F:backend/app/settings.py†L298-L305】
- If metrics remain enabled, set `METRICS_TOKEN` and keep it secret; the audit tool flags placeholders or missing tokens.【F:backend/app/settings.py†L159-L307】【F:ops/env_audit.py†L24-L220】
- Run `python3 ops/env_audit.py --env /etc/cleaning/cleaning.env` before deployments to catch missing MUST keys, placeholder secrets (e.g., the detected `ADMIN_BASIC_PASSWORD` placeholder), or stray unused keys without printing secret values.【F:ops/env_audit.py†L1-L258】
