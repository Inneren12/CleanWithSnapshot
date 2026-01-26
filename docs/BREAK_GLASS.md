# Break-glass emergency access

Break-glass grants are **time-bound**, **audited**, and **reviewed** emergency access sessions used to override admin read-only protections during incidents.

## Activation

**Requirements**

* Allowed roles: owner or security.
* MFA must be verified for roles configured in `admin_mfa_required_roles`.
* Provide an incident/ticket reference and a reason.

**Request**

`POST /v1/admin/break-glass/start`

```json
{
  "reason": "Mitigate production outage",
  "incident_ref": "INC-12345",
  "scope": "org",
  "ttl_minutes": 45
}
```

**Response**

```json
{
  "token": "<break-glass-token>",
  "expires_at": "2024-05-01T12:30:00Z",
  "session_id": "9d3f0a98-7f4d-4f1e-9d47-1e2c3c5d6e7f"
}
```

## Usage

Include the break-glass token in admin requests while the grant is active:

```
X-Break-Glass-Token: <break-glass-token>
```

Every elevated request emits an immutable audit log with the request ID, incident reference, and session ID.

## Revoke (manual)

`POST /v1/admin/break-glass/{session_id}/revoke`

```json
{
  "reason": "Incident resolved; rollback complete."
}
```

Manual revocation ends access immediately and produces an audit log entry.

## Review & closure

After the incident (and after the session is expired or revoked), the break-glass session **must** be reviewed and closed.

`POST /v1/admin/break-glass/{session_id}/review`

```json
{
  "review_notes": "Reviewed logs and verified changes were authorized. No follow-up actions needed."
}
```

Review completion is required for governance reporting and is recorded in access review evidence bundles.

## Configuration

* `break_glass_default_ttl_minutes` (default 30)
* `break_glass_max_ttl_minutes` (default 60)
* `admin_mfa_required` + `admin_mfa_required_roles`

## Audit & alerting

* Audit logs are immutable and capture grant creation, use, revocation, expiry, and review.
* Prometheus metrics:
  * `break_glass_grants_total{scope,event}`
  * `break_glass_active`
* Alerts:
  * `BreakGlassActivated`
  * `BreakGlassStillActiveTooLong`
