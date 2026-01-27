# Security Exception (Waiver) Policy (PR-GOV-SEC-EXCEPTION-01)

## Purpose
This policy defines a **formal, auditable** process for granting **time-bound security exceptions** (waivers) when a security control must be bypassed temporarily. The default stance is **deny unless justified** and mitigated. Exceptions exist to keep the business operating **without losing security control**.

## Scope
Applies to **all security controls** documented in this repository, including (but not limited to):
- Edge/WAF protections
- Admin access controls (MFA, IP allowlists, device posture)
- Vulnerability gating and CI checks
- Operational security procedures

This policy **does not** replace incident response or break-glass workflows; those are separate, time-bound emergency procedures.

## What qualifies as an exception
An exception may be considered when **all** of the following are true:
1. A documented security control **cannot be met** for a justified, time-bound reason.
2. The request includes a **business justification** and **risk assessment**.
3. A **mitigation plan** is defined to reduce risk during the exception window.
4. An **expiry date** is included (required for temporary exceptions).

## What does NOT qualify
The following do **not** qualify as exceptions:
- Convenience or preference ("this is easier") without a measurable business impact.
- Permanent bypasses without scheduled review.
- Requests that lack mitigation, owner, or approval.
- Requests that conflict with legal/regulatory obligations.
- Requests that would disable **core security logging or audit trails**.

## Default stance: deny unless justified
The default decision is **deny** unless the request provides:
- Clear business impact if not granted.
- A time-bound window.
- Compensating controls to reduce exposure.
- Appropriate approvals by role.

## Mitigation requirement
All exceptions must include **compensating controls** appropriate to the risk level. Examples:
- Narrow scoping (specific user/IP/endpoint only)
- Enhanced monitoring/alerting
- Increased logging or change ticket references
- Temporary access windows

## Exception types
- **Temporary exception (default):** Must include an expiry date.
- **Permanent exception:** Rare and requires **mandatory review** at a fixed cadence.

## Approval roles (by risk level)
Approvals are by **role**, not by name.

| Risk Level | Required Approvals (all required) |
| --- | --- |
| Low | Security Owner + Service Owner |
| Medium | Security Owner + Service Owner + Ops Lead |
| High | Security Owner + Service Owner + Compliance/Risk Owner |

> The Security Owner is the final gate and may require additional review for any exception.

## Duration limits
- **Temporary exceptions:** Max **60 days** (default). Use **30 days** for high-risk controls or if uncertainty is high.
- **Permanent exceptions:** Must be reviewed **at least quarterly** and re-approved or revoked.

## Auto-expiry rules
- All temporary exceptions **auto-expire** on the stated date.
- **Expired exceptions are invalid** and must be removed immediately.
- Renewals require a **new request** and a fresh approval cycle.

## Process summary
1. **Request** submitted using `docs/SECURITY_EXCEPTION_FORM.md`.
2. **Risk review** performed by Security Owner (risk level assigned).
3. **Approvals** obtained based on risk level.
4. **Record** the approved exception in the exception register.
5. **Implement** mitigations and scoped bypass.
6. **Monitor** and **review** until expiry or renewal.

## Audit readiness
### Source of truth
- **Exception register:** `security/exception-register.yml` (approved exceptions only).
- **Evidence package:** each exception has a folder in `security/exceptions/<exception-id>/` containing:
  - Approved request form
  - Risk assessment notes
  - Approval evidence (email, ticket, or signature)
  - Implementation notes and rollback steps

### Listing active exceptions
To list active exceptions:
1. Open `security/exception-register.yml`.
2. Filter for entries with `status: approved`.
3. Validate `expires_on` is **today or in the future**.

### Proving reviews
- Each exception must include `reviewed_on` and `reviewed_by` fields in the register.
- Permanent exceptions must show quarterly review timestamps.
- Review evidence must be retained in the exception folder.

## Relationship to other policies
- Vulnerability waivers follow `docs/SECURITY_VULN_POLICY.md` and are stored in `security/waivers.yml`.
- Access review exceptions follow `docs/ACCESS_REVIEW_POLICY.md` and must be stored with quarterly evidence.

## Enforcement
Exceptions that are missing approvals, have expired, or lack mitigation are **invalid** and must be revoked immediately.
