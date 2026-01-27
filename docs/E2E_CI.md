# CI/E2E Admin Auth Helper

CI runs with `ADMIN_PROXY_AUTH_ENABLED=true`, so every `/v1/admin/*` call must include proxy
identity headers and an MFA assertion. The workflow uses the signed proxy helper to avoid
unauthenticated admin probes.

## Helper script

`backend/scripts/e2e_admin_probe.py` builds signed admin headers and calls `/v1/admin/profile`.

Required env vars:
- `ADMIN_PROXY_AUTH_SECRET`
- `ADMIN_PROXY_AUTH_E2E_SECRET`
- `ADMIN_PROXY_AUTH_E2E_USER`
- `ADMIN_PROXY_AUTH_E2E_EMAIL`
- `ADMIN_PROXY_AUTH_E2E_ROLES`

The helper always sends:
- `X-Proxy-Auth-Secret`
- `X-Auth-MFA: true`
- `X-E2E-Admin-User`
- `X-E2E-Admin-Email`
- `X-E2E-Admin-Roles`
- `X-E2E-Proxy-Timestamp`
- `X-E2E-Proxy-Signature`

## Why this exists

Admin endpoints reject unauthenticated requests when proxy auth is enabled. CI must not
probe `/v1/admin/profile` without the signed proxy headers or MFA assertion.
