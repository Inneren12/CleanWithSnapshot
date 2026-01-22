# OBS-202 Grafana access controls

## Summary

Grafana is only exposed on localhost by default via Docker port binding:

- `127.0.0.1:3001:3000` in `docker-compose.observability.yml`

This ensures Grafana is unreachable from the public internet unless an explicit reverse proxy route is configured.

## Verify localhost-only binding

```bash
ss -ltnp | grep 3001 || true
```

You should see Grafana bound to `127.0.0.1:3001`.

## Optional: Caddy reverse proxy access

A `/grafana/*` route is available in the `Caddyfile` and is locked down by an IP allowlist.

### IP allowlist (default)

Set `GRAFANA_ALLOWED_IPS` to a space-separated list of allowed IPs or CIDRs. Requests not on the allowlist receive `403`.

```bash
export GRAFANA_ALLOWED_IPS="203.0.113.10 198.51.100.0/24"
```

If `GRAFANA_ALLOWED_IPS` is unset, only localhost (`127.0.0.1` / `::1`) is allowed.

### Optional BasicAuth (reverse proxy)

If you prefer BasicAuth instead of (or in addition to) the allowlist, uncomment the `basicauth` block
in the `/grafana/*` route and provide credentials via environment variables.

```bash
export GRAFANA_BASIC_AUTH_USER="grafana"
export GRAFANA_BASIC_AUTH_HASH="$(caddy hash-password --plaintext 'replace-me')"
```

> Do not commit credentials or hashes to the repository.

## Notes

- Grafana remains bound to localhost even when proxied; Caddy is the only public entry point.
- Keep the proxy route disabled unless remote access is required.
