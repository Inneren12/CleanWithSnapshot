# Trusted Proxy IP – Client IP Resolution

## Overview

The API uses the direct TCP connection source address (`request.client.host`)
as the authoritative client identity for rate limiting and audit logging.

When the API sits behind a reverse proxy (Caddy), the proxy sets
`X-Forwarded-For` or the RFC 7239 `Forwarded` header to carry the real client
IP. **These headers can be freely forged by any client**, so the API only
trusts them when the packet originates from a known, trusted proxy.

The environment variable `TRUSTED_PROXY_CIDRS` controls which source addresses
are trusted to supply forwarded-header data.

---

## Configuration

```
# .env / environment
TRUSTED_PROXY_CIDRS=172.18.0.0/16,172.19.0.0/16
```

| Value | Behaviour |
|-------|-----------|
| *(empty / unset)* | **Never** trust forwarded headers. Always use `request.client.host`. |
| One or more CIDRs | Trust forwarded headers **only** when the TCP source IP matches a listed CIDR. |

### Resolution logic (`get_client_ip`)

```
source_ip = TCP connection source (request.client.host)

if source_ip NOT in TRUSTED_PROXY_CIDRS:
    return source_ip          # spoof attempt – ignored

# Source is a trusted proxy; inspect headers in priority order:
1. RFC 7239 Forwarded: parse left-most "for=" value
2. X-Forwarded-For:    take left-most IP

if extracted IP is valid:
    return extracted IP
else:
    return source_ip          # malformed header – safe fallback
```

Header values are validated with `ipaddress.ip_address`. Malformed values,
oversized headers (> 2 048 bytes) and excessively long hop chains (> 20 hops)
all fall back to `source_ip`.

---

## Recommended Caddy Setup

Caddy communicates with the API container over the internal Docker network.
The API should trust **only** the Caddy container's subnet – **never** ranges
reachable from the public internet.

### 1. Identify the Docker bridge subnet

With the default Compose network:

```bash
docker network inspect cleanwithsnapshot_default \
  | python3 -m json.tool | grep Subnet
```

The subnet is typically `172.18.0.0/16` (or similar). Caddy's IP is one
address in that range.

### 2. Set `TRUSTED_PROXY_CIDRS` in the API container

```bash
# docker-compose.yml  ─  api service
environment:
  TRUSTED_PROXY_CIDRS: "172.18.0.0/16"
```

Use the narrowest CIDR that covers only your Caddy container(s). Prefer a
`/24` or `/32` over a wider `/16` if you can pin the address.

### 3. Caddy automatically forwards the client IP

Caddy sets `X-Forwarded-For` by default when proxying. No extra Caddyfile
directive is needed for standard single-hop setups.

If you need RFC 7239 `Forwarded` header instead:

```
reverse_proxy api:8000 {
  header_up Forwarded "for={remote_host}"
}
```

> **Do not** set both `X-Forwarded-For` and `Forwarded` from Caddy.
> The API prefers `Forwarded` when both are present.

---

## Which CIDRs to Trust

| Trust | Why |
|-------|-----|
| Docker internal bridge (`172.x.x.x/16`) | Your Caddy container |
| Local loopback (`127.0.0.0/8`, `::1/128`) | Only if API is accessed locally without Caddy |
| **Public internet ranges** | **Never** – any client can forge forwarded headers |
| `0.0.0.0/0` | **Never** – defeats the entire mechanism |

In a typical single-server deployment with Caddy and the API on the same
Docker network, only the Docker bridge CIDR is needed:

```
TRUSTED_PROXY_CIDRS=172.18.0.0/16
```

---

## Warning: Do Not Trust Public Addresses

> **CRITICAL**: Never add a public IP range to `TRUSTED_PROXY_CIDRS`.
>
> If an attacker can reach the API directly (bypassing Caddy), they will also
> be able to supply arbitrary `X-Forwarded-For` / `Forwarded` headers, which
> the API will then honour as the authoritative client IP. This allows them to:
>
> - Impersonate any IP address for rate-limit bypasses.
> - Poison audit logs with fake client identities.
>
> Restrict inbound traffic to the API port (`8000`) to the internal Docker
> network only. Expose only ports `80` and `443` via Caddy.

Recommended `docker-compose.yml` port binding for the API service:

```yaml
services:
  api:
    # Do NOT publish port 8000 to the host.
    # Caddy reaches the API through the internal Docker network.
    expose:
      - "8000"
```

---

## Migration from `TRUST_PROXY_HEADERS` + `TRUSTED_PROXY_IPS`

The legacy `TRUST_PROXY_HEADERS=true` / `TRUSTED_PROXY_IPS=…` pair is still
supported by `resolve_client_key` (used for admin auth and the client portal).
For the main rate-limiting middleware, only `TRUSTED_PROXY_CIDRS` is
consulted.

Migrate individual IPs to `/32` (IPv4) or `/128` (IPv6) CIDRs:

```
# Before
TRUST_PROXY_HEADERS=true
TRUSTED_PROXY_IPS=172.18.0.5

# After
TRUSTED_PROXY_CIDRS=172.18.0.5/32
```

---

## Related Docs

- [SECURITY_RATE_LIMITS.md](../SECURITY_RATE_LIMITS.md) – per-client and per-org rate limits
- [SECURITY_ADMIN_AUTH.md](../SECURITY_ADMIN_AUTH.md) – admin proxy auth headers
- [CONTAINER_SECURITY.md](../CONTAINER_SECURITY.md) – network isolation
