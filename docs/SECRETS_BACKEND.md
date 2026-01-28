# Secrets Backend Integration

This document describes how secrets are loaded for secure environments and how configuration precedence works.

## Precedence

Secrets backend configuration follows the same precedence as `Settings` sources:

1. Environment variables
2. `.env`/dotenv file

Environment variables always override `.env` values for the following keys:

- `SECRETS_BACKEND`
- `AWS_REGION` / `AWS_DEFAULT_REGION`
- `AWS_SECRETS_MANAGER_SECRET_ID`
- `AWS_SECRETS_MANAGER_SECRET_JSON`
- `AWS_SSM_PARAMETER_PATH`

## Supported backends

### AWS Secrets Manager

Required configuration:

- `SECRETS_BACKEND=aws_secrets_manager`
- `AWS_REGION`
- `AWS_SECRETS_MANAGER_SECRET_ID`

Optional (local/CI only): `AWS_SECRETS_MANAGER_SECRET_JSON` containing a JSON object with secrets.

Expected keys in the JSON payload:

- `AUTH_SECRET_KEY`
- `CLIENT_PORTAL_SECRET`
- `WORKER_PORTAL_SECRET`
- `ADMIN_PROXY_AUTH_SECRET`

### AWS SSM Parameter Store

Required configuration:

- `SECRETS_BACKEND=aws_ssm`
- `AWS_REGION`
- `AWS_SSM_PARAMETER_PATH` (e.g. `/cleanwithsnapshot/prod/`)

Parameters are loaded recursively and use the final path segment as the secret key (uppercased).

## Environment behavior

- **prod/staging:** secrets backend must be configured and required secrets must be present; startup fails fast.
- **dev/ci/e2e/test/local:** secrets backend is optional; if configured but missing required parameters, the loader
  logs a warning and defaults remain available.
