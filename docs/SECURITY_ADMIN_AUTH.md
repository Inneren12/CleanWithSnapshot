# Admin Authentication Security Guide

This document describes the admin authentication architecture, trust boundaries, and operational procedures for the cleaning economy platform.

## Table of Contents

1. [Overview](#overview)
2. [Authentication Modes](#authentication-modes)
3. [Proxy Authentication Architecture](#proxy-authentication-architecture)
4. [Configuration](#configuration)
5. [Trust Boundary](#trust-boundary)
6. [Rollback Instructions](#rollback-instructions)
7. [Security Considerations](#security-considerations)

---

## Overview

Admin authentication has two modes:

1. **Legacy Basic Auth** (deprecated) — Credentials verified in the backend
2. **Proxy Authentication** (recommended) — Credentials verified at the reverse proxy, backend trusts proxy headers

Proxy authentication provides better security by:
- Moving credential verification to the edge (reverse proxy)
- Enabling MFA/SSO/IP controls without backend changes
- Reducing the attack surface of the backend
- Allowing centralized authentication policy management

---

## Authentication Modes

### Legacy Basic Auth

| Setting | Value |
|---------|-------|
| `LEGACY_BASIC_AUTH_ENABLED` | `true` |
| `ADMIN_PROXY_AUTH_ENABLED` | `false` |

Backend verifies credentials directly using environment variables:
- `ADMIN_BASIC_USERNAME` / `ADMIN_BASIC_PASSWORD`
- `OWNER_BASIC_USERNAME` / `OWNER_BASIC_PASSWORD`
- `DISPATCHER_BASIC_USERNAME` / `DISPATCHER_BASIC_PASSWORD`
- `ACCOUNTANT_BASIC_USERNAME` / `ACCOUNTANT_BASIC_PASSWORD`
- `VIEWER_BASIC_USERNAME` / `VIEWER_BASIC_PASSWORD`

**Warning**: This mode is deprecated and disabled by default in production.

### Proxy Authentication

| Setting | Value |
|---------|-------|
| `ADMIN_PROXY_AUTH_ENABLED` | `true` |
| `ADMIN_PROXY_AUTH_REQUIRED` | `true` (recommended) |
| `ADMIN_PROXY_AUTH_SECRET` | `<32+ character secret>` |

Reverse proxy authenticates users and injects trusted headers. Backend validates the shared secret and trusts the proxy headers.

---

## Proxy Authentication Architecture

### Request Flow

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Browser   │────▶│  Reverse Proxy   │────▶│    Backend      │
│             │     │  (Caddy/nginx)   │     │    (FastAPI)    │
└─────────────┘     └──────────────────┘     └─────────────────┘
       │                    │                        │
       │  1. Basic Auth     │                        │
       │  Authorization:    │                        │
       │  Basic base64...   │                        │
       └───────────────────▶│                        │
                            │  2. Verify creds       │
                            │  (bcrypt hash check)   │
                            │                        │
                            │  3. Strip Auth header  │
                            │  Add trusted headers:  │
                            │  - X-Admin-User        │
                            │  - X-Admin-Roles       │
                            │  - X-Proxy-Auth-Secret │
                            └───────────────────────▶│
                                                     │  4. Verify secret
                                                     │  Create AdminIdentity
                                                     │  from headers
```

### Headers Injected by Proxy

| Header | Description | Required |
|--------|-------------|----------|
| `X-Admin-User` | Authenticated username | Yes |
| `X-Admin-Email` | User's email address | No |
| `X-Admin-Roles` | Comma-separated roles (e.g., `owner,admin`) | No (defaults to `viewer`) |
| `X-Proxy-Auth-Secret` | Shared secret for verification | Yes |

### Role Hierarchy

Roles are evaluated in priority order. If multiple roles are provided, the highest-privilege role is used:

1. `owner` — Full administrative access
2. `admin` — Administrative access
3. `dispatcher` — View + dispatch operations
4. `accountant` / `finance` — View + financial operations
5. `viewer` — Read-only access

---

## Configuration

### Backend Environment Variables

```bash
# Enable proxy authentication
ADMIN_PROXY_AUTH_ENABLED=true

# Require proxy authentication (blocks direct access)
ADMIN_PROXY_AUTH_REQUIRED=true

# Shared secret (must match proxy configuration, min 32 chars in prod)
ADMIN_PROXY_AUTH_SECRET=your-very-long-and-secure-shared-secret-here

# Header names (optional, defaults shown)
ADMIN_PROXY_AUTH_HEADER_USER=X-Admin-User
ADMIN_PROXY_AUTH_HEADER_EMAIL=X-Admin-Email
ADMIN_PROXY_AUTH_HEADER_ROLES=X-Admin-Roles

# Disable legacy Basic Auth (recommended)
LEGACY_BASIC_AUTH_ENABLED=false
```

### Caddy Configuration

```caddyfile
# Generate password hashes: caddy hash-password --plaintext 'your-password'

@admin path /v1/admin /v1/admin/*
handle @admin {
    basicauth {
        owner {env.ADMIN_PROXY_AUTH_HASH_OWNER}
        admin {env.ADMIN_PROXY_AUTH_HASH_ADMIN}
        dispatcher {env.ADMIN_PROXY_AUTH_HASH_DISPATCHER}
        accountant {env.ADMIN_PROXY_AUTH_HASH_ACCOUNTANT}
        viewer {env.ADMIN_PROXY_AUTH_HASH_VIEWER}
    }

    # Strip original auth header
    request_header -Authorization

    # Inject trusted headers
    request_header X-Admin-User {http.auth.user.id}
    request_header X-Admin-Roles {http.auth.user.id}
    request_header X-Proxy-Auth-Secret {env.ADMIN_PROXY_AUTH_SECRET}

    reverse_proxy api:8000
}
```

### Caddy Environment Variables

```bash
# Password hashes (bcrypt, generated with caddy hash-password)
ADMIN_PROXY_AUTH_HASH_OWNER=$2a$14$...
ADMIN_PROXY_AUTH_HASH_ADMIN=$2a$14$...
ADMIN_PROXY_AUTH_HASH_DISPATCHER=$2a$14$...
ADMIN_PROXY_AUTH_HASH_ACCOUNTANT=$2a$14$...
ADMIN_PROXY_AUTH_HASH_VIEWER=$2a$14$...

# Shared secret (must match backend configuration)
ADMIN_PROXY_AUTH_SECRET=your-very-long-and-secure-shared-secret-here
```

### Generating Password Hashes

```bash
# Generate bcrypt hash for Caddy basicauth
caddy hash-password --plaintext 'your-secure-password'

# Output: $2a$14$...
```

---

## Trust Boundary

### What the Backend Trusts

The backend trusts proxy headers **only when**:
1. `ADMIN_PROXY_AUTH_ENABLED=true`
2. The `X-Proxy-Auth-Secret` header matches `ADMIN_PROXY_AUTH_SECRET`
3. The `X-Admin-User` header is present and non-empty

### Security Invariants

1. **No credentials in backend**: The backend never sees or validates passwords when proxy auth is enabled
2. **Secret verification**: Every request with proxy headers must include the correct shared secret
3. **Header stripping**: The proxy strips the `Authorization` header before forwarding to prevent credential leakage
4. **Direct access blocked**: When `ADMIN_PROXY_AUTH_REQUIRED=true`, requests without valid proxy headers are rejected with 401

### Attack Vectors Mitigated

| Attack | Mitigation |
|--------|------------|
| Direct backend access bypassing proxy | `ADMIN_PROXY_AUTH_REQUIRED=true` blocks requests without valid proxy headers |
| Header injection | Shared secret verification prevents spoofed headers |
| Credential theft from backend | Backend never handles credentials |
| Timing attacks on password verification | Verification happens at proxy level with battle-tested libraries |

---

## Rollback Instructions

If proxy authentication needs to be disabled (e.g., proxy misconfiguration):

### Emergency Rollback (30 seconds)

1. Set environment variables:
   ```bash
   ADMIN_PROXY_AUTH_ENABLED=false
   ADMIN_PROXY_AUTH_REQUIRED=false
   LEGACY_BASIC_AUTH_ENABLED=true
   ```

2. Ensure legacy credentials are configured:
   ```bash
   ADMIN_BASIC_USERNAME=admin
   ADMIN_BASIC_PASSWORD=your-secure-password
   ```

3. Restart the backend service:
   ```bash
   docker compose restart api
   ```

### Full Rollback

1. Update environment configuration
2. Revert Caddyfile changes (remove the `@admin` handler)
3. Restart Caddy and backend:
   ```bash
   docker compose restart caddy api
   ```

### Verification After Rollback

```bash
# Test Basic Auth works
curl -u admin:your-password https://api.example.com/v1/admin/profile

# Expected: 200 OK with admin profile JSON
```

---

## Security Considerations

### Secrets Management

- Use a secrets manager (e.g., HashiCorp Vault, AWS Secrets Manager) for production
- Rotate `ADMIN_PROXY_AUTH_SECRET` periodically
- Use strong, unique passwords for each admin user

### Network Security

- Ensure the backend is not directly accessible from the internet
- Use internal network or localhost for backend-proxy communication
- Consider IP allowlisting at the proxy level

### Monitoring

Monitor for:
- Failed proxy auth attempts (`admin_proxy_auth_invalid_secret` log events)
- Missing proxy headers (`admin_proxy_auth_required_missing_headers` log events)
- Unusual admin access patterns

### Audit Trail

All admin actions are logged in the `admin_audit_logs` table, including:
- Username (from `X-Admin-User` header)
- Role (from `X-Admin-Roles` header)
- Action performed
- Timestamp

---

## Migration Checklist

### Before Migration

- [ ] Generate password hashes for all admin users using `caddy hash-password`
- [ ] Generate a secure shared secret (32+ characters)
- [ ] Update Caddy configuration with admin route handler
- [ ] Test in staging environment

### During Migration

- [ ] Set `ADMIN_PROXY_AUTH_ENABLED=true`
- [ ] Set `ADMIN_PROXY_AUTH_SECRET` in both Caddy and backend
- [ ] Restart Caddy first, then backend
- [ ] Verify admin login works through proxy

### After Migration

- [ ] Set `ADMIN_PROXY_AUTH_REQUIRED=true` to block direct access
- [ ] Set `LEGACY_BASIC_AUTH_ENABLED=false`
- [ ] Remove legacy credential environment variables
- [ ] Monitor logs for authentication issues

---

## Troubleshooting

### 401 Unauthorized

1. **Check shared secret**: Ensure `ADMIN_PROXY_AUTH_SECRET` matches in proxy and backend
2. **Check headers**: Verify proxy is injecting `X-Admin-User` and `X-Proxy-Auth-Secret`
3. **Check logs**: Look for `admin_proxy_auth_*` log entries

### 403 Forbidden

1. **Check role**: Ensure the role has sufficient permissions for the action
2. **Check header format**: Roles should be comma-separated without spaces

### Direct Access Still Working

1. **Check `ADMIN_PROXY_AUTH_REQUIRED`**: Must be `true` to block direct access
2. **Restart backend**: Configuration changes require restart
