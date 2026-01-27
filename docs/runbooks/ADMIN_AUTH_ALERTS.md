# Admin Authentication Alerts Runbook

This runbook covers alerts for admin authentication anomalies and abuse detection.

## Alerts

### AdminAuthFailuresHigh (warning)
**Trigger:** `admin_auth_failure_total` spikes (default: >10 failures in 10 minutes).

**Why it matters:** Elevated failures can indicate credential stuffing, proxy misconfiguration, or targeted probing of admin endpoints.

**Immediate checks**
- Review structured logs for `event=admin_auth_attempt` with `outcome=failure` and inspect `failure_reason`, `source_ip`, `source_cidr`, and `auth_method`.
- Confirm the reverse proxy is enforcing MFA and forwarding the correct headers.

**Response actions**
1. Validate whether the source CIDR belongs to a known admin or corporate network.
2. If suspicious, block the CIDR at the edge and rotate the proxy shared secret.
3. Check for correlated alerts: `AdminAuthSuccessNoMFA`, `AdminBreakGlassUsed`, or `AdminAuthNewCIDR`.

**PromQL quick checks**
- `sum by (reason) (increase(admin_auth_failure_total[15m]))`
- `sum by (source_cidr) (increase(admin_auth_failure_total[15m]))`

---

### AdminAuthSuccessNoMFA (critical)
**Trigger:** `admin_auth_success_total{mfa="false"}` increases.

**Why it matters:** MFA is required for admin access. A success without MFA indicates a policy bypass or proxy header tampering.

**Immediate checks**
- Identify the request in logs (`mfa=false`, `auth_method`, `source_ip`, `source_cidr`).
- Confirm IdP/access policy enforcement for MFA.

**Response actions**
1. Immediately disable admin proxy access by setting `ADMIN_PROXY_AUTH_REQUIRED=true` and rotating `ADMIN_PROXY_AUTH_SECRET`.
2. Confirm the IdP policy enforces MFA for all admin groups and devices.
3. Require re-authentication for all active admin sessions.

**PromQL quick checks**
- `sum by (method, source_cidr) (increase(admin_auth_success_total{mfa="false"}[1h]))`

---

### AdminBreakGlassUsed (critical)
**Trigger:** `admin_break_glass_total` increases.

**Why it matters:** Break-glass access is for emergency use only and requires incident tracking.

**Immediate checks**
- Confirm a corresponding incident ticket exists.
- Review admin auth logs for `break_glass=true` and ensure the usage was authorized.

**Response actions**
1. Validate approval and scope of break-glass access.
2. Ensure break-glass access is revoked after the task is complete.
3. Perform post-incident review (who/what/why/when).

**PromQL quick checks**
- `increase(admin_break_glass_total[1h])`

---

### AdminAuthNewCIDR (warning)
**Trigger:** A new `source_cidr` is observed within 15 minutes that had no activity in the prior 30 days.

**Why it matters:** Admin access from a new network can indicate compromised credentials or travel.

**Immediate checks**
- Identify the source CIDR and admin user from logs (`source_cidr`, `admin_user`, `auth_method`).
- Verify the admin’s expected location and corporate VPN usage.

**Response actions**
1. Confirm the login is expected with the admin user or their manager.
2. If unexpected, rotate credentials and investigate for additional suspicious activity.
3. Update the IP allowlist if this CIDR is newly approved.

**PromQL quick checks**
- `sum by (source_cidr) (increase(admin_auth_success_total[30d]))`

---

## Simulation / Validation

To verify alerting behavior in lower environments:

1. **Failure spike**: send repeated invalid auth attempts to `/v1/admin/*` to increment `admin_auth_failure_total`.
2. **No MFA success**: temporarily disable MFA header injection in a staging proxy and authenticate (use controlled accounts only).
3. **Break-glass**: trigger an admin auth request with `break_glass=true` in staging (ensure the break-glass toggle is enabled).
4. **New CIDR**: authenticate from a new VPN exit or IP range not seen in the last 30 days.

Ensure all simulations are tracked in a test incident ticket and cleaned up afterward.
