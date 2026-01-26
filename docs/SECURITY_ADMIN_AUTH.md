# Admin Authentication at the Edge

## Overview

Admin authentication is enforced at the reverse proxy (edge). The backend does **not** validate
admin passwords; it only trusts proxy-injected headers after verifying the request originated
from a trusted proxy IP/CIDR. Direct access to `/v1/admin/*` without proxy headers is rejected.

## Auth Flow

1. Admin connects to the edge (Caddy/SSO/Access provider).
2. Edge authenticates the admin user (Basic, SSO, MFA, IP allowlists, device posture, etc.).
3. Edge forwards the request to the backend and injects trusted headers:
   - `X-Admin-User`
   - `X-Admin-Email`
   - `X-Admin-Roles` (optional)
   - `X-Proxy-Auth: 1`
4. Backend validates the request came from a trusted proxy and requires the headers.
5. Backend authorizes based on the role and processes the request.

## Trust Boundary

The backend accepts admin headers **only** if:

- `TRUST_PROXY_HEADERS=true`
- The request `client.host` is in `TRUSTED_PROXY_IPS` or `TRUSTED_PROXY_CIDRS`
- `X-Admin-User` or `X-Admin-Email` is present
- `X-Proxy-Auth=1` is present

Any direct call to `/v1/admin/*` that does not meet the above is rejected with `401`.

### Required Backend Settings

- `ADMIN_PROXY_AUTH_ENABLED=true` (default)
- `TRUST_PROXY_HEADERS=true`
- `TRUSTED_PROXY_IPS` / `TRUSTED_PROXY_CIDRS` set to your edge proxy addresses

## Reverse Proxy Requirements

The proxy must:

- Authenticate admin users (Basic/SSO/Access provider)
- Strip any inbound `Authorization` headers for `/v1/admin/*`
- Inject `X-Admin-User`, `X-Admin-Email`, `X-Admin-Roles`, and `X-Proxy-Auth=1`

See `Caddyfile` for a working example.

## Rollback Instructions

If you need to temporarily roll back to legacy Basic Auth:

1. Disable proxy auth in the backend:
   - `ADMIN_PROXY_AUTH_ENABLED=false`
2. Re-enable legacy Basic Auth:
   - `LEGACY_BASIC_AUTH_ENABLED=true`
   - Set `ADMIN_BASIC_USERNAME` / `ADMIN_BASIC_PASSWORD` (or role-specific vars)
3. Remove/disable proxy header injection for `/v1/admin/*`

**Note:** This rollback reintroduces backend credential validation and should be treated as a
short-lived emergency measure.
