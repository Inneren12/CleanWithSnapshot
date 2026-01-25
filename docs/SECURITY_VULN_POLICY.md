# Vulnerability Gating & Waiver Policy

This policy defines the vulnerability thresholds that block merges, the remediation SLAs by severity,
and the waiver/exception process for time-bound risk acceptance.

## Severity thresholds (merge-block rules)

| Severity | Merge gate | Notes |
| --- | --- | --- |
| **CRITICAL** | **Always blocks merge** | No exceptions without an approved waiver. |
| **HIGH** | **Conditionally blocks merge** | Blocks when a fix is available or the vulnerability is reachable in our deployed image/application. Waiver required to proceed. |
| **MEDIUM** | Does not block | Must be tracked and remediated within SLA. |
| **LOW / UNKNOWN** | Does not block | Track and remediate as part of maintenance. |

**Conditional HIGH rule:** if a HIGH finding has a known fix or is reachable in the deployed runtime
(base image, OS package, or runtime dependency), it blocks merge unless an approved waiver is on file.
If no fix exists *and* the finding is non-reachable, it may proceed without a waiver, but must be tracked
until a fix is available.

## Remediation SLA

| Severity | SLA | Owner |
| --- | --- | --- |
| **CRITICAL** | 48 hours | Security owner + service owner |
| **HIGH** | 7 days | Service owner |
| **MEDIUM** | 30 days | Service owner |
| **LOW / UNKNOWN** | 90 days | Service owner |

The SLA clock starts when the issue is detected in CI or a production scan report.

## Waiver / Exception process

Waivers are time-bound, owned, and documented in `security/waivers.yml`.

### Requirements

- **Owner required:** Each waiver must list an accountable owner (team or individual).
- **Expiry required:** Every waiver must include an expiry date. Waivers **must not be indefinite**.
- **Scope required:** Include vulnerability identifiers, affected component, and justification.
- **Review required:** Waivers must be reviewed and re-approved before renewal.

### Waiver format

```yaml
waivers:
  - id: "CVE-2024-0000"
    severity: "HIGH"
    component: "python:3.11-slim (base image)"
    detected_in: "api image"
    justification: "No upstream fix available; not reachable in runtime path."
    owner: "security@company.com"
    approved_by: "security-lead"
    expires_on: "2025-01-31" # YYYY-MM-DD
    tracking_issue: "SEC-1234"
```

### Enforcement

- CI must validate that all waivers have **owner** and **expires_on** fields.
- Expired waivers are invalid and **do not** allow merges.
- Waivers should be removed as soon as the vulnerability is fixed.

## References

- Trivy scan reports (CI artifacts)
- `OPERATIONS.md` → Security Scanning
