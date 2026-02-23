# PII Logging Policy for Authentication

## Purpose
Authentication responses returned to clients **must not include PII** (email addresses, usernames, or other user identifiers) or backend-only failure details.

## Requirements
- Client-visible authentication failures must use a generic message: `Invalid credentials`.
- Keep existing HTTP status codes unchanged for auth failures.
- Internal logs may include machine-readable failure reasons (for example, `invalid_credentials`, `membership_not_found`) to support incident response and debugging.
- Internal auth-failure logs should include correlation metadata when available (`request_id`, optional `X-Correlation-ID`).

## Implementation Notes
- Normalize auth errors before returning them to the client.
- Emit structured logs for failed auth attempts using sanitized fields only.
- Continue recording auth failure metrics by internal reason.

## Auth Failure Reason Codes
Use stable, non-PII auth failure codes in logs and metrics for SaaS auth flows:
- `invalid_credentials`
- `mfa_required`
- `mfa_invalid`
- `refresh_invalid`
- `refresh_expired`
- `membership_not_found`
- `org_not_found`
- `unknown`
