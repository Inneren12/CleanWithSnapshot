# Admin IP allowlist (proxy enforcement)

## Status (current)

* **Allowlist enforcement** is implemented at the reverse proxy (Caddy) for `/v1/admin/*` routes.
* **Initial posture:** a **static list is not required** at the start. The allowlist can be **empty** while onboarding; this is acceptable for early-stage operations because MFA + proxy auth are still enforced and all access is logged.
* **Current status:** when enabled, the list is expected to begin with **a single operator IP** and expand as needed.
* **Operator IPs are dynamic:** the allowlist is expected to change as operators travel or rotate networks.

This document defines how to enable and manage the allowlist without hardcoding IPs.

---

## Why an empty initial allowlist is acceptable

* The proxy **already enforces MFA + Basic Auth** for all admin routes before forwarding to the backend.
* All admin actions are **audited** and tied to an authenticated identity.
* The allowlist can be enabled and tightened incrementally without disrupting break-glass procedures.

This approach is audit-safe because it documents the staged rollout plan and retains strong identity controls while the network perimeter is being finalized.

---

## Enabling the allowlist

The allowlist is enabled when `ADMIN_ALLOWED_IPS` is **non-empty**. When enabled:

* Only IPs/CIDRs in the list (plus `127.0.0.1` and `::1`) can access `/v1/admin/*`.
* Requests with a valid `X-Break-Glass-Token` bypass the allowlist to prevent emergency access lockout.

**Caddy environment variable**

```bash
# Comma/space-separated list of IPs or CIDRs.
# Example: "203.0.113.10 198.51.100.0/24"
ADMIN_ALLOWED_IPS=""
```

**Apply changes** (example):

```bash
# Update your env file, then restart Caddy to apply.
docker compose restart caddy
```

---

## Updating the allowlist (dynamic / temporary)

### Add or remove IPs

1. Update `ADMIN_ALLOWED_IPS` in the environment file used by the Caddy container.
2. Restart Caddy to apply changes.
3. Record the change in the access log or change ticket (who/why/when).

### Temporary IPs with expiry (manual)

To allow travel or emergency access:

1. Add the temporary IP/CIDR to `ADMIN_ALLOWED_IPS` with an **explicit expiry** in the change ticket.
2. Set a calendar reminder to remove it before expiration.
3. After expiry, remove the IP and restart Caddy.

This workflow is considered acceptable because the allowlist is **operationally managed**, auditable, and time-bound.

---

## Break-glass exception (must not be blocked)

Break-glass access is **time-bound**, **MFA-protected**, and **audited**. The proxy allowlist supports emergency access by:

* Allowing requests with `X-Break-Glass-Token` to bypass the IP allowlist.
* Requiring standard proxy authentication + MFA for all admin routes.

**Break-glass workflow (summary)**

1. Obtain approval and start a break-glass session (`POST /v1/admin/break-glass/start`).
2. Use the returned `X-Break-Glass-Token` for time-bound elevated requests.
3. Revoke and review the session after the incident.

Refer to the break-glass policy for full details.

---

## Future tightening plan

1. **Phase 1 (now):** keep `ADMIN_ALLOWED_IPS` empty or limited to the primary operator IP.
2. **Phase 2:** require allowlist for all admin access; add VPN/bastion IP ranges.
3. **Phase 3:** enforce a dedicated access gateway with short-lived device certificates and automated IP rotation.

This staged approach keeps operations flexible while progressively tightening network controls.
