# Admin Device Posture Policy (PR-SEC-ADMIN-POSTURE-01)

This document defines the **device posture requirements** for administrative access to the platform and how those checks are enforced at the **edge (Cloudflare Access / IdP)**. The backend **never evaluates device posture** and only trusts proxy headers after edge enforcement.

## Scope

**Applies to:**
- Admin API routes: `https://api.<domain>/v1/admin/*`
- Admin UI redirect: `https://<domain>/admin/*` (redirects to `/v1/admin/*`)

**Does not apply to:**
- Public APIs and user-facing web routes
- Non-admin service-to-service traffic

## Provider & enforcement point

**Provider:** Cloudflare Access (or equivalent IdP/access gateway) sitting in front of Caddy.

**Enforcement location:** Edge / Access policy only. Caddy and the backend do **not** evaluate device posture.

## Device posture policy (enforced at edge)

Cloudflare Access policy for **admin** resources must require **all** of the following posture checks when supported by the device posture provider:

1. **Managed device (MDM enrolled)**
   - Required when an MDM integration is available (e.g., Intune, Kandji, Jamf, Workspace ONE).
   - Enforced by Access device posture rules (MDM enrollment + compliant status).

2. **OS up-to-date (minimum versions)**
   - macOS: **13.6+**
   - Windows: **11 22H2+**
   - Ubuntu (or approved Linux): **22.04 LTS+**
   - Enforcement uses Access OS version posture rules.

3. **Disk encryption enabled**
   - macOS: FileVault enabled
   - Windows: BitLocker enabled
   - Enforcement uses Access disk encryption posture rules.

### Example Access policy (admin-only)

Apply this policy to the admin application or to the `/v1/admin/*` path:

- **Include:** Admin IdP group(s) (e.g., `admin`, `owner`, `dispatcher`, `accountant`, `viewer`)
- **Require:** MFA
- **Require device posture:**
  - MDM enrolled **AND** compliant
  - OS version >= minimums listed above
  - Disk encryption enabled

## Enforcement status (explicit)

**Enforced now (edge):**
- MFA at IdP/Access (required to reach Caddy)
- **Device posture checks listed above**, when supported by the configured Access provider

**Not enforced yet / gaps:**
- **MDM enrollment** if no MDM integration is connected to the Access provider
- **Disk encryption** if the Access provider cannot verify encryption status for the OS
- **Linux posture** if the Access provider lacks Linux device posture support

These gaps are acceptable only as documented exceptions below; they must be closed as soon as the provider capabilities are available.

## Exception handling

### Break-glass access (posture bypass)

Break-glass access may **bypass device posture** only under emergency conditions, but **must still require MFA** and must be **audited**.

Requirements:
- Use the existing break-glass workflow (`/v1/admin/break-glass/start`).
- Access policy must allow a **break-glass IdP group** that bypasses device posture checks but still requires MFA.
- All break-glass sessions are time-bound and logged.

### Temporary exceptions (time-bound, approved)

Temporary posture exceptions are allowed only with:
- Written approval from Security + Admin owner
- A **defined expiration date** (max 30 days)
- A documented ticket/change record

Access implementation:
- Use a **temporary Access policy** scoped to a named user or device that bypasses one specific posture check.
- Remove the exception by its expiration date and record the removal.

## Documentation & audit expectations

- Device posture requirements are **explicit** and must be listed in the Access policy and this document.
- Any exceptions (break-glass or temporary) must be logged with who/why/when and expiration.
- Backend logs must **not** include posture evaluation. Only edge enforcement is authoritative.

## Future hardening plan

1. **MDM integration**: connect Access to an MDM provider to enforce managed-device compliance for all admin users.
2. **Full posture coverage**: ensure disk encryption and OS version checks are available for all supported OSes.
3. **Device certificates** (optional): require mTLS or device certificates for admin access to reduce reliance on IP allowlists.
4. **Continuous compliance**: automate alerts for posture drift or expired temporary exceptions.
