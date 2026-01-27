# Admin Authentication Audit Logging & Anomaly Detection

This document describes how admin authentication attempts are audited, how to query the logs/metrics, and which alerts are configured for early anomaly detection.

## What is logged

Every admin authentication attempt emits a structured log event with the following fields (PII is redacted by the log formatter):

- `event`: `admin_auth_attempt`
- `outcome`: `success` or `failure`
- `failure_reason`: standardized enum (see below)
- `failure_reason_detail`: raw internal reason (for debugging)
- `timestamp`: emitted by the logging pipeline
- `source_ip`: client IP resolved from trusted proxy headers
- `user_agent`
- `admin_user`
- `admin_email` (redacted)
- `role`: highest-privilege role
- `roles`: list of roles from proxy headers or basic auth
- `auth_method`: `proxy`, `e2e`, `basic`, or `bearer` (denied)
- `mfa`: `true` or `false`
- `proxy_trusted`: whether the proxy IP is trusted
- `break_glass`: whether a break-glass header/session was present
- `request_id`, `path`, `method`

### Standardized failure reasons

All failure logs include `failure_reason` with one of:

- `untrusted_proxy`
- `proxy_auth_required`
- `bad_signature`
- `mfa_required`
- `invalid_credentials`
- `rate_limited`

## How to query

### Log queries (examples)

- All admin auth failures in the last hour:
  - `event="admin_auth_attempt" outcome="failure"`
- MFA required failures:
  - `event="admin_auth_attempt" failure_reason="mfa_required"`
- Break-glass usage correlated with auth:
  - `event="admin_auth_attempt" break_glass=true`

### Detecting admin login from a new IP (log-based)

Use your SIEM/log pipeline to detect first-seen IPs for each admin identity. Example logic:

1. Group by `admin_user`.
2. Maintain a rolling 30-day list of `source_ip` values per admin.
3. Alert when a `source_ip` appears for a user that is not in the rolling list.

**TODO:** Wire this query into the log-based alerting pipeline (e.g., Better Stack/SIEM) once the log index is configured for admin auth events.

## Metrics

The following Prometheus metric is emitted for admin auth attempts:

- `admin_auth_events_total{outcome,method,mfa,reason}`
  - `outcome`: `success` / `failure`
  - `method`: `proxy` / `e2e` / `basic` / `bearer` / `unknown`
  - `mfa`: `true` / `false` / `unknown`
  - `reason`: standardized failure reason or `none` for successful attempts

## Alerts

### Prometheus alerts

- **AdminAuthFailuresHigh**: fires when more than 10 admin auth failures occur in 10 minutes.
- **AdminAuthSuccessNoMFA**: fires if any admin auth succeeds without MFA.
- **BreakGlassActivated / BreakGlassStillActiveTooLong**: fires on break-glass session creation or prolonged activation.

### Log-based alerts

- **AdminLoginFromNewIP**: alert on first-seen IPs for an admin identity (see query above).

## Expected operator response

1. **AdminAuthFailuresHigh**
   - Triage failed attempts by `source_ip`, `admin_user`, and `failure_reason`.
   - Confirm whether attempts align with known admin activity or indicate abuse.
   - Escalate to incident response if failures are unexpected or persistent.

2. **AdminAuthSuccessNoMFA**
   - Validate proxy/IdP policy enforcement for MFA.
   - Check if any temporary exceptions exist and revoke them.
   - Rotate admin proxy secrets if tampering is suspected.

3. **AdminLoginFromNewIP**
   - Contact the admin to confirm the login.
   - Review the source IP for reputation and geolocation anomalies.
   - Require credential rotation and session revocation if suspicious.

4. **BreakGlass alerts**
   - Ensure incident ticketing is active and a post-incident review is scheduled.
   - Revoke break-glass access immediately if it is no longer needed.
