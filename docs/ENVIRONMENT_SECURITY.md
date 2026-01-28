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
- `ADMIN_PROXY_AUTH_SECRET` (legacy: `admin_proxy_auth_secret`)

Set the uppercase names in production and staging to ensure audit-friendly configuration.

## Secrets backend (production)

Production and staging environments must load secrets from a managed backend via `SECRETS_BACKEND`. The application
fails fast if the backend is missing or if the required secrets are absent.

Supported backends:

- `aws_secrets_manager`
- `aws_ssm`

### AWS Secrets Manager

Store a single JSON secret containing the required keys:

```json
{
  "AUTH_SECRET_KEY": "...",
  "CLIENT_PORTAL_SECRET": "...",
  "WORKER_PORTAL_SECRET": "...",
  "ADMIN_PROXY_AUTH_SECRET": "..."
}
```

Configuration:

- `SECRETS_BACKEND=aws_secrets_manager`
- `AWS_REGION`
- `AWS_SECRETS_MANAGER_SECRET_ID`

Optional (for local testing only): `AWS_SECRETS_MANAGER_SECRET_JSON` with the JSON payload.

### AWS SSM Parameter Store

Store each secret as a SecureString under a shared path, for example:

```
/cleanwithsnapshot/prod/AUTH_SECRET_KEY
/cleanwithsnapshot/prod/CLIENT_PORTAL_SECRET
/cleanwithsnapshot/prod/WORKER_PORTAL_SECRET
/cleanwithsnapshot/prod/ADMIN_PROXY_AUTH_SECRET
```

Configuration:

- `SECRETS_BACKEND=aws_ssm`
- `AWS_REGION`
- `AWS_SSM_PARAMETER_PATH` (e.g. `/cleanwithsnapshot/prod/`)

## Secret lifecycle

### Where secrets live

- Primary storage is AWS Secrets Manager or AWS SSM Parameter Store (SecureString).
- Environment variables only reference the backend location (`SECRETS_BACKEND`, region, secret ID/path).

### How to rotate

1. Generate new values (min 32 characters, high entropy).
2. Update the secret in the chosen backend.
3. Deploy or restart the service to load the new values.
4. Validate auth flows and rotate any downstream integrations that depend on the secrets.

### Who has access

- Production secrets access is restricted to the platform/DevOps IAM role(s).
- Application runtime identity has read-only access to the specific secret path/ID.
- Human access is audited and limited to on-call or security-approved personnel.
