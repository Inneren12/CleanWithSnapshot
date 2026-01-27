# Environment Security Policy

This document defines how application environments handle secrets and configuration validation.

## APP_ENV values

Supported values for `APP_ENV` are:

- `prod`
- `staging`
- `dev`
- `ci`
- `e2e`
- `test`
- `local`

## Secure environments (prod-like)

The following environments are treated as **secure** and must be configured with real secrets:

- `prod`
- `staging`

Policy:

- No default development secrets are applied.
- Startup validation fails if required secrets are missing or set to known defaults.
- Secret requirements mirror production enforcement.

## Dev-like environments

The following environments are **dev-like** and may use defaults intentionally for local or automated runs:

- `dev`
- `ci`
- `e2e`
- `test`
- `local`

Policy:

- If secrets are omitted, the application explicitly fills non-production defaults (e.g., `dev-auth-secret`).
- These defaults are **not** permitted in secure environments.

## Secret environment variable mapping

Secrets are read from explicit environment variable names (with legacy field-name aliases accepted for backward
compatibility):

- `AUTH_SECRET_KEY` (legacy: `auth_secret_key`)
- `CLIENT_PORTAL_SECRET` (legacy: `client_portal_secret`)
- `WORKER_PORTAL_SECRET` (legacy: `worker_portal_secret`)

Set the uppercase names in production and staging to ensure audit-friendly configuration.
